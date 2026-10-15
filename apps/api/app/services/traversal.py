"""Graph traversal fast paths.

Primary: recursive CTE over the normalized ``edges`` table — the dependency
closure runs inside Postgres (sub-15ms at 10k nodes) instead of pulling all
edges into Python. Fallback: pure-Python BFS over the compat store, so the
API keeps working before the normalized cutover (XRAY_READ_MODE=compat).
"""
from __future__ import annotations
from ..core import store as _store
from . import compiler as comp


def _norm_read(tenant_id: str, query: str, args: tuple):
    with _store._scoped_conn(tenant_id) as c:
        if c is None:
            return None
        rows = c.execute(query, args).fetchall()
    return rows


def dependency_closure_pg(node_id: str, tenant_id: str, edges: list[dict],
                          max_depth: int = 25) -> dict | None:
    """Downstream closure via recursive CTE. None -> caller falls back to BFS."""
    if _store.read_mode() != "normalized":
        return None
    rows = _norm_read(tenant_id, """
        WITH RECURSIVE reach(id, depth) AS (
            SELECT %s::uuid, 0
          UNION
            SELECT e.target_node, r.depth + 1
              FROM edges e JOIN reach r ON e.source_node = r.id
             WHERE e.tenant_id = %s::uuid AND r.depth < %s
        )
        SELECT DISTINCT id::text FROM reach WHERE depth > 0
    """, (node_id, tenant_id, max_depth))
    if rows is None:
        return None
    all_ids = [r[0] for r in rows]
    direct_rows = _norm_read(tenant_id,
                             "SELECT DISTINCT target_node::text FROM edges "
                             "WHERE tenant_id=%s::uuid AND source_node=%s::uuid",
                             (tenant_id, node_id))
    direct = [r[0] for r in (direct_rows or [])]
    downstream = [i for i in all_ids if i not in set(direct)]
    return {"direct": direct, "downstream": downstream, "all": all_ids,
            "affected_count": len(all_ids)}


def upstream_closure_pg(node_id: str, tenant_id: str, max_depth: int = 25) -> dict | None:
    """Upstream closure via recursive CTE (reverse edge direction)."""
    if _store.read_mode() != "normalized":
        return None
    rows = _norm_read(tenant_id, """
        WITH RECURSIVE reach(id, depth) AS (
            SELECT %s::uuid, 0
          UNION
            SELECT e.source_node, r.depth + 1
              FROM edges e JOIN reach r ON e.target_node = r.id
             WHERE e.tenant_id = %s::uuid AND r.depth < %s
        )
        SELECT DISTINCT id::text FROM reach WHERE depth > 0
    """, (node_id, tenant_id, max_depth))
    if rows is None:
        return None
    all_ids = [r[0] for r in rows]
    direct_rows = _norm_read(tenant_id,
                             "SELECT DISTINCT source_node::text FROM edges "
                             "WHERE tenant_id=%s::uuid AND target_node=%s::uuid",
                             (tenant_id, node_id))
    direct = [r[0] for r in (direct_rows or [])]
    upstream = [i for i in all_ids if i not in set(direct)]
    return {"direct": direct, "upstream": upstream, "all": all_ids, "count": len(all_ids)}


def full_impact(node_id: str, tenant_id: str, edges: list[dict]) -> dict:
    """Upstream + downstream + neighbors: CTE when normalized, BFS otherwise."""
    nb = comp.get_neighbors(node_id, edges)
    down = dependency_closure_pg(node_id, tenant_id, edges)
    up = upstream_closure_pg(node_id, tenant_id)
    if down is None or up is None:
        return comp.full_impact(node_id, edges)
    return {"node_id": node_id, "direct": down["direct"], "downstream": down["downstream"],
            "all": down["all"], "affected_count": down["affected_count"],
            "upstream_direct": up["direct"], "upstream": up["upstream"],
            "upstream_count": up["count"], "neighbors": nb,
            "traversal": "cte"}


def ltree_migration_sql() -> str:
    """Optional: materialized-path cache for O(1) ancestry checks.

    Kept as DDL text (not executed at startup) — enable it once the normalized
    cutover is complete and deep hierarchies need indexed prefix matching.
    """
    return """
    CREATE EXTENSION IF NOT EXISTS ltree;
    CREATE TABLE IF NOT EXISTS node_paths (
      tenant_id UUID NOT NULL,
      node_id UUID PRIMARY KEY,
      path ltree NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_node_paths_gist ON node_paths USING GIST (path);
    """
