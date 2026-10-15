"""Every catalog business seeds and simulates through the same engine."""
import sys
sys.path.insert(0, "apps/api")
from fastapi.testclient import TestClient
from app.main import app
from app.core.store import clear


def _client(email="biz@co.co"):
    clear()
    c = TestClient(app)
    tok = c.post("/auth/signup", json={"org": "Biz Co", "email": email, "password": "secret123"}).json()["token"]
    return c, {"Authorization": f"Bearer {tok}"}


def test_catalog_lists_six_businesses():
    c, H = _client("cat@co.co")
    r = c.get("/ingest/sample-catalog", headers=H).json()
    keys = {b["key"] for b in r["businesses"]}
    assert {"manufacturing", "tea_shop", "hospital", "logistics", "saas", "retail"} <= keys


def test_each_business_seed_simulates():
    cases = {
        "hospital": ("Doctor.capacity", 0, "Appointment.fulfillable"),
        "logistics": ("Vehicle.capacity", 0, "Shipment.fulfillable"),
        "saas": ("Agent.capacity", 0, "Ticket.fulfillable"),
        "retail": ("Store.capacity", 0, "Sale.fulfillable"),
        "tea_shop": ("MilkSupplier.capacity", 0, "TeaSale.fulfillable"),
        "manufacturing": ("Supplier.capacity", 0, "Order.fulfillable"),
    }
    for biz, (target, val, expect) in cases.items():
        c, H = _client(f"{biz}@co.co")
        s = c.post(f"/ingest/seed/{biz}", headers=H).json()
        assert s.get("nodes", 0) >= 6, (biz, s)
        r = c.post("/simulations/run", json={"name": f"{biz} outage",
                   "changes": [{"target": target, "value": val}], "duration_days": 7},
                   headers=H).json()
        assert r["result"]["scenario"][expect] == 0, (biz, r["result"]["scenario"])


def test_load_sample_uses_real_pipeline():
    c, H = _client("load@co.co")
    r = c.post("/ingest/load-sample/hospital", headers=H).json()
    assert len(r["files_loaded"]) >= 3
    assert r["formulas_added"] >= 4
    nodes = c.get("/graph/nodes", headers=H).json()
    assert len(nodes) >= 4
    # unknown business rejected
    bad = c.post("/ingest/seed/nope", headers=H)
    assert bad.status_code == 400


def test_tenant_isolation_between_businesses():
    clear()
    c = TestClient(app)
    t1 = c.post("/auth/signup", json={"org": "Hosp", "email": "iso-a@co.co", "password": "secret123"}).json()["token"]
    t2 = c.post("/auth/signup", json={"org": "SaaS", "email": "iso-b@co.co", "password": "secret123"}).json()["token"]
    H1, H2 = {"Authorization": f"Bearer {t1}"}, {"Authorization": f"Bearer {t2}"}
    c.post("/ingest/seed/hospital", headers=H1)
    c.post("/ingest/seed/saas", headers=H2)
    n1 = {n["type"] for n in c.get("/graph/nodes", headers=H1).json()}
    n2 = {n["type"] for n in c.get("/graph/nodes", headers=H2).json()}
    assert "Appointment" in n1 and "Appointment" not in n2
    assert "Ticket" in n2 and "Ticket" not in n1
