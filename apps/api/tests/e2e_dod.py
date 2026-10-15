"""Definition of Done (spec section 39) — end-to-end acceptance run.

Walks the full 21-step journey against the real backend and asserts each
step. Run: python3.11 apps/api/tests/e2e_dod.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient
from app.main import app
from app.core.store import clear

PASS, FAIL = [], []


def step(n, label, cond, detail=""):
    (PASS if cond else FAIL).append(n)
    print(f"{'PASS' if cond else 'FAIL'}  {n:>2}. {label}" + (f"  — {detail}" if detail and not cond else ""))


def main():
    clear()
    c = TestClient(app)

    # 1-2. Create an organization + user
    s = c.post("/auth/signup", json={"org": "Acme Manufacturing", "email": "dod@acme.co", "password": "secret123"}).json()
    H = {"Authorization": f"Bearer {s['token']}"}
    step(1, "Create organization", bool(s.get("tenant_id")), s)
    step(2, "Authenticate and receive scoped token", bool(s.get("token")))

    # 3. Upload business CSV data (real ingestion -> IR -> graph)
    sup_csv = b"supplier_id,name,lead_time_days,capacity_kg\nS1,ABC Metals,4,5000\nS2,Kovai Alloys,6,3200\n"
    up = c.post("/ingest/upload", files={"f": ("suppliers.csv", sup_csv, "text/csv")}, headers=H).json()
    step(3, "Upload CSV data", up["source"]["status"] == "COMPLETED", up.get("source"))

    # 4. See ingestion progress / statuses
    srcs = c.get("/ingest/sources", headers=H).json()
    step(4, "Inspect ingestion status", len(srcs) == 1 and srcs[0]["status"] == "COMPLETED", srcs)

    # 5. Inspect discovered entities — a table with foreign keys must yield
    #    typed entities AND relationships, not one opaque node.
    ord_csv = (b"order_id,customer_id,supplier_id,product_id,quantity,price\n"
               b"O1,C1,S1,P1,40,120\nO2,C2,S1,P2,60,85\n")
    c.post("/ingest/upload", files={"f": ("orders.csv", ord_csv, "text/csv")}, headers=H)
    nodes = c.get("/graph/nodes", headers=H).json()
    types = {n["type"] for n in nodes}
    edges = c.get("/graph/edges", headers=H).json()
    step(5, "Inspect discovered entities and relationships",
         len(nodes) >= 4 and len(edges) >= 2 and {"Supplier", "Order"} <= types,
         {"types": sorted(types), "nodes": len(nodes), "edges": len(edges)})

    # 6. Approve/correct mappings (provenance level is explicit)
    sup = next(n for n in nodes if n["type"] == "Supplier")
    step(6, "Provenance present on discovered node",
         bool(sup.get("provenance")) and sup.get("level") == "INFERRED",
         {"level": sup.get("level"), "prov_count": len(sup.get("provenance") or [])})

    # 7. Generate an executable operational graph (merges into uploaded data)
    seeded = c.post("/ingest/seed", headers=H).json()
    step(7, "Compile executable operational graph (merged, non-destructive)",
         seeded["seeded"] is True and seeded["nodes"] >= 12 and seeded["formulas"] >= 8, seeded)

    # 8-9. Explore graph; click a node; see upstream/downstream
    nodes = c.get("/graph/nodes", headers=H).json()
    edges = c.get("/graph/edges", headers=H).json()
    sup = next(n for n in nodes if n["type"] == "Supplier")
    imp = c.get(f"/graph/impact/{sup['id']}", headers=H).json()
    step(8, "Explore graph interactively (nodes + edges)", len(nodes) >= 12 and len(edges) >= 10,
         {"nodes": len(nodes), "edges": len(edges)})
    step(9, "Upstream/downstream dependencies", "upstream" in imp and "downstream" in imp and imp["affected_count"] >= 1, imp)

    # 10. Create or approve a formula
    f = c.post("/formulas/", json={"target": "Test.metric", "expression": "MIN(1, 2)"}, headers=H).json()
    approved = c.post(f"/formulas/{f['id']}/approve", headers=H).json()
    step(10, "Create and approve a formula", approved["status"] == "approved", approved)

    # 11. Modify a node value (node inspector write)
    patched = c.patch(f"/graph/nodes/{sup['id']}", json={"properties": {"capacity": 5000}}, headers=H).json()
    step(11, "Modify a node value", patched["properties"].get("capacity") == 5000, patched.get("properties"))

    # 12-14. Create scenario, run it, see propagation
    sim = c.post("/simulations/run", json={"name": "Supplier ABC capacity = 0",
                                          "changes": [{"target": "Supplier.capacity", "value": 0}],
                                          "duration_days": 14}, headers=H).json()
    step(12, "Create a simulation", sim["scenario"]["id"] and sim["scenario"]["base_graph_version"] >= 1, sim.get("scenario"))
    step(13, "Run the simulation", sim["run"]["status"] == "done", sim["run"])
    step(14, "Values propagate through the graph",
         sim["result"]["scenario"].get("Production.capacity") == 0
         and sim["result"]["scenario"].get("Revenue.total") == 0,
         {k: v for k, v in sim["result"]["scenario"].items() if "." in k})

    # 15. Compare simulation vs baseline
    comp = sim["result"]["comparison"]
    step(15, "Baseline comparison with deltas",
         comp["metrics"]["Revenue.total"]["before"] > 0 and comp["metrics"]["Revenue.total"]["after"] == 0,
         comp["metrics"].get("Revenue.total"))

    # 16. Ask the AI why the result happened
    why = c.post("/ai/ask", json={"question": "What happens if we lose our largest supplier?"}, headers=H).json()
    e = why.get("explanation", {})
    step(16, "Ask AI why the result happened",
         bool(why.get("answer")) and bool(e.get("why")) and bool(e.get("bottleneck", {}).get("reason")),
         why.get("answer"))

    # 17. Ask AI to generate a formula (proposal only, pending approval)
    prop = c.post("/ai/ask", json={"question": "Create a formula for revenue"}, headers=H).json()
    step(17, "AI generates a formula requiring approval",
         prop.get("proposal", {}).get("status") == "pending", prop.get("proposal"))

    # 18. Ask AI to find bottlenecks
    bn = c.post("/ai/ask", json={"question": "Find bottlenecks"}, headers=H).json()
    step(18, "AI finds bottlenecks", len(bn.get("bottlenecks", [])) > 0, bn.get("answer"))

    # 19. Ask AI to suggest an optimization
    opt = c.post("/ai/optimize", json={"question": "Reduce delivery delays while keeping cost increase below 5%"}, headers=H).json()
    step(19, "AI suggests an optimization", len(opt.get("options", [])) >= 3 and opt.get("recommended") is not None,
         opt.get("note"))

    # 20. Generate a report
    rep = c.get("/reports/", headers=H).json()
    csv_ok = c.get("/reports/export.csv", headers=H).status_code == 200
    step(20, "Generate a report", "executive_summary" in rep and csv_ok, rep.get("executive_summary"))

    # 21. Return later and see the same versioned model
    versions = c.get("/graph/versions", headers=H).json()
    v = c.get(f"/graph/versions/{versions[0]['version']}", headers=H).json()
    step(21, "Return later: same versioned model", "snapshot" in v and v["version"] == versions[0]["version"],
         versions)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} Definition-of-Done steps passed")
    if FAIL:
        print("FAILED STEPS:", FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())