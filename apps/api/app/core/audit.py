"""Audit log: every material action is recorded with before/after.

Collections: ``audit_log`` rows carry tenant_id, user, timestamp, action,
resource, before, after, metadata. Reads are tenant-scoped; writes happen
inside routers via :func:`record`.
"""
from __future__ import annotations
from datetime import datetime, timezone
from . import store as _store


def record(ctx: dict, action: str, resource: str,
           before: dict | None = None, after: dict | None = None,
           metadata: dict | None = None) -> dict:
    entry = {
        "user_id": ctx.get("user_id", ""),
        "email": ctx.get("email", ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "resource": resource,
        "before": before or {},
        "after": after or {},
        "metadata": metadata or {},
    }
    return _store.insert("audit_log", ctx, entry)


def list_for_tenant(ctx: dict, limit: int = 100) -> list[dict]:
    rows = _store.list_all("audit_log", ctx)
    rows.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return rows[: max(1, min(limit, 500))]
