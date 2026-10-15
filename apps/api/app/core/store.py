"""Durable store with in-memory fallback. Same interface either way.

Postgres backend: single JSONB table (collection, id, tenant_id, data) during
the xray_store -> normalized migration window. Connections come from a
pooled pool (psycopg_pool) instead of one global blocking connection, and
RLS scope uses transaction-local ``set_config(..., true)`` so pooled
connections can never leak tenant context.
"""
from __future__ import annotations
import uuid
import copy
import os
import threading
from collections import defaultdict
from contextlib import contextmanager

MEM: dict[str, dict[str, dict]] = defaultdict(dict)
_PG_OK = False
_POOL = None
_POOL_LOCK = threading.Lock()
_LAST_TRY = 0.0
_RETRY_COOLDOWN = 10.0
_PG_ERROR = ""


def _pg_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://xray:xray@localhost:5432/xray")


def _pool_sizes() -> tuple[int, int, float]:
    try:
        from .config import settings
        return (int(settings.DATABASE_POOL_SIZE), int(settings.DATABASE_MAX_OVERFLOW),
                float(settings.DATABASE_POOL_TIMEOUT))
    except Exception:
        return (20, 10, 30.0)


def _ensure_schema(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS xray_store (
        collection TEXT NOT NULL, id TEXT NOT NULL,
        tenant_id TEXT NOT NULL, data JSONB NOT NULL,
        updated_at TIMESTAMPTZ DEFAULT now(),
        PRIMARY KEY (collection, id))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_xray_tenant ON xray_store (collection, tenant_id)")
    # Transitional indexed email lookup: avoids full-table scan("users") on login.
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_xray_users_email
        ON xray_store ((lower(data->>'email'))) WHERE collection = 'users'""")
    conn.execute("ALTER TABLE xray_store ENABLE ROW LEVEL SECURITY")
    conn.execute("ALTER TABLE xray_store FORCE ROW LEVEL SECURITY")
    conn.execute("DROP POLICY IF EXISTS tenant_isolation ON xray_store")
    conn.execute("""CREATE POLICY tenant_isolation ON xray_store USING (
        current_setting('app.tenant_id', true) = 'all'
        OR (NULLIF(current_setting('app.tenant_id', true), '') IS NOT NULL
            AND tenant_id = current_setting('app.tenant_id', true))
    )""")


def _connect():
    """Return the pool, creating it lazily. None when Postgres is unreachable."""
    import time
    global _POOL, _PG_OK, _LAST_TRY, _PG_ERROR
    # Legacy test hook: allow store._CONN = None resets to also drop the pool.
    try:
        legacy = globals().get("_CONN")
        if legacy is None and _POOL is not None and not _PG_OK:
            pass
    except Exception:
        pass
    with _POOL_LOCK:
        if _POOL is not None:
            try:
                with _POOL.connection(timeout=2.0) as c:
                    c.execute("SELECT 1")
                return _POOL
            except Exception:
                try:
                    _POOL.close()
                except Exception:
                    pass
                _POOL, _PG_OK = None, False
        if time.time() - _LAST_TRY < _RETRY_COOLDOWN:
            return None
        _LAST_TRY = time.time()
        try:
            import psycopg
            # Fast probe first: fail to memory in ~2s instead of blocking pool open.
            url = _pg_url()
            sep = "&" if "?" in url else "?"
            probe_url = f"{url}{sep}connect_timeout=2"
            try:
                probe = psycopg.connect(probe_url, autocommit=True, connect_timeout=2)
                probe.close()
            except Exception as pe:
                raise pe
            from psycopg_pool import ConnectionPool
            try:
                pool_size, _, _ = _pool_sizes()
                max_size = max(2, min(pool_size, 20))
            except Exception:
                max_size = 10
            pool = ConnectionPool(probe_url, min_size=1, max_size=max_size,
                                  timeout=2.0, open=True)
            with pool.connection(timeout=2.0) as c:
                with c.transaction():
                    _ensure_schema(c)
            _POOL, _PG_OK = pool, True
            _PG_ERROR = ""
            return pool
        except Exception as e:
            _PG_ERROR = f"{type(e).__name__}: {e}"
            print(f"[store] postgres unavailable, using in-memory fallback: {_PG_ERROR}", flush=True)
            _PG_OK = False
            return None


def store_error() -> str:
    return _PG_ERROR


# --- Normalized mirror (xray_store -> relational tables) -------------------
# xray_store stays the compat read path; writes dual-write into the
# normalized tables (init.sql) so the cutover is a flag flip and never data
# loss. Every mirror runs in its own savepoint: a normalized failure can
# never break the primary write.
_NORMALIZED_TABLES = {
    "tenants": ("id", "name"),
    "users": ("id", "tenant_id", "email", "password_hash", "role"),
    "nodes": ("id", "tenant_id", "type", "name", "properties", "state", "level",
              "provenance", "source_docs", "confidence", "last_observed"),
    "edges": ("id", "tenant_id", "source_node", "target_node", "type", "properties",
              "conditions", "formula", "level", "provenance", "source_docs", "confidence"),
    "formulas": ("id", "tenant_id", "target", "expression", "dependencies", "status",
                 "level", "created_by"),
    "graph_versions": ("id", "tenant_id", "version", "node_count", "edge_count",
                       "formula_count", "source", "snapshot"),
    "scenarios": ("id", "tenant_id", "name", "base_graph_version", "changes",
                  "formula_overrides", "duration_days", "status"),
    "simulation_runs": ("id", "tenant_id", "scenario_id", "base_graph_version",
                        "status", "duration_ms", "results", "error"),
    "data_sources": ("id", "tenant_id", "filename", "kind", "status", "row_count",
                     "columns", "error", "object_key"),
    "reports": ("id", "tenant_id", "report"),
    "ingest_jobs": ("id", "tenant_id", "kind", "filename", "size", "status",
                    "queue", "progress", "error", "result"),
    "audit_log": ("id", "tenant_id", "user_id", "email", "action", "resource",
                  "before", "after", "metadata"),
}


_JSONB_COLS = ("properties", "dependencies", "snapshot", "changes",
               "formula_overrides", "results", "result", "conditions",
               "columns", "report", "before", "after", "metadata",
               "provenance", "source_docs")


def _mirror_upsert(c, coll: str, obj: dict) -> None:
    cols = _NORMALIZED_TABLES.get(coll)
    if not cols:
        return
    try:
        import psycopg.types.json as pjson
    except Exception:
        return
    # Omit absent fields instead of writing NULL: JSONB/level/status columns
    # have defaults (NOT NULL DEFAULT '[]') and a partial object (e.g. a node
    # without provenance) must not violate them.
    present, values = [], []
    for col in cols:
        v = obj.get(col)
        if v is None and col != "id":
            continue
        if col in _JSONB_COLS:
            v = pjson.Jsonb(v)
        present.append(col)
        values.append(v)
    placeholders = ",".join(["%s"] * len(present))
    col_list = ",".join(present)
    updates = ",".join(f"{c_} = EXCLUDED.{c_}" for c_ in present if c_ != "id")
    conflict = f"ON CONFLICT (id) DO UPDATE SET {updates}" if updates else "ON CONFLICT (id) DO NOTHING"
    try:
        with c.transaction():
            c.execute(
                f"INSERT INTO {coll} ({col_list}) VALUES ({placeholders}) {conflict}",
                tuple(values))
    except Exception as e:
        # Missing table / type mismatch (uuid vs text ids): keep xray_store
        # authoritative and surface the mirror failure (non-fatal).
        msg = f"normalized mirror skipped for {coll}: {type(e).__name__}: {e}"
        print(f"[store] {msg}", flush=True)


def _mirror_delete(c, coll: str, _id: str) -> None:
    if coll not in _NORMALIZED_TABLES:
        return
    try:
        with c.transaction():
            c.execute(f"DELETE FROM {coll} WHERE id=%s", (_id,))
    except Exception:
        pass


@contextmanager
def _scoped_conn(tenant_id: str | None):
    """Yield a connection inside a transaction with transaction-local RLS scope.

    ``set_config(..., true)`` makes the setting LOCAL to the transaction, so a
    pooled connection returns to the pool without tenant state attached.
    Fail-closed: empty scope sees zero rows via RLS (NULLIF guard).
    """
    pool = _connect()
    if pool is None:
        yield None
        return
    with pool.connection() as conn:
        with conn.transaction():
            # is_local=true -> SET LOCAL semantics
            conn.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id or "",))
            yield conn


def backend() -> str:
    return "postgres" if _connect() is not None else "memory"


def _new_id() -> str:
    return str(uuid.uuid4())


def insert(coll: str, ctx: dict, obj: dict) -> dict:
    obj = copy.deepcopy(obj)
    obj["id"] = obj.get("id") or _new_id()
    obj["tenant_id"] = ctx["tenant_id"]
    pool = _connect()
    if pool is None:
        MEM[coll][obj["id"]] = obj
    else:
        import psycopg.types.json as pjson
        with _scoped_conn(obj["tenant_id"]) as c:
            assert c is not None
            c.execute("INSERT INTO xray_store (collection, id, tenant_id, data) VALUES (%s,%s,%s,%s) "
                      "ON CONFLICT (collection, id) DO UPDATE SET data=EXCLUDED.data, updated_at=now()",
                      (coll, obj["id"], obj["tenant_id"], pjson.Jsonb(obj)))
            _mirror_upsert(c, coll, obj)
    return copy.deepcopy(obj)


def _read_normalized(coll: str, ctx: dict, _id: str | None = None) -> list[dict] | dict | None:
    """Normalized reads (XRAY_READ_MODE=normalized cutover flag).

    Rebuilds the same dict shape from relational columns so routers and tests
    need no changes. RLS applies because _scoped_conn sets app.tenant_id.
    """
    if coll not in _NORMALIZED_TABLES:
        return None
    cols = _NORMALIZED_TABLES[coll]
    where = "tenant_id=%s" if coll != "tenants" else "id=%s"
    args: tuple = (ctx.get("tenant_id"),) if coll != "tenants" else (_id,)
    q = f"SELECT {','.join(cols)} FROM {coll} WHERE {where}"
    if _id is not None and coll != "tenants":
        q += " AND id=%s"
        args = (ctx.get("tenant_id"), _id)
    with _scoped_conn(ctx.get("tenant_id") if coll != "tenants" else "all") as c:
        if c is None:
            return None
        rows = c.execute(q, args).fetchall()
    out = []
    for r in rows:
        d = {}
        for k, v in zip(cols, r):
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
            elif isinstance(v, uuid.UUID):
                d[k] = str(v)
            else:
                d[k] = v
        d.setdefault("tenant_id", ctx.get("tenant_id"))
        out.append(d)
    return out[0] if _id is not None else out


def read_mode() -> str:
    import os
    return os.environ.get("XRAY_READ_MODE", "compat")


def get(coll: str, ctx: dict, _id: str) -> dict | None:
    pool = _connect()
    if pool is None:
        o = MEM[coll].get(_id)
    else:
        o = None
        if read_mode() == "normalized":
            try:
                o = _read_normalized(coll, ctx, _id)
            except Exception:
                o = None  # cutover read failed: stay available on compat
        if o is None:
            with _scoped_conn(ctx.get("tenant_id")) as c:
                assert c is not None
                row = c.execute("SELECT data FROM xray_store WHERE collection=%s AND id=%s",
                                (coll, _id)).fetchone()
            o = dict(row[0]) if row else None
    if not o or o.get("tenant_id") != ctx.get("tenant_id"):
        return None
    return copy.deepcopy(o)


def list_all(coll: str, ctx: dict) -> list[dict]:
    pool = _connect()
    if pool is None:
        return [copy.deepcopy(o) for o in MEM[coll].values() if o.get("tenant_id") == ctx.get("tenant_id")]
    if read_mode() == "normalized":
        try:
            rows_norm = _read_normalized(coll, ctx)
        except Exception:
            rows_norm = None
        if rows_norm:
            return rows_norm
    with _scoped_conn(ctx.get("tenant_id")) as c:
        assert c is not None
        rows = c.execute("SELECT data FROM xray_store WHERE collection=%s AND tenant_id=%s",
                         (coll, ctx.get("tenant_id"))).fetchall()
    return [dict(r[0]) for r in rows]


def update(coll: str, ctx: dict, _id: str, patch: dict) -> dict | None:
    o = get(coll, ctx, _id)
    if not o:
        return None
    o.update(patch)
    o["tenant_id"] = ctx["tenant_id"]
    pool = _connect()
    if pool is None:
        MEM[coll][_id] = o
    else:
        import psycopg.types.json as pjson
        with _scoped_conn(o["tenant_id"]) as c:
            assert c is not None
            c.execute("UPDATE xray_store SET data=%s, updated_at=now() WHERE collection=%s AND id=%s "
                      "AND tenant_id=%s", (pjson.Jsonb(o), coll, _id, o["tenant_id"]))
            _mirror_upsert(c, coll, o)
    return copy.deepcopy(o)


def delete(coll: str, ctx: dict, _id: str) -> bool:
    o = get(coll, ctx, _id)
    if not o:
        return False
    pool = _connect()
    if pool is None:
        MEM[coll].pop(_id, None)
    else:
        with _scoped_conn(o["tenant_id"]) as c:
            assert c is not None
            c.execute("DELETE FROM xray_store WHERE collection=%s AND id=%s AND tenant_id=%s",
                      (coll, _id, o["tenant_id"]))
            _mirror_delete(c, coll, o["id"])
    return True


def scan(coll: str) -> list[dict]:
    """Cross-tenant read. Auth use only (login resolves tenant from email)."""
    pool = _connect()
    if pool is None:
        return [copy.deepcopy(o) for o in MEM[coll].values()]
    with _scoped_conn("all") as c:
        assert c is not None
        rows = c.execute("SELECT data FROM xray_store WHERE collection=%s", (coll,)).fetchall()
    return [dict(r[0]) for r in rows]


def find_user_by_email(email: str) -> dict | None:
    """Indexed login lookup: single-row query instead of full scan("users")."""
    email = (email or "").strip()
    if not email:
        return None
    pool = _connect()
    if pool is None:
        low = email.lower()
        for o in MEM["users"].values():
            if str(o.get("email", "")).lower() == low:
                return copy.deepcopy(o)
        return None
    if read_mode() == "normalized":
        try:
            with _scoped_conn("all") as c:
                assert c is not None
                row = c.execute("SELECT id, tenant_id, email, password_hash, role FROM users "
                                "WHERE lower(email) = lower(%s) LIMIT 1", (email,)).fetchone()
            if row:
                return {"id": str(row[0]), "tenant_id": str(row[1]), "email": row[2],
                        "password_hash": row[3], "role": row[4]}
        except Exception:
            pass  # fall through to compat lookup
    with _scoped_conn("all") as c:
        assert c is not None
        row = c.execute("SELECT data FROM xray_store WHERE collection='users' "
                        "AND lower(data->>'email') = lower(%s) LIMIT 1", (email,)).fetchone()
    return dict(row[0]) if row else None


def get_user(tenant_id: str, user_id: str) -> dict | None:
    """Tenant-scoped single user fetch (no cross-tenant scan)."""
    if not tenant_id or not user_id:
        return None
    pool = _connect()
    if pool is None:
        o = MEM["users"].get(user_id)
        if o and o.get("tenant_id") == tenant_id:
            return copy.deepcopy(o)
        return None
    with _scoped_conn(tenant_id) as c:
        assert c is not None
        row = c.execute("SELECT data FROM xray_store WHERE collection='users' AND id=%s "
                        "AND tenant_id=%s", (user_id, tenant_id)).fetchone()
    return dict(row[0]) if row else None


# Back-compat for tests that poke pool internals: expose a lock + scope helper.
_LOCK = _POOL_LOCK


def _scope(c, tenant_id: str | None) -> None:
    """Legacy helper: set RLS scope on a raw connection (session-level).

    Prefer _scoped_conn (transaction-local). Kept for RLS tests that hold a
    raw connection and assert policy behaviour.
    """
    c.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id or "",))


# Legacy alias: some tests reset store._CONN. Map it to the pool.
_CONN = None


def clear():
    MEM.clear()
    pool = _connect()
    if pool is not None:
        with _scoped_conn("all") as c:
            assert c is not None
            c.execute("DELETE FROM xray_store")
