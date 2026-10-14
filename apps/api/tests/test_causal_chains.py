"""Deterministic causal-chain tests (spec section 33).

If Supplier.capacity=5000, Production.capacity=MIN(Supplier.capacity,4000)
then Production.capacity=4000. If Supplier.capacity=0 then
Production.capacity=0. If Demand=500, Production.capacity=400 then
Backlog=100. No LLM involved — pure formula + simulation determinism.
"""
import sys
sys.path.insert(0, "apps/api")
from fastapi.testclient import TestClient
from app.main import app
from app.core.store import clear
from app.services import formula_engine as bfl
from app.services import simulation as sim


def _client():
    clear()
    c = TestClient(app)
    tok = c.post("/auth/signup", json={"org": "T", "email": "chain@t.co", "password": "secret123"}).json()["token"]
    return c, {"Authorization": f"Bearer {tok}"}


def test_supplier_min_chain():
    assert bfl.evaluate("MIN(Supplier.capacity, 4000)", {"Supplier.capacity": 5000}) == 4000
    assert bfl.evaluate("MIN(Supplier.capacity, 4000)", {"Supplier.capacity": 0}) == 0


def test_backlog_chain():
    assert bfl.evaluate("MAX(0, Demand.quantity - Production.capacity)",
                        {"Demand.quantity": 500, "Production.capacity": 400}) == 100
    assert bfl.evaluate("MAX(0, Demand.quantity - Production.capacity)",
                        {"Demand.quantity": 300, "Production.capacity": 400}) == 0


def test_revenue_chain():
    assert bfl.evaluate("Order.fulfilled * Order.avg_value",
                        {"Order.fulfilled": 350, "Order.avg_value": 120}) == 42000


def test_clamp():
    assert bfl.evaluate("CLAMP(15, 0, 10)", {}) == 10
    assert bfl.evaluate("CLAMP(-3, 0, 10)", {}) == 0
    assert bfl.evaluate("CLAMP(5, 0, 10)", {}) == 5


def test_evaluate_detailed_trace():
    d = bfl.evaluate_detailed("MIN(A.x, B.y)", {"A.x": 3})
    assert d["value"] == 0  # MIN(3, 0-missing)
    assert "B.y" in d["dependencies"]
    assert any("missing ref B.y" in w for w in d["warnings"])
    assert d["error"] is None


def test_simulation_propagates_chain():
    nodes = [
        {"id": "s", "type": "Supplier", "name": "S", "properties": {"capacity": 5000}},
        {"id": "m", "type": "Machine", "name": "M", "properties": {"capacity": 4000}},
        {"id": "p", "type": "Production", "name": "P", "properties": {"capacity": 0}},
    ]
    formulas = [{"target": "Production.capacity",
                 "expression": "MIN(Supplier.capacity, Machine.capacity)"}]
    r = sim.run(nodes, [], formulas, [], duration_days=2)
    assert r["scenario"]["Production.capacity"] == 4000
    r2 = sim.run(nodes, [], formulas, [{"target": "Supplier.capacity", "value": 0}], duration_days=2)
    assert r2["scenario"]["Production.capacity"] == 0
    assert "Production.capacity" in r2["deltas"]
    d = r2["deltas"]["Production.capacity"]
    assert d["before"] == 4000 and d["after"] == 0
    assert d["absolute_change"] == -4000 and d["percentage_change"] == -100.0


def test_simulation_never_mutates_live():
    c, H = _client()
    c.post("/ingest/seed", headers=H)
    before = {n["id"]: dict(n.get("properties", {})) for n in c.get("/graph/nodes", headers=H).json()}
    r = c.post("/simulations/run", json={"name": "kill supplier",
                                         "changes": [{"target": "Supplier.capacity", "value": 0}],
                                         "duration_days": 5}, headers=H).json()
    assert r["run"]["status"] == "done"
    after = {n["id"]: dict(n.get("properties", {})) for n in c.get("/graph/nodes", headers=H).json()}
    assert before == after
    assert len(r["result"]["timeline"]) == 5
    assert "comparison" in r["result"] and "time_to_impact_days" in r["result"]["comparison"]


def test_reference_demo_scenario_end_to_end():
    """Spec section 40: supplier failure must propagate and be explainable."""
    c, H = _client()
    c.post("/ingest/seed", headers=H)
    # approve seed formulas already approved; run the 14-day failure
    r = c.post("/simulations/run", json={"name": "Supplier ABC capacity = 0",
                                         "changes": [{"target": "Supplier.capacity", "value": 0}],
                                         "duration_days": 14}, headers=H).json()
    assert r["run"]["status"] == "done"
    assert len(r["result"]["timeline"]) == 14
    # AI explanation path resolves the failure without hallucination
    q = c.post("/ai/ask", json={"question": "What happens if we lose our largest supplier?"}, headers=H).json()
    assert "steps" in q and q["supplier"]["type"] == "Supplier"
    assert q["impact"]["affected_count"] >= 1
