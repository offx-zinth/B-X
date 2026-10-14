"""System endpoints: health, readiness, metrics, audit trail."""
from fastapi import APIRouter, Depends
from ..core.tenant import get_ctx
from ..core import audit as auditlog
from ..core import observability as obs
from ..core.store import backend

router = APIRouter(tags=["system"])


@router.get("/audit")
def audit(ctx: dict = Depends(get_ctx), limit: int = 100):
    return auditlog.list_for_tenant(ctx, limit)


@router.get("/metrics")
def metrics():
    return {"store_backend": backend(), **obs.snapshot()}
