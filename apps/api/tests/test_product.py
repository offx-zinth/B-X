import sys; sys.path.insert(0, "apps/api")
from fastapi.testclient import TestClient
from app.main import app
from app.core.store import clear

def _client():
    clear()
    c = TestClient(app)
    tok = c.post("/auth/signup", json={"org": "T", "email": "t@t.co", "password": "secret123"}).json()["token"]
    return c, {"Authorization": f"Bearer {tok}"}

def test_cross_file_merge():
    c, H = _client()
    c.post("/ingest/upload", files={"f": ("suppliers.csv", b"supplier_id,name,capacity\nS1,ABC,5000", "text/csv")}, headers=H)
    c.post("/ingest/upload", files={"f": ("orders.csv", b"customer_id,supplier_id,qty\nC1,S1,5", "text/csv")}, headers=H)
    nodes = c.get("/graph/nodes", headers=H).json()
    types = [n["type"] for n in nodes]
    assert types.count("Supplier") == 1, types
    sup = [n for n in nodes if n["type"] == "Supplier"][0]
    assert "suppliers.csv" in sup["source_docs"] and "orders.csv" in sup["source_docs"]
    assert sup["properties"]["record_count"] == 2

def test_formula_lifecycle():
    c, H = _client()
    f = c.post("/formulas/", json={"target": "A.b", "expression": "MAX(1, 2)"}, headers=H).json()
    assert f["status"] == "pending"
    bad = c.patch(f"/formulas/{f['id']}", json={"expression": "EVAL(1)"}, headers=H)
    assert bad.status_code == 400
    e = c.patch(f"/formulas/{f['id']}", json={"expression": "MIN(1, 2)"}, headers=H).json()
    assert e["status"] == "pending" and e["expression"] == "MIN(1, 2)"
    assert c.post(f"/formulas/{f['id']}/approve", headers=H).json()["status"] == "approved"
    assert c.post(f"/formulas/{f['id']}/reject", headers=H).json()["status"] == "rejected"

def test_seed_idempotent():
    c, H = _client()
    r1 = c.post("/ingest/seed", headers=H).json()
    assert r1["seeded"] is True and r1["nodes"] >= 6 and r1["formulas"] >= 5
    r2 = c.post("/ingest/seed", headers=H).json()
    assert r2["seeded"] is False
    assert len(c.get("/graph/nodes", headers=H).json()) == r1["nodes"]
