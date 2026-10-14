"""Ingestion pipeline: UPLOAD -> VALIDATE -> STORE -> PARSE -> EXTRACT ->
NORMALIZE -> VALIDATE -> COMPILE -> GRAPH UPDATE.

Statuses: QUEUED -> PROCESSING -> COMPLETED / FAILED / PARTIAL. Failures are
retained and inspectable (records are never lost on parse/compile errors).
Large files should move to background workers; this modular-monolith step
keeps parsing bounded (10 MB / 200 sampled rows) inside the request while
recording the same status transitions a future queue worker would emit.
"""
from fastapi import APIRouter, UploadFile, Depends, HTTPException
from datetime import datetime, timezone
from ..core.tenant import get_ctx
from ..core.store import insert, list_all, update, get as sget
from ..core import audit as auditlog
from ..core import roles as RBAC
from ..core import versions as ver
from ..core.observability import METRICS
from ..services import ingestion as ing, ir as irs, compiler as comp
from ..services import seed as seedsvc
from ..services import provenance as prov
import time

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _user(ctx: dict) -> dict:
    from ..core.store import scan
    for u in scan("users"):
        if u.get("id") == ctx.get("user_id"):
            return u
    return {"role": "Viewer"}


@router.post("/upload")
async def upload(f: UploadFile, ctx: dict = Depends(get_ctx)):
    RBAC.require(_user(ctx), "ingest.write")
    t0 = time.perf_counter()
    raw = await f.read()
    src = insert("data_sources", ctx, {"filename": f.filename, "kind": "file",
                                       "status": "QUEUED", "row_count": 0})
    update("data_sources", ctx, src["id"], {"status": "PROCESSING"})
    try:
        cols, rows = ing.parse(f.filename, raw)
    except Exception as e:
        update("data_sources", ctx, src["id"], {"status": "FAILED", "error": str(e)[:500]})
        auditlog.record(ctx, "ingest.failed", f"source:{src['id']}", after={"error": str(e)[:300]})
        raise HTTPException(400, f"ingest failed (source retained for inspection): {e}")
    update("data_sources", ctx, src["id"], {"status": "parsed", "row_count": len(rows),
                                            "columns": cols[:50]})
    table = (f.filename.rsplit(".", 1)[0] if "." in (f.filename or "") else (f.filename or "data")).lower()
    try:
        ir = irs.detect_ir(table, cols, rows, f.filename)
    except Exception as e:
        update("data_sources", ctx, src["id"], {"status": "FAILED", "error": f"IR: {e}"[:500]})
        raise HTTPException(400, f"schema discovery failed: {e}")
    try:
        compiled = comp.compile_ir(ir, ctx, insert, list_all, update)
    except Exception as e:
        update("data_sources", ctx, src["id"], {"status": "PARTIAL", "error": f"compile: {e}"[:500]})
        raise HTTPException(500, f"graph compilation partially failed: {e}")
    now = datetime.now(timezone.utc).isoformat()
    for n in compiled["nodes"]:
        cur = sget("nodes", ctx, n["id"]) or n
        docs = list(cur.get("source_docs") or ([cur.get("source_doc")] if cur.get("source_doc") else []))
        if f.filename not in docs:
            docs.append(f.filename)
        history = list(cur.get("provenance") or [])
        history.append(prov.attach(f.filename, row=f"rows:{len(rows)}", confidence=0.9,
                                  level="INFERRED", method="column-classification"))
        # Never downgrade a CONFIRMED / USER_DEFINED node back to INFERRED.
        level = cur.get("level")
        if level not in ("CONFIRMED", "USER_DEFINED"):
            level = "INFERRED"
        update("nodes", ctx, n["id"], {"source_docs": docs, "confidence": 0.9,
                                       "last_observed": now, "provenance": history[-10:],
                                       "level": level})
    status = "COMPLETED" if compiled["nodes"] else "PARTIAL"
    update("data_sources", ctx, src["id"], {"status": status})
    snap = ver.snapshot(ctx, source=f"ingest:{f.filename}")
    METRICS["ingestions"] += 1
    METRICS["ingest_ms"] += int((time.perf_counter() - t0) * 1000)
    auditlog.record(ctx, "ingest.completed", f"source:{src['id']}",
                     after={"file": f.filename, "nodes": len(compiled["nodes"]),
                            "edges": len(compiled["edges"]), "version": snap.get("version")})
    return {"source": {**src, "status": status}, "columns": cols, "ir": ir,
            "graph": {"nodes": len(compiled["nodes"]), "edges": len(compiled["edges"]),
                      "version": snap.get("version")},
            "stats": f"discovered {len(compiled['nodes'])} types, {len(compiled['edges'])} rels from {f.filename}"}

@router.get("/sources")
def sources(ctx: dict = Depends(get_ctx)):
    return list_all("data_sources", ctx)

@router.get("/sources/{sid}")
def source_one(sid: str, ctx: dict = Depends(get_ctx)):
    s = sget("data_sources", ctx, sid)
    if not s: raise HTTPException(404, "source not found")
    return s

@router.post("/seed")
def seed(ctx: dict = Depends(get_ctx)):
    """One-click Acme demo dataset. Idempotent per tenant."""
    RBAC.require(_user(ctx), "ingest.write")
    out = seedsvc.seed_demo(ctx, insert, list_all, update)
    if out.get("seeded"):
        snap = ver.snapshot(ctx, source="seed")
        out["graph_version"] = snap.get("version")
        auditlog.record(ctx, "ingest.seed", "seed:acme", after=out)
    return out
