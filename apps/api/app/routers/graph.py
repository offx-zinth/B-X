from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..core.tenant import get_ctx
from ..core.store import insert, list_all, get, update
from ..core import audit as auditlog
from ..core import roles as RBAC
from ..core import versions as ver
from ..services import compiler as comp
from ..services import provenance as prov

router = APIRouter(prefix="/graph", tags=["graph"])

class NodeIn(BaseModel):
    type: str; name: str; properties: dict = {}; state: str = "active"; confidence: float = 1.0
class EdgeIn(BaseModel):
    source_node: str; target_node: str; type: str; properties: dict = {}; formula: str | None = None
class NodePatch(BaseModel):
    name: str | None = None; properties: dict | None = None; state: str | None = None


def _user(ctx: dict) -> dict:
    from ..core.store import scan
    for u in scan("users"):
        if u.get("id") == ctx.get("user_id"):
            return u
    return {"role": "Viewer"}


@router.post("/nodes")
def create_node(b: NodeIn, ctx: dict = Depends(get_ctx)):
    RBAC.require(_user(ctx), "graph.write")
    if not b.type.strip() or not b.name.strip():
        raise HTTPException(400, "type and name required")
    rec = insert("nodes", ctx, {**b.model_dump(), "level": "USER_DEFINED",
                                "provenance": [prov.attach("console", method="manual", level="USER_DEFINED")]})
    auditlog.record(ctx, "graph.node.create", f"node:{rec['id']}", after={"type": b.type, "name": b.name})
    return rec

@router.get("/nodes")
def nodes(ctx: dict = Depends(get_ctx)): return list_all("nodes", ctx)

@router.get("/nodes/{node_id}")
def get_node(node_id: str, ctx: dict = Depends(get_ctx)):
    n = get("nodes", ctx, node_id)
    if not n: raise HTTPException(404, "node not found")
    edges = [e for e in list_all("edges", ctx) if e["source_node"] == node_id or e["target_node"] == node_id]
    formulas = [f for f in list_all("formulas", ctx) if n["type"] in f.get("target", "")]
    return {"node": n, "provenance": prov.explain(n), "edges": edges,
            "formulas": formulas}

@router.patch("/nodes/{node_id}")
def update_node(node_id: str, b: NodePatch, ctx: dict = Depends(get_ctx)):
    RBAC.require(_user(ctx), "graph.write")
    before = get("nodes", ctx, node_id)
    if not before: raise HTTPException(404, "node not found")
    patch = {k: v for k, v in b.model_dump().items() if v is not None}
    after = update("nodes", ctx, node_id, patch)
    auditlog.record(ctx, "graph.node.update", f"node:{node_id}", before=before, after=patch)
    ver.snapshot(ctx, source="graph.node.update")
    return after

@router.post("/edges")
def create_edge(b: EdgeIn, ctx: dict = Depends(get_ctx)):
    RBAC.require(_user(ctx), "graph.write")
    if not get("nodes", ctx, b.source_node) or not get("nodes", ctx, b.target_node): raise HTTPException(400, "unknown node")
    rec = insert("edges", ctx, {**b.model_dump(), "level": "USER_DEFINED"})
    auditlog.record(ctx, "graph.edge.create", f"edge:{rec['id']}",
                     after={"source": b.source_node, "target": b.target_node, "type": b.type})
    ver.snapshot(ctx, source="graph.edge.create")
    return rec

@router.get("/edges")
def edges(ctx: dict = Depends(get_ctx)): return list_all("edges", ctx)

@router.get("/impact/{node_id}")
def impact(node_id: str, ctx: dict = Depends(get_ctx)):
    if not get("nodes", ctx, node_id): raise HTTPException(404, "node not found")
    return comp.full_impact(node_id, list_all("edges", ctx))

@router.get("/neighbors/{node_id}")
def neighbors(node_id: str, ctx: dict = Depends(get_ctx)):
    if not get("nodes", ctx, node_id): raise HTTPException(404, "node not found")
    return comp.get_neighbors(node_id, list_all("edges", ctx))

@router.get("/trace")
def trace(source: str, target: str, ctx: dict = Depends(get_ctx)):
    if not get("nodes", ctx, source) or not get("nodes", ctx, target):
        raise HTTPException(404, "unknown node")
    return comp.trace_path(source, target, list_all("edges", ctx))

@router.get("/versions")
def versions(ctx: dict = Depends(get_ctx)): return ver.list_versions(ctx)

@router.get("/versions/{v}")
def version_one(v: int, ctx: dict = Depends(get_ctx)):
    r = ver.get_version(ctx, v)
    if not r: raise HTTPException(404, "version not found")
    return r
