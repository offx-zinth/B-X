"""Observability: structured logs + request IDs + basic metrics.

Every request gets an ``X-Request-ID`` (reused when the client sends one).
Logs are single-line JSON with request_id, tenant_id, path, method, status,
duration_ms — consumable by OpenTelemetry collectors / error monitoring.
Counters track ingestion / compilation / simulation durations, formula
failures, AI tool calls, API latency and job failures in-process.
"""
from __future__ import annotations
import json, time, uuid
from collections import Counter
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

METRICS: Counter = Counter()
FAILURES: Counter = Counter()


def log(event: str, **fields) -> None:
    rec = {"event": event, **fields}
    try:
        print(json.dumps(rec, default=str), flush=True)
    except Exception:
        print(f"event={event} fields={fields}", flush=True)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
        start = time.perf_counter()
        tenant = ""
        try:
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer ") and len(auth) > 20:
                tenant = "jwt"
        except Exception:
            pass
        try:
            resp = await call_next(request)
            status = resp.status_code
        except Exception as e:
            FAILURES["unhandled"] += 1
            log("request_error", request_id=rid, path=request.url.path,
                error=str(e)[:300])
            raise
        dur = (time.perf_counter() - start) * 1000
        METRICS["requests"] += 1
        METRICS[f"route:{request.url.path}"] += 1
        log("request", request_id=rid, tenant=tenant, method=request.method,
            path=request.url.path, status=status, duration_ms=round(dur, 1))
        resp.headers["X-Request-ID"] = rid
        return resp


def snapshot() -> dict:
    return {"metrics": dict(METRICS), "failures": dict(FAILURES)}
