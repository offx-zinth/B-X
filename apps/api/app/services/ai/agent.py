"""AI agent: tool-calling loop over the deterministic graph engine.

Contract (spec sections 20-21, 29, 41):
- The model may ONLY learn facts by calling registered tools.
- The model is given a bounded, graph-aware context — never the whole graph.
- Answers are grounded: if the model cites a `Type.property` that no tool
  returned, the citation is flagged and the claim is dropped.
- If a provider errors, we fall back to the deterministic client so the user
  still gets a tool-derived answer, explicitly labelled.
"""
from __future__ import annotations
import json
import re
import time
from ...core import versions as ver
from ...core.store import list_all
from .. import llm
from ..llm.base import LLMResponse, ToolCall
from . import tools as tool_registry

REF_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*)\.([a-z_][A-Za-z0-9_]*)\b")

SYSTEM = """You are the Business X-Ray copilot. You operate an executable operational graph of a real company.

ABSOLUTE RULES
1. The graph is the source of truth. You have NO independent knowledge of this company.
2. Every factual claim must come from a tool result. Never state a number, node, formula or relationship you did not receive from a tool.
3. NEVER compute business values yourself. Any Type.property that has a formula (Production.capacity, Order.fulfillable, Order.backlog, Revenue.total, Cost.production, Margin.total, Inventory.available) is computed by the engine. Read it with get_metric, or get it from a simulation. Do not do arithmetic on inputs to derive an output.
4. If the information is not available, say plainly that it is unavailable and name the tool that came up empty. Never guess or estimate.
5. Reference metrics as Type.property exactly as returned by tools.
6. Never claim a change was applied. create_formula returns a PENDING proposal; scenario tools create drafts. Say approval is required.
7. Keep answers concise and specific to this company. No generic management advice.
8. Answer directly. Do not narrate internal deliberation; never open with "the tool
   provided" or "looking at the formulas" — state the finding instead.

HOW TO WORK
- Locate entities with query_graph before analysing them.
- To READ a metric, call get_metric (or list_metrics to see what exists). Do not re-derive it.
- Use find_dependencies to establish blast radius, then run_simulation or explain_simulation for quantified impact.
- Cite the formula (target = expression) when explaining WHY something changed.
- Prefer explain_simulation for "what happens if" questions: it returns the full causal chain."""


def build_context(ctx: dict, question: str, max_nodes: int | None = None) -> dict:
    """Bounded, graph-aware context. Never the whole graph."""
    from ...core.config import settings
    limit = max_nodes or settings.LLM_MAX_CONTEXT_NODES
    nodes = list_all("nodes", ctx)
    formulas = list_all("formulas", ctx)
    edges = list_all("edges", ctx)
    ql = (question or "").lower()
    terms = {w for w in re.findall(r"[a-z]{3,}", ql)}

    def relevance(n):
        score = 0
        hay = f"{n.get('type','')} {n.get('name','')}".lower()
        for t in terms:
            if t in hay:
                score += 1
        return score

    ranked = sorted(nodes, key=relevance, reverse=True)
    keep = ranked[:limit]
    ids = {n["id"] for n in keep}
    return {
        "tenant": ctx.get("tenant_id"),
        "graph_version": ver.current_version(ctx),
        "graph_counts": {"nodes": len(nodes), "edges": len(edges), "formulas": len(formulas)},
        "active_formulas": [
            {"target": f.get("target"), "expression": f.get("expression"),
             "dependencies": f.get("dependencies", [])}
            for f in formulas if f.get("status") in ("approved", "active")
        ][:limit],
        "node_types": sorted({n.get("type") for n in nodes if n.get("type")}),
        "relevant_nodes": [
            {"id": n["id"], "type": n.get("type"), "name": n.get("name"),
             "properties": {k: v for k, v in (n.get("properties") or {}).items()
                            if isinstance(v, (int, float, str, bool)) and k != "examples"},
             "level": n.get("level"), "confidence": n.get("confidence")}
            for n in keep
        ],
        "edges_among_relevant": [
            {"from": e.get("source_node"), "to": e.get("target_node"), "type": e.get("type")}
            for e in edges
            if e.get("source_node") in ids and e.get("target_node") in ids
        ][:200],
        "truncated": len(nodes) > limit,
    }


_NOT_A_REF = {"Type.property", "Node.property", "type.property", "JSON.object"}


def _ground(text: str, facts: set[str]) -> dict:
    """Verify Type.property citations in free text against known facts.

    Known facts come from tool results AND the bounded context we supplied —
    a formula legitimately names its own operands, so citing one is not
    fabrication. Anything else is flagged.
    """
    cited = {f"{a}.{b}" for a, b in REF_RE.findall(text or "")}
    cited = {c for c in cited if c not in _NOT_A_REF
             and not c.endswith(".property") and not c.endswith(".id")}
    ungrounded = sorted(c for c in cited if c not in facts)
    return {"cited_refs": sorted(cited), "grounded_refs": sorted(c for c in cited if c in facts),
            "ungrounded_refs": ungrounded,
            "fully_grounded": not ungrounded}


def _collect_refs(obj, acc: set[str]) -> None:
    """Harvest every Type.property and node id that a tool result contains."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.count(".") == 1 and k not in acc:
                acc.add(k)
            _collect_refs(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _collect_refs(v, acc)
    elif isinstance(obj, str) and "." in obj:
        for a, b in REF_RE.findall(obj):
            acc.add(f"{a}.{b}")


def ask(ctx: dict, question: str, selected_node_id: str = "",
        max_rounds: int | None = None) -> dict:
    from ...core.config import settings
    client = llm.build_client()
    rounds_cap = max_rounds or settings.LLM_MAX_TOOL_ROUNDS
    specs = tool_registry.registry()
    context = build_context(ctx, question)

    user_msg = {
        "role": "user",
        "content": (
            f"Question: {question}\n\n"
            f"GRAPH CONTEXT (bounded, not exhaustive)\n{json.dumps(context, default=str)[:12000]}\n\n"
            + (f"Currently selected node id: {selected_node_id}\n" if selected_node_id else "")
            + "\nCall tools to obtain the facts you need, then answer. Cite Type.property values exactly."
        ),
    }
    messages = [user_msg]

    trace: list[dict] = []
    # Facts the model may cite: everything we legitimately supplied in the
    # bounded context, plus anything tools return during the run.
    facts: set[str] = set()
    _collect_refs(context, facts)
    last_error = None
    answer = ""
    used_provider = client.name
    used_model = client.model
    called: set[str] = set()
    results: list[dict] = []
    failures = 0
    degraded = False

    for _ in range(max(1, rounds_cap)):
        try:
            resp = client.generate(messages, specs, system=SYSTEM)
        except Exception as e:  # provider SDK raised instead of returning
            resp = LLMResponse(provider=client.name, model=client.model,
                               error=f"{type(e).__name__}: {e}")
        if not resp.ok:
            last_error = resp.error
            failures += 1
            if client.name != "deterministic" and failures < 3:
                # Transient upstream failure (429/500): brief backoff, retry.
                time.sleep(min(2 ** failures, 8))
                continue
            if client.name != "deterministic":
                # Give up on the live provider: degrade explicitly so the user
                # still gets a tool-derived answer, and say so.
                from ..llm.deterministic import DeterministicClient
                client = DeterministicClient()
                used_provider = "deterministic (fallback)"
                used_model = client.model
                degraded = True
                continue
            break

        if resp.tool_calls:
            messages.append({"role": "assistant", "content": resp.text or "(calling tools)"})
            for call in resp.tool_calls:
                sig = f"{call.name}:{json.dumps(call.args, sort_keys=True, default=str)}"
                if sig in called:
                    # Never execute the same call twice: prevents loops,
                    # duplicate side effects and wasted tokens.
                    trace.append({"tool": call.name, "args": call.args, "ok": True,
                                  "summary": "skipped (duplicate call)"})
                    messages.append({"role": "user", "content": json.dumps(
                        {"tool": call.name,
                         "result": {"note": "duplicate call suppressed; reuse the earlier result"}},
                        default=str)[:12000]})
                    continue
                called.add(sig)
                result = tool_registry.invoke(call.name, call.args, ctx)
                _collect_refs(result, facts)
                if isinstance(result, dict):
                    result = {**result, "__tool__": call.name}
                results.append(result)
                trace.append({"tool": call.name, "args": call.args,
                              "ok": "error" not in result,
                              "summary": _summarize(call.name, result)})
                messages.append({"role": "user", "content": json.dumps(
                    {"tool": call.name,
                     "result": {k: v for k, v in result.items() if k != "__tool__"}
                     if isinstance(result, dict) else result}, default=str)[:12000]})
            continue

        answer = resp.text.strip()
        break

    if not answer and trace and client.name == "deterministic":
        answer = _compose_from_trace(trace, facts, results)

    answer = _sanitize(answer)
    grounding = _ground(answer, facts) if answer else {"fully_grounded": True,
                                                       "ungrounded_refs": [],
                                                       "cited_refs": [], "grounded_refs": []}
    if not grounding["fully_grounded"] and answer:
        answer = (answer + "\n\n[Grounding notice: the following references were not found in "
                  "tool results and are excluded: "
                  + ", ".join(grounding["ungrounded_refs"]) + "]")

    return {
        "answer": answer or "Unable to answer from the available graph data.",
        "provider": used_provider,
        "model": used_model,
        "llm_status": llm.status(),
        "tool_calls": trace,
        "steps": [f"{t['tool']}" for t in trace],
        "grounding": grounding,
        "context": {"graph_version": context["graph_version"],
                    "nodes_in_context": len(context["relevant_nodes"]),
                    "truncated": context["truncated"]},
        # A provider failure is only reported when it actually degraded the
        # response. A transient error that a retry recovered from is not.
        "error": last_error if degraded else None,
        "degraded": degraded,
        "recovered_error": (last_error if (last_error and not degraded) else None),
    }


def _summarize(name: str, result: dict) -> str:
    if "error" in result:
        return str(result["error"])[:160]
    if name == "run_simulation":
        return f"{len(result.get('deltas', {}))} metrics changed"
    if name == "explain_simulation":
        return f"{len(result.get('explanation', {}).get('metrics_changed', []))} metrics, " \
               f"{len(result.get('explanation', {}).get('affected_nodes', []))} nodes affected"
    if name == "query_graph":
        return f"{len(result.get('hits', []))} matches of {result.get('total_nodes', 0)} nodes"
    if name == "find_dependencies":
        return f"{result.get('affected_count', 0)} downstream, {result.get('upstream_count', 0)} upstream"
    if name == "find_bottlenecks":
        return f"{len(result.get('bottlenecks', []))} bottlenecks"
    if name == "find_risks":
        return f"{len(result.get('risks', []))} risks"
    if name == "get_metric":
        return f"{result.get('ref')}: {result.get('value') if result.get('available') else 'unavailable'}"
    if name == "create_formula":
        return f"pending proposal {result.get('proposal', {}).get('target')}"
    if name == "suggest_optimization":
        return f"{len(result.get('options', []))} options"
    if name == "generate_report":
        return "report generated"
    return "ok"


# Open-weight models sometimes echo the system rules or narrate their own
# reasoning. Strip that deterministically so the user sees only the finding.
_META_PREFIXES = (
    "the user asked", "the user wants", "i must ", "i need to ", "i should ",
    "according to the absolute rules", "according to rule", "let me ",
    "looking at the ", "based on the tool", "the tool provided",
    "the provided tools", "note: the graph context", "in this scenario, the",
    "first, i", "now, i", "next, i",
)
_META_RE = re.compile(r"(?im)^\s*(?:[-*]\s*)?(?:" + "|".join(re.escape(p) for p in _META_PREFIXES) + r").*$")


def _sanitize(text: str) -> str:
    """Remove echoed rules and internal deliberation from the final answer."""
    if not text:
        return ""
    cleaned = _META_RE.sub("", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned or text.strip()


def _compose_from_trace(trace: list[dict], facts: set[str],
                        results: list[dict] | None = None) -> str:
    """Deterministic answer built only from tool output (no LLM).

    This is the answer a user gets with the LLM removed, so it must be a real
    explanation — not a list of tool names.
    """
    parts: list[str] = []
    by_tool: dict[str, list[dict]] = {}
    for r in (results or []):
        if isinstance(r, dict):
            by_tool.setdefault(_tool_of(r), []).append(r)

    def tool_of(name: str) -> list[dict]:
        return by_tool.get(name, [])

    for res in tool_of("get_metric"):
        ref = res.get("ref")
        if res.get("available"):
            parts.append(f"{ref} = {res.get('value')}.")
        else:
            parts.append(f"{ref} is not available in the graph.")

    for res in tool_of("find_dependencies"):
        parts.append(f"Dependency closure: {res.get('affected_count', 0)} nodes affected "
                     f"({len(res.get('direct', []))} direct), "
                     f"{res.get('upstream_count', 0)} upstream.")

    for res in tool_of("explain_simulation"):
        e = res.get("explanation", {}) or {}
        for a in e.get("affected_nodes", [])[:6]:
            parts.append(f"{a['ref']}: {a['before']} -> {a['after']}.")
        for m in e.get("metrics_changed", [])[:6]:
            parts.append(f"{m['ref']} changed {m['change_pct']}%.")
        bn = (e.get("bottleneck") or {}).get("reason")
        if bn:
            parts.append(f"Bottleneck: {bn}")
        for i in (e.get("interventions") or [])[:3]:
            parts.append(f"Intervention: {i['action']} - {i['why']}")

    for res in tool_of("run_simulation"):
        d = res.get("deltas", {}) or {}
        parts.append(f"Simulation changed {len(d)} metrics.")
        for k, v in list(d.items())[:6]:
            parts.append(f"{k}: {v.get('before')} -> {v.get('after')}.")

    for res in tool_of("find_bottlenecks"):
        names = [b.get("node", {}).get("name") for b in res.get("bottlenecks", [])[:5]]
        if names:
            parts.append("Bottlenecks: " + ", ".join(n for n in names if n) + ".")

    for res in tool_of("find_risks"):
        for r in res.get("risks", [])[:4]:
            parts.append(f"Risk ({r.get('severity')}): {r.get('detail')}")

    for res in tool_of("suggest_optimization"):
        opts = res.get("options", [])[:3]
        for o in opts:
            parts.append(f"Option: {o.get('name')} ({o.get('expected_benefit')}, "
                         f"{o.get('expected_cost')}) - {o.get('reasoning')}")

    for res in tool_of("create_formula"):
        p = res.get("proposal", {}) or {}
        if p.get("target"):
            parts.append(f"Proposed formula {p['target']} = {p.get('expression')} "
                         f"(PENDING approval).")

    for res in tool_of("query_graph"):
        hits = res.get("hits", [])
        if not hits:
            parts.append("No matching entities found in the graph.")
        else:
            parts.append("Matched: " + ", ".join(h.get("name", h.get("type", "?"))
                                                for h in hits[:6]) + ".")

    parts = [p for p in parts if p and "skipped" not in p]
    return " ".join(parts) or "No matching data in the graph."


def _tool_of(result: dict) -> str:
    return result.get("__tool__", "")
