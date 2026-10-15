"""Universal ontology proof: tea shop and factory share the same 14-primitive engine."""
import sys
sys.path.insert(0, "apps/api")
from fastapi.testclient import TestClient
from app.main import app
from app.core.store import clear
from app.core import ontology as onto
from app.services import formula_engine as bfl


def test_core_14_shape():
    assert len(onto.CORE_14) == 14
    assert len(onto.NODE_PRIMITIVES) == 7
    assert len(onto.EDGE_PRIMITIVES) == 2
    assert len(onto.PROPERTY_PRIMITIVES) == 5
    assert set(onto.CORE_14) == set(onto.NODE_PRIMITIVES) | set(onto.EDGE_PRIMITIVES) | set(onto.PROPERTY_PRIMITIVES)


def test_normalize_and_classify_general():
    assert onto.normalize_kind("Entity") == "ENTITY"
    assert onto.normalize_kind("Metric") == "ENTITY"  # legacy
    assert onto.normalize_kind("WeirdTeaThing") == "ENTITY"  # unknown stays executable
    assert onto.classify_edge("supplies") == "FLOW"
    assert onto.classify_edge("DEPENDENCY") == "DEPENDENCY"
    assert onto.classify_edge("USES") == "FLOW"


def test_strict_units_blocks_time_plus_currency():
    bad = bfl.validate_expression("Supplier.lead_time + Revenue.total")
    assert not bad["ok"] and "unit mismatch" in bad["error"]
    # seed formulas stay valid
    for expr in [
        "MIN(Supplier.capacity, Machine.capacity, Material.available / Material.required)",
        "Order.fulfillable * Order.avg_value",
        "MAX(0, Demand.quantity - Order.fulfillable)",
        "MIN(MilkSupplier.capacity, Brewer.capacity, MilkStock.available / MilkStock.required)",
    ]:
        assert bfl.validate_expression(expr)["ok"], expr


def _client():
    clear()
    c = TestClient(app)
    tok = c.post("/auth/signup", json={"org": "Universal Co", "email": "u@uni.co", "password": "secret123"}).json()["token"]
    return c, {"Authorization": f"Bearer {tok}"}


def test_tea_shop_same_engine_as_factory():
    c, H = _client()
    # factory baseline still works
    c.post("/ingest/seed", headers=H)
    r = c.post("/simulations/run", json={"name": "factory outage",
               "changes": [{"target": "Supplier.capacity", "value": 0}],
               "duration_days": 7}, headers=H).json()
    assert r["result"]["scenario"]["Revenue.total"] == 0
    # tea shop seed merges in and runs through the SAME solver
    t = c.post("/ingest/seed-tea-shop", headers=H).json()
    assert t.get("seeded") or "nodes" in t
    r2 = c.post("/simulations/run", json={"name": "milk outage",
                "changes": [{"target": "MilkSupplier.capacity", "value": 0}],
                "duration_days": 7}, headers=H).json()
    assert r2["result"]["scenario"]["TeaSale.fulfillable"] == 0
    assert r2["result"]["scenario"]["TeaRevenue.total"] == 0
    assert len(r2["result"]["timeline"]) == 7


def test_forecast_tool_and_models():
    c, H = _client()
    c.post("/ingest/seed", headers=H)
    mods = c.get("/ai/forecast-models", headers=H).json()
    assert any(m["name"] == "moving_average" for m in mods["models"])
    res = c.post("/ai/tools/forecast", json={"args": {"target": "Demand.quantity", "horizon": 7}}, headers=H).json()
    assert len(res["predictions"]) == 7
    assert "simulation" in res["note"].lower() or "simulation" in res.get("note", "")


def test_ontology_endpoints():
    c, H = _client()
    o1 = c.get("/graph/ontology", headers=H).json()
    assert len(o1["core_14"]) == 14
    o2 = c.get("/ontology", headers=H).json()
    assert o2["operational_nodes"] == o1["operational_nodes"]
