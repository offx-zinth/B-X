from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..core.tenant import get_ctx
from ..core.store import insert, list_all, get as sget
from ..core import audit as auditlog
from ..core import roles as RBAC
from ..core import versions as ver
from ..services import simulation as sim
import time

router = APIRouter(prefix="/simulations", tags=["simulations"])

class SimIn(BaseModel):
    name: str = "Scenario"; changes: list[dict] = []; duration_days: int = 14
    base_graph_version: int | None = None
    formula_overrides: list[dict] = []

TEMPLATES = [
    {"name": "Supplier disappears", "changes": [{"target": "Supplier.capacity", "value": 0}]},
    {"name": "Demand +50%", "changes": [{"target": "Order.demand", "value": 750}]},
    {"name": "Employee unavailable", "changes": [{"target": "Employee.daily_capacity", "value": 0}]},
    {"name": "Machine failure", "changes": [{"target": "Machine.capacity", "value": 0}]},
    {"name": "New branch", "changes": [{"target": "Order.demand", "value": 650}]},
    {"name": "Price increase", "changes": [{"target": "Order.avg_value", "value": 150}]},
    {"name": "Hiring increase", "changes": [{"target": "Employee.daily_capacity", "value": 200}]},
    {"name": "Inventory reduction", "changes": [{"target": "Inventory.available", "value": 1000}]},
    {"name": "Delivery delay", "changes": [{"target": "Supplier.lead_time", "value": 10}]},
    {"name": "Customer growth", "changes": [{"target": "Customer.demand", "value": 500}]},
]


def _user(ctx: dict) -> dict:
    from ..core.store import scan
    for u in scan("users"):
        if u.get("id") == ctx.get("user_id"):
            return u
    return {"role": "Viewer"}


@router.get("/templates")
def templates(): return [t["name"] for t in TEMPLATES]

@router.get("/templates/full")
def templates_full(): return TEMPLATES

@router.post("/run")
def run(b: SimIn, ctx: dict = Depends(get_ctx)):
    RBAC.require(_user(ctx), "simulation.write")
    t0 = time.perf_counter()
    if b.duration_days < 1 or b.duration_days > 365:
        raise HTTPException(400, "duration_days must be 1..365")
    for ch in b.changes:
        if "." not in (ch.get("target") or ""):
            raise HTTPException(400, f"change target must be Type.property, got {ch}")
    nodes = list_all("nodes", ctx); edges = list_all("edges", ctx)
    formulas = [f for f in list_all("formulas", ctx) if f.get("status") in ("approved", "active")] or list_all("formulas", ctx)
    base_ver = b.base_graph_version or ver.current_version(ctx)
    sc = insert("scenarios", ctx, {"name": b.name, "changes": b.changes,
                                   "base_graph_version": base_ver,
                                   "formula_overrides": b.formula_overrides,
                                   "duration_days": b.duration_days})
    try:
        res = sim.run(nodes, edges, formulas, b.changes, steps=b.duration_days,
                      duration_days=b.duration_days, base_graph_version=base_ver,
                      formula_overrides=b.formula_overrides)
        status = "done"
        err = None
    except Exception as e:
        # retain scenario definition + error trace (never silently swallow)
        res = {"baseline": {}, "scenario": {}, "deltas": {}, "timeline": [],
               "comparison": {}, "changes": b.changes, "error": str(e)[:500]}
        status = "failed"
        err = str(e)[:500]
    run = insert("simulation_runs", ctx, {"scenario_id": sc["id"], "status": status,
                                          "duration_ms": int((time.perf_counter() - t0) * 1000),
                                          "results": {"deltas": res.get("deltas"),
                                                      "comparison": res.get("comparison"),
                                                      "changes": b.changes, "error": err}})
    auditlog.record(ctx, "simulation.run", f"scenario:{sc['id']}",
                     after={"name": b.name, "status": status, "base_version": base_ver})
    return {"scenario": sc, "result": res, "run": run}

@router.get("/")
def history(ctx: dict = Depends(get_ctx), limit: int = 50, offset: int = 0):
    runs = list_all("simulation_runs", ctx)
    runs.sort(key=lambda r: r.get("id", ""), reverse=True)
    limit = max(1, min(int(limit or 50), 200)); offset = max(0, int(offset or 0))
    return runs[offset:offset + limit]

@router.get("/{run_id}")
def one(run_id: str, ctx: dict = Depends(get_ctx)):
    r = sget("simulation_runs", ctx, run_id)
    if not r: raise HTTPException(404, "run not found")
    return r
