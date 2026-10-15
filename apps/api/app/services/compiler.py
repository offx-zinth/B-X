"""Graph Compiler: Business IR -> executable operational graph (nodes/edges + dependency graph)."""
from __future__ import annotations

try:
    from ..core.ontology import normalize_kind as _norm_kind, validate_edge_type as _validate_edge
except Exception:  # offline/service import without package context
    def _norm_kind(k):  # type: ignore
        return (k.title() if k else "Entity")
    def _validate_edge(t):  # type: ignore
        return t

def compile_ir(ir: dict, ctx: dict, store_insert, store_list=None, store_update=None) -> dict:
    """store_* injected for testability. Nodes merge by type within a tenant,
    so separate uploads interconnect: orders.csv + suppliers.csv share ONE
    Supplier node with edges from both files. Duplicate edges are skipped."""
    created_nodes, created_edges = [], []
    type_to_id: dict[str, str] = {}
    known: dict[str, dict] = {}
    if store_list:
        for n in store_list("nodes", ctx):
            known.setdefault(n["type"], n)
    for n in ir.get("nodes", []):
        normalized = n.get("properties") or {}
        kind = _norm_kind(n.get("kind", "Entity"))
        if n["type"] in known:
            saved = known[n["type"]]
            if store_update:
                props = dict(saved.get("properties") or {})
                props.setdefault("kind", kind)
                # Normalize legacy kinds already persisted (Metric/Location/...).
                if props.get("kind") not in ("Entity", "Actor", "Resource", "Process",
                                              "Task", "Event", "Transaction", "State",
                                              "Dependency", "Flow", "Capacity",
                                              "Constraint", "Time", "Cost"):
                    props["kind"] = _norm_kind(props.get("kind"))
                props["record_count"] = props.get("record_count", 0) + 1
                # Never clobber an existing value with a re-discovered one.
                for k, v in normalized.items():
                    props.setdefault(k, v)
                saved = store_update("nodes", ctx, saved["id"], {"properties": props}) or saved
                known[n["type"]] = saved
            type_to_id[n["type"]] = saved["id"]; created_nodes.append(saved)
            continue
        obj = {"type": n["type"], "name": n["type"],
               "properties": {"kind": kind, "examples": n.get("examples", [])[:1],
                              "record_count": 1, **normalized},
               "state": "active", "confidence": 0.85}
        saved = store_insert("nodes", ctx, obj)
        known[n["type"]] = saved
        type_to_id[n["type"]] = saved["id"]; created_nodes.append(saved)
    seen_edges = set()
    if store_list:
        for e in store_list("edges", ctx):
            seen_edges.add((e["source_node"], e["target_node"], e["type"]))
    for e in ir.get("edges", []):
        s = type_to_id.get(e["source_type"]); t = type_to_id.get(e["target_type"])
        if not s or not t: continue
        etype = _validate_edge(e["type"])
        if (s, t, etype) in seen_edges: continue
        seen_edges.add((s, t, etype))
        saved = store_insert("edges", ctx, {"source_node": s, "target_node": t, "type": etype, "properties": {"via": e.get("via","")}})
        created_edges.append(saved)
    return {"nodes": created_nodes, "edges": created_edges}

def dependency_closure(node_id: str, edges: list[dict]) -> dict:
    """BFS downstream from node_id. Returns {direct:[ids], downstream:[ids], all:[ids]}"""
    children: dict[str, list[str]] = {}
    for e in edges:
        children.setdefault(e["source_node"], []).append(e["target_node"])
    direct = children.get(node_id, [])
    seen = set(direct); frontier = list(direct); downstream = []
    while frontier:
        cur = frontier.pop(0)
        for nxt in children.get(cur, []):
            if nxt not in seen:
                seen.add(nxt); downstream.append(nxt); frontier.append(nxt)
    return {"direct": direct, "downstream": downstream, "all": list(seen), "affected_count": len(seen)}


def upstream_closure(node_id: str, edges: list[dict]) -> dict:
    """BFS upstream (all ancestors). Returns {direct, upstream, all, count}."""
    parents: dict[str, list[str]] = {}
    for e in edges:
        parents.setdefault(e["target_node"], []).append(e["source_node"])
    direct = parents.get(node_id, [])
    seen = set(direct); frontier = list(direct); upstream: list[str] = []
    while frontier:
        cur = frontier.pop(0)
        for prev in parents.get(cur, []):
            if prev not in seen:
                seen.add(prev); upstream.append(prev); frontier.append(prev)
    return {"direct": direct, "upstream": upstream, "all": list(seen), "count": len(seen)}


def get_neighbors(node_id: str, edges: list[dict]) -> dict:
    """One-hop neighbourhood in both directions."""
    out = [e for e in edges if e.get("source_node") == node_id]
    inn = [e for e in edges if e.get("target_node") == node_id]
    return {"outgoing": out, "incoming": inn,
            "out_ids": [e["target_node"] for e in out],
            "in_ids": [e["source_node"] for e in inn]}


def trace_path(source_id: str, target_id: str, edges: list[dict]) -> dict:
    """BFS shortest path. Returns {path:[edges], node_ids:[ids], found:bool}."""
    from collections import deque
    adj: dict[str, list[dict]] = {}
    for e in edges:
        adj.setdefault(e.get("source_node"), []).append(e)
    q = deque([(source_id, [])]); seen = {source_id}
    while q:
        cur, path = q.popleft()
        if cur == target_id:
            return {"path": path, "node_ids": [source_id] + [e["target_node"] for e in path],
                    "found": True, "hops": len(path)}
        for e in adj.get(cur, []):
            nxt = e.get("target_node")
            if nxt not in seen:
                seen.add(nxt); q.append((nxt, path + [e]))
    return {"path": [], "node_ids": [], "found": False, "hops": 0}


def full_impact(node_id: str, edges: list[dict]) -> dict:
    """Upstream + downstream + neighbours in one call for impact analysis UI."""
    down = dependency_closure(node_id, edges)
    up = upstream_closure(node_id, edges)
    nb = get_neighbors(node_id, edges)
    return {"node_id": node_id, "direct": down["direct"], "downstream": down["downstream"],
            "all": down["all"], "affected_count": down["affected_count"],
            "upstream_direct": up["direct"], "upstream": up["upstream"],
            "upstream_count": up["count"], "neighbors": nb}
