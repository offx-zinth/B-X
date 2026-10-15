"""Reports: executive summary + health + bottlenecks + risks + simulations +
optimizations + AI recommendations. Export to JSON (default) and CSV.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from ..core.tenant import get_ctx
from ..core.store import list_all, insert
from ..core import audit as auditlog
from ..core import roles as RBAC
from ..services import ai_orchestrator as ai
import csv, io

router = APIRouter(prefix="/reports", tags=["reports"])


def _user(ctx: dict) -> dict:
    from ..core.store import get_user
    u = get_user(ctx.get("tenant_id", ""), ctx.get("user_id", ""))
    if not u:
        raise HTTPException(401, "unknown user")
    return u


@router.get("/")
def build(ctx: dict = Depends(get_ctx)):
    rep = ai.generate_report(ctx)
    rec = insert("reports", ctx, {"report": rep})
    auditlog.record(ctx, "report.generate", f"report:{rec['id']}")
    return {"id": rec["id"], **rep}


@router.get("/export.csv")
def export_csv(ctx: dict = Depends(get_ctx)):
    RBAC.require(_user(ctx), "report.read")
    rep = ai.generate_report(ctx)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["section", "key", "value"])
    w.writerow(["executive_summary", "summary", rep.get("executive_summary", "")])
    w.writerow(["health", "operational_risk", rep.get("operational_risk", "")])
    w.writerow(["health", "bottleneck_risk", rep.get("bottleneck_risk", "")])
    for b in rep.get("top_bottlenecks", []):
        n = (b.get("node") or {})
        w.writerow(["bottleneck", f"{n.get('type')}:{n.get('name')}", b.get("fanout", "")])
    for r in rep.get("operational_risks", []):
        w.writerow(["risk", r.get("kind", ""), f"{r.get('severity')}: {r.get('detail', '')}"])
    for i, rec in enumerate(rep.get("recommendations", [])):
        w.writerow(["recommendation", f"rec_{i}", rec])
    auditlog.record(ctx, "report.export", "report:csv")
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=business-xray-report.csv"})


@router.get("/history")
def history(ctx: dict = Depends(get_ctx)):
    rows = list_all("reports", ctx)
    return rows[-20:]
