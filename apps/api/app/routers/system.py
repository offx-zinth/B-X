"""System endpoints: health, readiness, metrics, audit trail."""
from fastapi import APIRouter, Depends
from ..core.tenant import get_ctx
from ..core import audit as auditlog
from ..core import observability as obs
from ..core.store import backend

router = APIRouter(tags=["system"])


@router.get("/audit")
def audit(ctx: dict = Depends(get_ctx), limit: int = 100, offset: int = 0):
    limit = max(1, min(int(limit or 100), 500)); offset = max(0, int(offset or 0))
    return auditlog.list_for_tenant(ctx, limit + offset)[offset:offset + limit]


@router.get("/metrics")
def metrics():
    try:
        from ..services import graph_mirror as _mirror
        neo = _mirror.status()
    except Exception:
        neo = {"enabled": False}
    return {"store_backend": backend(), "neo4j_mirror": neo, **obs.snapshot()}


@router.get("/ontology")
def ontology():
    from ..core.ontology import describe
    return describe()
