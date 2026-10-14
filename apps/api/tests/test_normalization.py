"""Business normalization: heterogeneous columns -> canonical properties.

This is what makes an uploaded tenant executable instead of opaque. Values are
aggregated deterministically and never invented.
"""
import sys
sys.path.insert(0, "apps/api")
from app.services.ir import normalize_measures, canonical_name
from fastapi.testclient import TestClient
from app.main import app
from app.core.store import clear


def test_unit_suffix_stripping():
    assert canonical_name("capacity_kg") == "capacity"
    assert canonical_name("lead_time_days") == "lead_time"
    assert canonical_name("available_kg") == "available"
    assert canonical_name("required_per_unit") == "required"
    assert canonical_name("demand_units") == "demand"
    assert canonical_name("cost_per_unit") == "cost"


def test_aggregation_semantics():
    # rate-like -> mean, stock-like -> sum
    assert normalize_measures(["capacity_kg"], [{"capacity_kg": 5000}, {"capacity_kg": 3000}]) == {"capacity": 4000.0}
    assert normalize_measures(["available_kg"], [{"available_kg": 500}, {"available_kg": 300}]) == {"available": 800.0}


def test_non_numeric_is_ignored_not_invented():
    out = normalize_measures(["capacity_kg"], [{"capacity_kg": "n/a"}, {"capacity_kg": None}])
    assert out == {}


def test_uploaded_supplier_becomes_executable():
    clear()
    c = TestClient(app)
    s = c.post("/auth/signup", json={"org": "Norm", "email": "n@n.co", "password": "secret123"}).json()
    H = {"Authorization": f"Bearer {s['token']}"}
    csv = (b"supplier_id,name,lead_time_days,capacity_kg\n"
           b"S1,ABC Metals,4,5000\nS2,Kovai Alloys,6,3200\n")
    c.post("/ingest/upload", files={"f": ("suppliers.csv", csv, "text/csv")}, headers=H)
    nodes = c.get("/graph/nodes", headers=H).json()
    sup = next(n for n in nodes if n["type"] == "Supplier")
    # the discovered node now carries executable canonical properties
    assert sup["properties"]["capacity"] == 4100.0
    assert sup["properties"]["lead_time"] == 5.0
    assert sup["level"] == "INFERRED"


def test_never_clobbers_existing_value():
    clear()
    c = TestClient(app)
    s = c.post("/auth/signup", json={"org": "N2", "email": "n2@n.co", "password": "secret123"}).json()
    H = {"Authorization": f"Bearer {s['token']}"}
    n = c.post("/graph/nodes", json={"type": "Supplier", "name": "Mine",
                                     "properties": {"capacity": 9999}}, headers=H).json()
    csv = b"supplier_id,name,capacity_kg\nS1,X,100\n"
    c.post("/ingest/upload", files={"f": ("suppliers.csv", csv, "text/csv")}, headers=H)
    after = c.get(f"/graph/nodes/{n['id']}", headers=H).json()["node"]
    assert after["properties"]["capacity"] == 9999  # user value preserved