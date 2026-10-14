"""Reference implementation test — spec section 40.

Acme Manufacturing: Supplier ABC -> Material -> Production -> Product ->
Orders -> Revenue. Set Supplier.capacity = 0 for 14 days and assert the
causal propagation through the real seeded graph + real simulation engine.
"""
import sys
sys.path.insert(0, "apps/api")
from fastapi.testclient import TestClient
from app.main import app
from app.core.store import clear


def _seeded():
    clear()
    c = TestClient(app)
    tok = c.post("/auth/signup", json={"org": "Acme Manufacturing", "email": "ref@acme.co", "password": "secret123"}).json()["token"]
    H = {"Authorization": f"Bearer {tok}"}
    c.post("/ingest/seed", headers=H)
    return c, H


def test_supplier_failure_cascades_full_chain():
    c, H = _seeded()
    r = c.post("/simulations/run", json={"name": "Supplier ABC capacity = 0",
                                         "changes": [{"target": "Supplier.capacity", "value": 0}],
                                         "duration_days": 14}, headers=H).json()
    assert r["run"]["status"] == "done", r["run"]
    d = r["result"]["deltas"]
    s = r["result"]["scenario"]
    # supplier cap zeroed
    assert d["Supplier.capacity"]["after"] == 0
    # production capacity collapses (min with supplier binding)
    assert d["Production.capacity"]["after"] == 0
    # nothing fulfillable
    assert s["Order.fulfillable"] == 0
    # backlog rises to full demand
    assert s["Order.backlog"] == 3500
    # revenue gone
    assert s["Revenue.total"] == 0
    # 14-day timeline present
    assert len(r["result"]["timeline"]) == 14


def test_baseline_healthy_business():
    c, H = _seeded()
    r = c.post("/simulations/run", json={"name": "no change", "changes": [], "duration_days": 14}, headers=H).json()
    b = r["result"]["baseline"]
    # baseline capacity is min(supplier 5000, machine 4000, material 5000/10=500) = 500
    assert b["Production.capacity"] == 500
    assert b["Order.fulfillable"] == 500
    assert b["Revenue.total"] == 500 * 120


def test_impact_graph_reaches_revenue():
    c, H = _seeded()
    nodes = c.get("/graph/nodes", headers=H).json()
    sup = next(n for n in nodes if n["type"] == "Supplier")
    imp = c.get(f"/graph/impact/{sup['id']}", headers=H).json()
    # Supplier -> Material -> Production -> Order -> ... downstream closure
    assert imp["affected_count"] >= 4


def test_ai_explains_all_seven_elements():
    """Spec section 40: the AI must explain what/which/when/why/metrics/
    bottleneck/interventions — derived from the graph, never invented."""
    c, H = _seeded()
    r = c.post("/ai/ask", json={"question": "What happens if we lose our largest supplier?"}, headers=H).json()
    e = r["explanation"]
    assert e["what_changed"] and "Supplier.capacity" in e["what_changed"][0]
    assert len(e["affected_nodes"]) >= 1
    assert any(m["ref"] == "Revenue.total" for m in e["metrics_changed"])
    assert e["why"], "must explain causal reasoning"
    assert "binding constraint" in e["bottleneck"]["reason"]
    assert e["interventions"], "must propose interventions"
    # every claimed 'why' must cite a real formula expression from the graph
    formulas = {f["target"]: f["expression"] for f in c.get("/formulas/", headers=H).json()}
    for w in e["why"]:
        assert formulas.get(w["ref"]) == w["because"].split(" = ")[1]