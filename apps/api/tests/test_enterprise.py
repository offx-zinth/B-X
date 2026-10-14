"""Tenant isolation, RBAC, versioning, audit, API v1, AI tools."""
import sys
sys.path.insert(0, "apps/api")
from fastapi.testclient import TestClient
from app.main import app
from app.core.store import clear


def _mk(email="u@t.co", org="T"):
    clear()
    c = TestClient(app)
    s = c.post("/auth/signup", json={"org": org, "email": email, "password": "secret123"}).json()
    return c, {"Authorization": f"Bearer {s['token']}"}, s


def test_signup_validates_and_roles():
    c, H, s = _mk()
    me = c.get("/auth/me", headers=H).json()
    assert me["role"] == "Owner"
    # invite a viewer; viewer cannot approve formulas
    v = c.post("/auth/users", json={"email": "v@t.co", "password": "secret123", "role": "Viewer"}, headers=H).json()
    assert v["role"] == "Viewer"
    tok = c.post("/auth/login", json={"email": "v@t.co", "password": "secret123"}).json()["token"]
    VH = {"Authorization": f"Bearer {tok}"}
    f = c.post("/formulas/", json={"target": "A.b", "expression": "1+1"}, headers=VH)
    assert f.status_code == 403  # Viewer cannot write formulas
    assert c.get("/graph/nodes", headers=VH).status_code == 200  # but can read


def test_versioning_and_audit():
    c, H, _ = _mk(email="v2@t.co")
    c.post("/ingest/seed", headers=H)
    vs = c.get("/graph/versions", headers=H).json()
    assert len(vs) >= 1 and vs[0]["version"] >= 1
    one = c.get(f"/graph/versions/{vs[0]['version']}", headers=H).json()
    assert "snapshot" in one
    # simulation records base version
    r = c.post("/simulations/run", json={"name": "t", "changes": [], "duration_days": 2}, headers=H).json()
    assert r["scenario"]["base_graph_version"] >= 1
    audit = c.get("/audit", headers=H).json()
    actions = {a["action"] for a in audit}
    assert "ingest.seed" in actions and "simulation.run" in actions


def test_api_v1_mirror_and_system():
    c, H, _ = _mk(email="v3@t.co")
    assert c.get("/health").json()["ok"] is True
    assert c.get("/ready").json()["ready"] is True
    assert c.get("/api/v1/health").json()["ok"] is True
    assert isinstance(c.get("/api/v1/graph/nodes", headers=H).json(), list)
    assert isinstance(c.get("/dashboard/", headers=H).json()["business_state"], dict)
    rep = c.get("/reports/", headers=H).json()
    assert "executive_summary" in rep
    csv = c.get("/reports/export.csv", headers=H)
    assert csv.status_code == 200 and "section,key,value" in csv.text


def test_ai_tools_and_graph_ops():
    c, H, _ = _mk(email="v4@t.co")
    c.post("/ingest/seed", headers=H)
    tools = c.get("/ai/tools", headers=H).json()
    names = {t["name"] for t in tools}
    assert {"query_graph", "run_simulation", "find_dependencies"} <= names
    assert all(t["parameters"]["type"] == "object" for t in tools), "every tool needs a schema"
    nodes = c.get("/graph/nodes", headers=H).json()
    sup = next(n for n in nodes if n["type"] == "Supplier")
    imp = c.get(f"/graph/impact/{sup['id']}", headers=H).json()
    assert "upstream" in imp and "downstream" in imp
    nb = c.get(f"/graph/neighbors/{sup['id']}", headers=H).json()
    assert "outgoing" in nb
    t = c.post("/ai/tools/run_simulation", json={"args": {"changes": [{"target": "Supplier.capacity", "value": 0}]}}, headers=H).json()
    assert "deltas" in t
    m = c.post("/ai/tools/get_metric", json={"args": {"ref": "Supplier.capacity"}}, headers=H).json()
    assert m["available"] is True
    v = c.post("/ai/tools/validate_formula", json={"args": {"target": "X.y", "expression": "MIN(1,2)"}}, headers=H).json()
    assert v["ok"] is True
    assert c.post("/ai/tools/nope", json={"args": {}}, headers=H).json()["error"].startswith("unknown tool")


def test_ingest_failure_status_and_docx_guard():
    c, H, _ = _mk(email="v5@t.co")
    bad = c.post("/ingest/upload", files={"f": ("evil.exe", b"zzz", "application/octet-stream")}, headers=H)
    assert bad.status_code == 400
    srcs = c.get("/ingest/sources", headers=H).json()
    assert any(s["status"] == "FAILED" for s in srcs)
    one = c.get(f"/ingest/sources/{srcs[0]['id']}", headers=H).json()
    assert one["status"] == "FAILED"
