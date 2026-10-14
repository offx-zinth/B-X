"""Durable store with in-memory fallback. Same interface either way.
Postgres backend: single JSONB table (collection, id, tenant_id, data).
Falls back to memory if Postgres is unreachable (e.g. unit tests).
All records carry tenant_id. Every accessor requires ctx."""
from __future__ import annotations
import uuid, copy, os, threading
from collections import defaultdict

MEM: dict[str, dict[str, dict]] = defaultdict(dict)
_PG_OK = False
_CONN = None
_LOCK = threading.Lock()
_LAST_TRY = 0.0
_RETRY_COOLDOWN = 10.0
_PG_ERROR = ""

def _pg_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://xray:xray@localhost:5432/xray")

def _connect():
    """Lazy Postgres connect with cooldown retry. Returns None when unreachable
    (callers fall back to memory). Retries matter: PG may boot after the API."""
    import time
    global _CONN, _PG_OK, _LAST_TRY
    with _LOCK:
        if _CONN is not None:
            try:
                _CONN.execute("SELECT 1")
                return _CONN
            except Exception:
                try: _CONN.close()
                except Exception: pass
                _CONN, _PG_OK = None, False
        if time.time() - _LAST_TRY < _RETRY_COOLDOWN:
            return None
        _LAST_TRY = time.time()
        try:
            import psycopg
            c = psycopg.connect(_pg_url(), autocommit=True, connect_timeout=3)
            c.execute("""CREATE TABLE IF NOT EXISTS xray_store (
                collection TEXT NOT NULL, id TEXT NOT NULL,
                tenant_id TEXT NOT NULL, data JSONB NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT now(),
                PRIMARY KEY (collection, id))""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_xray_tenant ON xray_store (collection, tenant_id)")
            # Row Level Security is defence in depth: every request sets
            # app.tenant_id, so a missing WHERE clause still cannot leak rows.
            # 'all' is reserved for cross-tenant auth lookups (login by email).
            c.execute("ALTER TABLE xray_store ENABLE ROW LEVEL SECURITY")
            c.execute("ALTER TABLE xray_store FORCE ROW LEVEL SECURITY")
            c.execute("DROP POLICY IF EXISTS tenant_isolation ON xray_store")
            c.execute("""CREATE POLICY tenant_isolation ON xray_store USING (
                current_setting('app.tenant_id', true) = 'all'
                OR (NULLIF(current_setting('app.tenant_id', true), '') IS NOT NULL
                    AND tenant_id = current_setting('app.tenant_id', true))
            )""")
            c.execute("SELECT set_config('app.tenant_id', 'all', false)")
            _CONN, _PG_OK = c, True
            return c
        except Exception as e:
            # Never fail silently: the in-memory fallback is a degraded mode
            # and must be visible (health reports the active backend).
            global _PG_ERROR
            _PG_ERROR = f"{type(e).__name__}: {e}"
            print(f"[store] postgres unavailable, using in-memory fallback: {_PG_ERROR}", flush=True)
            _PG_OK = False
            return None


def store_error() -> str:
    return _PG_ERROR


def _scope(c, tenant_id: str | None) -> None:
    """Bind the RLS context for subsequent statements on this connection."""
    c.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id or "",))

def backend() -> str:
    return "postgres" if _connect() is not None else "memory"

def _new_id() -> str: return str(uuid.uuid4())

def insert(coll: str, ctx: dict, obj: dict) -> dict:
    obj = copy.deepcopy(obj)
    obj["id"] = obj.get("id") or _new_id()
    obj["tenant_id"] = ctx["tenant_id"]
    c = _connect()
    if c is None:
        MEM[coll][obj["id"]] = obj
    else:
        import psycopg.types.json as pjson
        with _LOCK:
            _scope(c, obj["tenant_id"])
            c.execute("INSERT INTO xray_store (collection, id, tenant_id, data) VALUES (%s,%s,%s,%s) "
                      "ON CONFLICT (collection, id) DO UPDATE SET data=EXCLUDED.data, updated_at=now()",
                      (coll, obj["id"], obj["tenant_id"], pjson.Jsonb(obj)))
    return copy.deepcopy(obj)

def get(coll: str, ctx: dict, _id: str) -> dict | None:
    c = _connect()
    if c is None:
        o = MEM[coll].get(_id)
    else:
        with _LOCK:
            _scope(c, ctx["tenant_id"])
            row = c.execute("SELECT data FROM xray_store WHERE collection=%s AND id=%s", (coll, _id)).fetchone()
        o = dict(row[0]) if row else None
    if not o or o.get("tenant_id") != ctx["tenant_id"]:
        return None
    return copy.deepcopy(o)

def list_all(coll: str, ctx: dict) -> list[dict]:
    c = _connect()
    if c is None:
        return [copy.deepcopy(o) for o in MEM[coll].values() if o.get("tenant_id") == ctx["tenant_id"]]
    with _LOCK:
        _scope(c, ctx["tenant_id"])
        rows = c.execute("SELECT data FROM xray_store WHERE collection=%s AND tenant_id=%s", (coll, ctx["tenant_id"])).fetchall()
    return [dict(r[0]) for r in rows]

def update(coll: str, ctx: dict, _id: str, patch: dict) -> dict | None:
    o = get(coll, ctx, _id)
    if not o: return None
    o.update(patch); o["tenant_id"] = ctx["tenant_id"]
    c = _connect()
    if c is None:
        MEM[coll][_id] = o
    else:
        import psycopg.types.json as pjson
        with _LOCK:
            _scope(c, o["tenant_id"])
            c.execute("UPDATE xray_store SET data=%s, updated_at=now() WHERE collection=%s AND id=%s "
                      "AND tenant_id=%s", (pjson.Jsonb(o), coll, _id, o["tenant_id"]))
    return copy.deepcopy(o)

def delete(coll: str, ctx: dict, _id: str) -> bool:
    o = get(coll, ctx, _id)
    if not o: return False
    c = _connect()
    if c is None:
        MEM[coll].pop(_id, None)
    else:
        with _LOCK:
            _scope(c, o["tenant_id"])
            c.execute("DELETE FROM xray_store WHERE collection=%s AND id=%s AND tenant_id=%s",
                      (coll, _id, o["tenant_id"]))
    return True

def scan(coll: str) -> list[dict]:
    """Cross-tenant read. Auth use only (login resolves tenant from email).
    Never use in tenant-scoped routes. Runs under RLS scope 'all'."""
    c = _connect()
    if c is None:
        return [copy.deepcopy(o) for o in MEM[coll].values()]
    with _LOCK:
        _scope(c, "all")
        rows = c.execute("SELECT data FROM xray_store WHERE collection=%s", (coll,)).fetchall()
    return [dict(r[0]) for r in rows]

def clear():
    MEM.clear()
    c = _connect()
    if c is not None:
        with _LOCK:
            _scope(c, "all")
            c.execute("DELETE FROM xray_store")
