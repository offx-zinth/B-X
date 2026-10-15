"""Celery worker app: distributed processing for long ingest & simulation jobs.

Queues map 1:1 to app/services/jobs.QUEUES (ingest.parse, ingest.compile,
sim.compute). Redis is the broker; concurrency is per-queue so a slow parse
never starves interactive work.

Run:  celery -A app.worker worker -Q ingest.parse,ingest.compile,sim.compute -c 4
"""
from __future__ import annotations

try:
    from celery import Celery
except ImportError:  # celery not installed (dev/test): module still importable
    Celery = None  # type: ignore

import os

if Celery is not None:
    app = Celery("xray", broker=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                 backend=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    app.conf.task_routes = {
        "xray.ingest_parse": {"queue": "ingest.parse"},
        "xray.ingest_compile": {"queue": "ingest.compile"},
        "xray.sim_compute": {"queue": "sim.compute"},
    }
    app.conf.worker_prefetch_multiplier = 1
    app.conf.task_acks_late = True
    app.conf.task_time_limit = 600
else:  # pragma: no cover
    app = None

    def task_deco(*_a, **_kw):
        def deco(fn):
            fn.delay = lambda *a, **k: None  # type: ignore[attr-defined]
            return fn
        return deco
    task_deco.name = lambda *_a, **_kw: task_deco  # type: ignore[attr-defined]


def _task(name: str):
    if Celery is None:
        return task_deco
    return app.task(name=name)


@_task("xray.ingest_parse")
def ingest_parse(payload: dict) -> dict:
    return _run_ingest(payload)


@_task("xray.ingest_compile")
def ingest_compile(payload: dict) -> dict:
    return _run_ingest(payload)


@_task("xray.sim_compute")
def sim_compute(payload: dict) -> dict:
    from .services import simulation as sim
    from .core import store as st
    ctx = {"tenant_id": payload["tenant_id"]}
    nodes = st.list_all("nodes", ctx)
    edges = st.list_all("edges", ctx)
    formulas = [f for f in st.list_all("formulas", ctx)
                if f.get("status") in ("approved", "active")]
    res = sim.run(nodes, edges, formulas, payload.get("changes", []),
                  duration_days=int(payload.get("duration_days", 14)))
    return {"deltas": res.get("deltas", {}), "comparison": res.get("comparison", {})}


def _run_ingest(payload: dict) -> dict:
    """Fetch the blob and run the shared pipeline (same transitions as sync)."""
    from .core import store as st
    ctx = {"tenant_id": payload["tenant_id"]}
    try:
        blob = _fetch_blob(payload.get("object_key", ""))
        if blob is None:
            return {"status": "FAILED", "error": "blob not found"}
        from .routers.ingest import _run_job
        job_id = payload.get("job_id", "")
        _run_job(job_id, ctx, payload.get("filename", "upload.csv"), blob)
        job = st.get("ingest_jobs", ctx, job_id) if job_id else None
        return {"status": (job or {}).get("status", "COMPLETED"), "job_id": job_id}
    except Exception as e:
        return {"status": "FAILED", "error": f"{type(e).__name__}: {e}"[:300]}


def _fetch_blob(object_key: str) -> bytes | None:
    """Object storage fetch: S3/MinIO when configured, local spool otherwise."""
    if not object_key:
        return None
    try:
        import boto3
        bucket = os.environ.get("S3_BUCKET", "xray-uploads")
        s3 = boto3.client("s3", endpoint_url=os.environ.get("S3_ENDPOINT") or None)
        obj = s3.get_object(Bucket=bucket, Key=object_key)
        return obj["Body"].read()
    except Exception:
        pass
    spool = os.environ.get("XRAY_SPOOL_DIR", "/tmp/xray-spool")
    path = os.path.join(spool, os.path.basename(object_key))
    if os.path.exists(path):
        with open(path, "rb") as fh:
            return fh.read()
    return None
