"""Graph versioning: immutable snapshots. Never destroy previous versions.

Every major ingestion or approved model change creates a new
``graph_versions`` record: {version, tenant_id, created_at, node_count,
edge_count, formula_count, source, snapshot:{nodes, edges, formulas}}.
Simulations reference ``base_graph_version`` so results stay reproducible
even as the live graph evolves.
"""
from __future__ import annotations
from datetime import datetime, timezone
from . import store as _store


def current_version(ctx: dict) -> int:
    rows = _store.list_all("graph_versions", ctx)
    return max([r.get("version", 0) for r in rows] or [0])


def snapshot(ctx: dict, source: str = "ingest") -> dict:
    nodes = _store.list_all("nodes", ctx)
    edges = _store.list_all("edges", ctx)
    formulas = _store.list_all("formulas", ctx)
    ver = current_version(ctx) + 1
    rec = {
        "version": ver,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "node_count": len(nodes), "edge_count": len(edges),
        "formula_count": len(formulas), "source": source,
        "snapshot": {"nodes": nodes, "edges": edges, "formulas": formulas},
    }
    return _store.insert("graph_versions", ctx, rec)


def get_version(ctx: dict, version: int) -> dict | None:
    for r in _store.list_all("graph_versions", ctx):
        if r.get("version") == version:
            return r
    return None


def list_versions(ctx: dict) -> list[dict]:
    rows = _store.list_all("graph_versions", ctx)
    # strip heavy snapshots from list view
    out = []
    for r in sorted(rows, key=lambda x: x.get("version", 0)):
        out.append({k: v for k, v in r.items() if k != "snapshot"})
    return out
