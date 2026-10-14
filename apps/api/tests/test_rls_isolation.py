"""Database-enforced tenant isolation (Postgres Row Level Security).

These tests require a live Postgres. They are skipped when DATABASE_URL is
unset or the database is unreachable, so unit runs stay hermetic.

RLS is only meaningful for a non-superuser role: the POSTGRES_USER is a
superuser and bypasses RLS even with FORCE, so the API must connect as
`xray_app` (see infra/postgres/init.sql).
"""
import os
import sys
import uuid
sys.path.insert(0, "apps/api")
import pytest

PG_URL = os.environ.get("XRAY_TEST_PG")
if not PG_URL:
    pytest.skip("set XRAY_TEST_PG=postgresql://user:pass@host:port/db to run RLS tests",
                allow_module_level=True)

psycopg = pytest.importorskip("psycopg")
from app.core import store  # noqa: E402


@pytest.fixture()
def pg():
    os.environ["DATABASE_URL"] = PG_URL
    store._CONN = None
    store._LAST_TRY = 0.0
    conn = store._connect()
    if conn is None:
        pytest.skip(f"postgres unreachable: {store.store_error()}")
    yield conn
    store._CONN = None


def _ctx():
    return {"tenant_id": str(uuid.uuid4()), "user_id": "u", "email": "e@x.co"}


def test_app_role_is_not_rls_bypassing(pg):
    with pg.cursor() as cur:
        cur.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        is_super, bypass = cur.fetchone()
    assert not is_super, "API must not connect as a superuser or RLS is a no-op"
    assert not bypass, "API role must not have BYPASSRLS"


def test_rls_enabled_and_forced(pg):
    with pg.cursor() as cur:
        cur.execute("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname='xray_store'")
        rls, forced = cur.fetchone()
    assert rls and forced, "RLS must be ENABLED and FORCED"


def test_empty_scope_sees_nothing(pg):
    store.clear()
    a, b = _ctx(), _ctx()
    store.insert("nodes", a, {"type": "Supplier", "name": "A"})
    store.insert("nodes", b, {"type": "Supplier", "name": "B"})
    with store._LOCK:
        store._scope(pg, "")
        assert pg.execute("SELECT count(*) FROM xray_store").fetchone()[0] == 0
    store.clear()


def test_tenant_scope_sees_only_own_rows(pg):
    store.clear()
    a, b = _ctx(), _ctx()
    store.insert("nodes", a, {"type": "Supplier", "name": "A"})
    store.insert("nodes", b, {"type": "Supplier", "name": "B"})
    with store._LOCK:
        store._scope(pg, a["tenant_id"])
        assert pg.execute("SELECT count(*) FROM xray_store").fetchone()[0] == 1
        store._scope(pg, b["tenant_id"])
        assert pg.execute("SELECT count(*) FROM xray_store").fetchone()[0] == 1
        store._scope(pg, str(uuid.uuid4()))  # unknown tenant
        assert pg.execute("SELECT count(*) FROM xray_store").fetchone()[0] == 0
    store.clear()


def test_write_from_wrong_scope_is_blocked(pg):
    """A row for tenant B must be invisible (and un-updatable) under scope A."""
    store.clear()
    a, b = _ctx(), _ctx()
    nb = store.insert("nodes", b, {"type": "Supplier", "name": "B"})
    import psycopg.types.json as pjson
    with store._LOCK:
        store._scope(pg, a["tenant_id"])
        n = pg.execute("UPDATE xray_store SET data=%s WHERE id=%s",
                       (pjson.Jsonb({"hijacked": True}), nb["id"])).rowcount
    assert n == 0, "cross-tenant update must affect 0 rows"
    still_b = store.get("nodes", b, nb["id"])
    assert "hijacked" not in (still_b or {}), "tenant B row must be untouched"
    store.clear()


def test_scan_requires_explicit_all_scope(pg):
    store.clear()
    a, b = _ctx(), _ctx()
    store.insert("nodes", a, {"type": "Supplier", "name": "A"})
    store.insert("nodes", b, {"type": "Supplier", "name": "B"})
    assert len(store.scan("nodes")) == 2          # auth path, scope 'all'
    with store._LOCK:
        store._scope(pg, a["tenant_id"])
        assert pg.execute("SELECT count(*) FROM xray_store").fetchone()[0] == 1
    store.clear()