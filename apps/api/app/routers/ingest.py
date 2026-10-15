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
def sources(ctx: dict = Depends(get_ctx), limit: int = 100, offset: int = 0):
    rows = list_all("data_sources", ctx)
    limit = max(1, min(int(limit or 100), 500)); offset = max(0, int(offset or 0))
    return rows[offset:offset + limit]

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


@router.post("/seed-tea-shop")
def seed_tea(ctx: dict = Depends(get_ctx)):
    """Tea-shop reference graph. Same 14-primitive engine as the factory."""
    RBAC.require(_user(ctx), "ingest.write")
    out = seedsvc.seed_tea_shop(ctx, insert, list_all)
    if out.get("seeded"):
        snap = ver.snapshot(ctx, source="tea-seed")
        out["graph_version"] = snap.get("version")
        auditlog.record(ctx, "ingest.seed", "seed:tea", after=out)
    return out


@router.get("/sample-catalog")
def sample_catalog(ctx: dict = Depends(get_ctx)):
    """Businesses with one-click samples. Tenant-agnostic catalog, tenant-scoped loads."""
    from ..services.samples import sample_files
    catalog = []
    for key, spec in seedsvc.BUSINESS_SEEDS.items():
        files = sample_files(key)
        catalog.append({"key": key, "label": spec["label"], "description": spec["description"],
                        "files": files, "nodes": len(spec["nodes"]), "formulas": len(spec["formulas"])})
    return {"businesses": catalog}


@router.post("/seed/{business}")
def seed_business(business: str, ctx: dict = Depends(get_ctx)):
    """One-click executable graph for any catalog business. Merge, never clobber."""
    RBAC.require(_user(ctx), "ingest.write")
    try:
        out = seedsvc.seed_business(business, ctx, insert, list_all, update)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if out.get("seeded"):
        snap = ver.snapshot(ctx, source=f"seed:{business}")
        out["graph_version"] = snap.get("version")
        out["business"] = business
        auditlog.record(ctx, "ingest.seed", f"seed:{business}", after=out)
    return out


@router.post("/load-sample/{business}")
def load_sample(business: str, ctx: dict = Depends(get_ctx)):
    """Load a business's sample CSVs through the REAL pipeline (parse → IR → compile),
    then attach its executable formulas. Proves heterogeneous exports compile
    into one graph instead of bypassing ingestion via seed-only nodes."""
    RBAC.require(_user(ctx), "ingest.write")
    import os
    from ..services.samples import sample_paths
    key = (business or "").lower()
    if key not in seedsvc.BUSINESS_SEEDS:
        raise HTTPException(400, f"unknown business '{business}'")
    spec = seedsvc.BUSINESS_SEEDS[key]
    try:
        paths = sample_paths(key)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not paths:
        raise HTTPException(404, f"no sample CSVs for '{business}'")
    loaded: list[dict] = []
    for p in paths:
        try:
            with open(p, "rb") as fh:
                raw = fh.read()
            cols, rows = ing.parse(os.path.basename(p), raw)
        except Exception as e:
            raise HTTPException(400, f"{os.path.basename(p)}: {e}")
        table = os.path.splitext(os.path.basename(p))[0].lower()
        ir = irs.detect_ir(table, cols, rows, os.path.basename(p))
        compiled = comp.compile_ir(ir, ctx, insert, list_all, update)
        src = insert("data_sources", ctx, {"filename": f"sample:{business}/{os.path.basename(p)}",
                                           "kind": "sample", "status": "COMPLETED",
                                           "row_count": len(rows), "columns": cols[:50]})
        loaded.append({"file": os.path.basename(p), "source_id": src["id"],
                       "nodes": len(compiled["nodes"]), "edges": len(compiled["edges"])})
    # Attach executable formulas (approved) so the loaded graph simulates immediately.
    existing_targets = {f.get("target") for f in list_all("formulas", ctx)}
    added = 0
    for target, expr in spec["formulas"]:
        if target in existing_targets:
            continue
        from ..services import formula_engine as bfl
        insert("formulas", ctx, {"target": target, "expression": expr,
                                "dependencies": bfl.dependencies_of(expr),
                                "status": "approved", "created_by": f"sample:{business}",
                                "level": "CONFIRMED"})
        added += 1
    snap = ver.snapshot(ctx, source=f"load-sample:{business}")
    out = {"business": business, "files_loaded": loaded, "formulas_added": added,
           "graph_version": snap.get("version"),
           "nodes": len(list_all("nodes", ctx)), "edges": len(list_all("edges", ctx))}
    auditlog.record(ctx, "ingest.load_sample", f"sample:{business}", after=out)
    return out
