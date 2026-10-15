"""Background job pipeline: upload decoupled from processing.

Queues: ingest.parse, ingest.compile, sim.compute (logical names; one worker
pool serves all). Broker: Redis when REDIS_URL is set, else in-process
FastAPI BackgroundTasks + xray_store job records. Statuses mirror the sync
path so the UI polls one shape: QUEUED -> PROCESSING -> COMPLETED/FAILED.
"""
from __future__ import annotations
import time
import uuid

QUEUES = ("ingest.parse", "ingest.compile", "sim.compute")


def _redis():
    import os
    url = os.environ.get("REDIS_URL", "")
    if not url:
        return None
    try:
        import redis
        return redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=5)
    except Exception:
        return None


def enqueue(queue: str, payload: dict) -> str:
    """Enqueue payload, return job id. Falls back to inline (sync worker does it)."""
    assert queue in QUEUES, f"unknown queue {queue}"
    r = _redis()
    if r is None:
        return ""
    try:
        import json
        job_id = payload.get("job_id") or str(uuid.uuid4())
        r.lpush(f"xray:q:{queue}", json.dumps({"job_id": job_id, **payload}, default=str))
        r.setex(f"xray:job:{job_id}:queued", 3600, queue)
        return job_id
    except Exception:
        return ""


def dequeue(queue: str, timeout: int = 5) -> dict | None:
    r = _redis()
    if r is None:
        return None
    try:
        import json
        item = r.brpop(f"xray:q:{queue}", timeout=timeout)
        if not item:
            return None
        return json.loads(item[1])
    except Exception:
        return None


def create_job(ctx: dict, kind: str, filename: str, size: int, insert) -> dict:
    return insert("ingest_jobs", ctx, {"kind": kind, "filename": filename, "size": size,
                                       "status": "QUEUED", "queue": "ingest.parse",
                                       "progress": 0, "created_at": time.time()})


def mark(ctx: dict, job_id: str, patch: dict, update, get) -> dict | None:
    job = get("ingest_jobs", ctx, job_id)
    if not job:
        return None
    return update("ingest_jobs", ctx, job_id, patch)
