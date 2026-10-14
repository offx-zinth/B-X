"""Seed Acme Manufacturing demo (spec section 34 + 40).

Runs against the real backend: real ingestion, real IR, real graph compiler,
real formula engine, real simulation engine. No frontend-only data.

Usage:
  python3.11 seed_demo.py                # in-process via TestClient
  python3.11 seed_demo.py --print-result  # also print the supplier-failure deltas
"""
import sys
sys.path.insert(0, "apps/api")
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)
s = c.post("/auth/signup", json={"org": "Acme Manufacturing", "email": "demo@acme.co", "password": "secret123"}).json()
H = {"Authorization": f"Bearer {s['token']}"}
print("tenant:", s["tenant_id"])

seed = c.post("/ingest/seed", headers=H).json()
print("seed:", seed)

nodes = c.get("/graph/nodes", headers=H).json()
edges = c.get("/graph/edges", headers=H).json()
print("nodes:", len(nodes), "edges:", len(edges))

sup = next(n for n in nodes if n["type"] == "Supplier")
imp = c.get(f"/graph/impact/{sup['id']}", headers=H).json()
print(f"impact of {sup['name']}: {imp['affected_count']} downstream, {imp['upstream_count']} upstream")

run = c.post("/simulations/run", json={"name": "Supplier ABC capacity = 0",
                                       "changes": [{"target": "Supplier.capacity", "value": 0}],
                                       "duration_days": 14}, headers=H).json()
print("simulation status:", run["run"]["status"])
print("deltas:", run["result"]["deltas"])
print("versions:", c.get("/graph/versions", headers=H).json())
print("seed done. token:", s["token"][:20] + "...")