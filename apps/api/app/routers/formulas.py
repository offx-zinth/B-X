from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..core.tenant import get_ctx
from ..core.store import insert, list_all, update, get
from ..core import audit as auditlog
from ..core import roles as RBAC
from ..core import versions as ver
from ..services import formula_engine as bfl

router = APIRouter(prefix="/formulas", tags=["formulas"])

class FIn(BaseModel):
    target: str; expression: str

class FEdit(BaseModel):
    expression: str


def _user(ctx: dict) -> dict:
    from ..core.store import get_user
    from fastapi import HTTPException
    u = get_user(ctx.get("tenant_id", ""), ctx.get("user_id", ""))
    if not u:
        raise HTTPException(401, "unknown user")
    return u


@router.post("/")
def create(b: FIn, ctx: dict = Depends(get_ctx)):
    RBAC.require(_user(ctx), "formula.write")
    if "." not in b.target:
        raise HTTPException(400, "target must be Type.property (e.g. Production.capacity)")
    v = bfl.validate_expression(b.expression)
    if not v["ok"]:
        raise HTTPException(400, f"bad formula: {v['error']}")
    rec = insert("formulas", ctx, {"target": b.target, "expression": b.expression,
                                   "dependencies": v["dependencies"], "status": "pending",
                                   "level": "USER_DEFINED"})
    auditlog.record(ctx, "formula.create", f"formula:{rec['id']}", after={"target": b.target})
    return rec

@router.get("/")
def all(ctx: dict = Depends(get_ctx), limit: int = 200, offset: int = 0):
    rows = list_all("formulas", ctx)
    limit = max(1, min(int(limit or 200), 500)); offset = max(0, int(offset or 0))
    return rows[offset:offset + limit]

@router.post("/{fid}/approve")
def approve(fid: str, ctx: dict = Depends(get_ctx)):
    RBAC.require(_user(ctx), "formula.approve")
    f = get("formulas", ctx, fid)
    if not f: raise HTTPException(404, "not found")
    v = bfl.validate_expression(f["expression"])
    if not v["ok"]:
        raise HTTPException(400, f"cannot approve invalid formula: {v['error']}")
    out = update("formulas", ctx, fid, {"status": "approved", "dependencies": v["dependencies"]})
    auditlog.record(ctx, "formula.approve", f"formula:{fid}", before={"status": f["status"]},
                     after={"status": "approved"})
    ver.snapshot(ctx, source=f"formula.approve:{fid}")
    return out

@router.post("/{fid}/reject")
def reject(fid: str, ctx: dict = Depends(get_ctx)):
    RBAC.require(_user(ctx), "formula.write")
    f = get("formulas", ctx, fid)
    if not f: raise HTTPException(404, "not found")
    out = update("formulas", ctx, fid, {"status": "rejected"})
    auditlog.record(ctx, "formula.reject", f"formula:{fid}", before={"status": f["status"]},
                     after={"status": "rejected"})
    return out

@router.patch("/{fid}")
def edit(fid: str, b: FEdit, ctx: dict = Depends(get_ctx)):
    RBAC.require(_user(ctx), "formula.write")
    f = get("formulas", ctx, fid)
    if not f: raise HTTPException(404, "not found")
    v = bfl.validate_expression(b.expression)
    if not v["ok"]:
        raise HTTPException(400, f"bad formula: {v['error']}")
    # edited formulas return to pending — AI or user output never goes live silently
    out = update("formulas", ctx, fid, {"expression": b.expression,
                                        "dependencies": v["dependencies"], "status": "pending"})
    auditlog.record(ctx, "formula.edit", f"formula:{fid}", before={"expression": f["expression"]},
                     after={"expression": b.expression})
    return out

@router.post("/validate")
def validate(b: FIn, ctx: dict = Depends(get_ctx)):
    """Dry-run validation with trace — no persistence."""
    v = bfl.validate_expression(b.expression)
    if not v["ok"]:
        return {"ok": False, **v}
    from ..services import simulation as sim
    nodes = list_all("nodes", ctx)
    trial = bfl.evaluate_detailed(b.expression, sim.build_context(nodes))
    return {"ok": True, "dependencies": v["dependencies"], "sample_value": trial["value"],
            "trace": trial["trace"], "warnings": trial["warnings"]}
