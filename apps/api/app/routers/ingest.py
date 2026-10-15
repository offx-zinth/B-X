"""Ingestion pipeline: UPLOAD -> VALIDATE -> STORE -> PARSE -> EXTRACT ->
NORMALIZE -> VALIDATE -> COMPILE -> GRAPH UPDATE.

Statuses: QUEUED -> PROCESSING -> COMPLETED / FAILED / PARTIAL. Failures are
retained and inspectable (records are never lost on parse/compile errors).
Large files should move to background workers; this modular-monolith step
keeps parsing bounded (10 MB / 200 sampled rows) inside the request while
recording the same status transitions a future queue worker would emit.
"""
from fastapi import APIRouter, UploadFile, Depends, HTTPException, BackgroundTasks
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
from ..services import jobs as jobsvc
import os
import time

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _user(ctx: dict) -> dict:
    from ..core.store import get_user
    from fastapi import HTTPException
    u = get_user(ctx.get("tenant_id", ""), ctx.get("user_id", ""))
    if not u:
        raise HTTPException(401, "unknown user")
    return u


def process_upload(ctx: dict, filename: str, raw: bytes, allow_large: bool = False) -> dict:
    """Shared pipeline used by sync upload and async workers (same transitions)."""
    t0 = time.perf_counter()
    src = insert("data_sources", ctx, {"filename": filename, "kind": "file",
                                       "status": "QUEUED", "row_count": 0})
    update("data_sources", ctx, src["id"], {"status": "PROCESSING"})
    try:
        cols, rows = ing.parse(filename, raw, allow_large=allow_large)
    except Exception as e:
        update("data_sources", ctx, src["id"], {"status": "FAILED", "error": str(e)[:500]})
        auditlog.record(ctx, "ingest.failed", f"source:{src['id']}", after={"error": str(e)[:300]})
        raise
    update("data_sources", ctx, src["id"], {"status": "parsed", "row_count": len(rows),
                                            "columns": cols[:50]})
    table = (filename.rsplit(".", 1)[0] if "." in (filename or "") else (filename or "data")).lower()
    ir = irs.detect_ir(table, cols, rows, filename)
    compiled = comp.compile_ir(ir, ctx, insert, list_all, update)
    now = datetime.now(timezone.utc).isoformat()
    for n in compiled["nodes"]:
        cur = sget("nodes", ctx, n["id"]) or n
        docs = list(cur.get("source_docs") or ([cur.get("source_doc")] if cur.get("source_doc") else []))
        if filename not in docs:
            docs.append(filename)
        history = list(cur.get("provenance") or [])
        history.append(prov.attach(filename, row=f"rows:{len(rows)}", confidence=0.9,
                                  level="INFERRED", method="column-classification"))
        level = cur.get("level")
        if level not in ("CONFIRMED", "USER_DEFINED"):
            level = "INFERRED"
        update("nodes", ctx, n["id"], {"source_docs": docs, "confidence": 0.9,
                                       "last_observed": now, "provenance": history[-10:],
                                       "level": level})
    status = "COMPLETED" if compiled["nodes"] else "PARTIAL"
    update("data_sources", ctx, src["id"], {"status": status})
    snap = ver.snapshot(ctx, source=f"ingest:{filename}")
    METRICS["ingestions"] += 1
    METRICS["ingest_ms"] += int((time.perf_counter() - t0) * 1000)
    auditlog.record(ctx, "ingest.completed", f"source:{src['id']}",
                     after={"file": filename, "nodes": len(compiled["nodes"]),
                            "edges": len(compiled["edges"]), "version": snap.get("version")})
    return {"source": {**src, "status": status}, "columns": cols, "ir": ir,
            "graph": {"nodes": len(compiled["nodes"]), "edges": len(compiled["edges"]),
                      "version": snap.get("version")},
            "stats": f"discovered {len(compiled['nodes'])} types, {len(compiled['edges'])} rels from {filename}"}


def _persist_blob(object_key: str, raw: bytes) -> bool:
    """Object storage write: S3/MinIO when configured, local spool otherwise."""
    if not object_key:
        return False
    try:
        import boto3
        bucket = os.environ.get("S3_BUCKET", "xray-uploads")
        s3 = boto3.client("s3", endpoint_url=os.environ.get("S3_ENDPOINT") or None)
        s3.put_object(Bucket=bucket, Key=object_key, Body=raw)
        return True
    except Exception:
        pass
    try:
        spool = os.environ.get("XRAY_SPOOL_DIR", "/tmp/xray-spool")
        os.makedirs(spool, exist_ok=True)
        with open(os.path.join(spool, os.path.basename(object_key)), "wb") as fh:
            fh.write(raw)
        return True
    except Exception:
        return False


def _run_job(job_id: str, ctx: dict, filename: str, raw: bytes) -> None:
    try:
        jobsvc.mark(ctx, job_id, {"status": "PROCESSING", "progress": 10}, update, sget)
        out = process_upload(ctx, filename, raw, allow_large=True)
        jobsvc.mark(ctx, job_id, {"status": "COMPLETED", "progress": 100,
                                  "result": {"source_id": out["source"]["id"],
                                             "graph": out["graph"]}}, update, sget)
    except Exception as e:
        try:
            jobsvc.mark(ctx, job_id, {"status": "FAILED", "error": str(e)[:500]}, update, sget)
        except Exception:
            pass


@router.post("/upload")
async def upload(f: UploadFile, ctx: dict = Depends(get_ctx)):
    RBAC.require(_user(ctx), "ingest.write")
    raw = await f.read()
    infected = ing.scan_malware(raw)
    if infected:
        raise HTTPException(400, f"upload quarantined by malware scanner: {infected[:120]}")
    try:
        return process_upload(ctx, f.filename, raw)
    except ValueError as e:
        raise HTTPException(400, f"ingest failed (source retained for inspection): {e}")
    except Exception as e:
        raise HTTPException(500, f"graph compilation partially failed: {e}")


@router.post("/upload-async")
async def upload_async(f: UploadFile, background: BackgroundTasks, ctx: dict = Depends(get_ctx)):
    """Decoupled upload: returns a job id immediately; worker processes the blob.

    [Client] POST /upload-async -> [API records job + blob] -> [Worker queue
    ingest.parse] -> WebSocket/SSE or poll GET /ingest/jobs/{id}.
    """
    RBAC.require(_user(ctx), "ingest.write")
    raw = await f.read()
    try:
        ing.validate(f.filename, raw, allow_large=True)
    except ValueError as e:
        raise HTTPException(400, str(e))
    infected = ing.scan_malware(raw)
    if infected:
        raise HTTPException(400, f"upload quarantined by malware scanner: {infected[:120]}")
    job = jobsvc.create_job(ctx, "ingest.parse", f.filename, len(raw), insert)
    payload = {"job_id": job["id"], "tenant_id": ctx["tenant_id"],
               "filename": f.filename, "size": len(raw)}
    object_key = f"uploads/{job['id']}"
    _persist_blob(object_key, raw)
    queued = jobsvc.enqueue("ingest.parse", payload)
    if queued:
        # Distributed worker path (Celery consumes ingest.parse tasks).
        try:
            from ..worker import ingest_parse
            ingest_parse.delay({**payload, "object_key": object_key})
        except Exception:
            pass
        jobsvc.mark(ctx, job["id"], {"queue": "ingest.parse", "status": "QUEUED"}, update, sget)
    else:
        # No broker: run in-process background task (same status transitions).
        background.add_task(_run_job, job["id"], dict(ctx), f.filename, raw)
    return {"job_id": job["id"], "status": "QUEUED", "queue": "ingest.parse",
            "poll": f"/ingest/jobs/{job['id']}"}


@router.get("/jobs")
def jobs(ctx: dict = Depends(get_ctx), limit: int = 50):
    rows = list_all("ingest_jobs", ctx)
    rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
    return rows[:max(1, min(int(limit or 50), 200))]


@router.get("/jobs/{jid}")
def job_one(jid: str, ctx: dict = Depends(get_ctx)):
    j = sget("ingest_jobs", ctx, jid)
    if not j:
        raise HTTPException(404, "job not found")
    return j


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
