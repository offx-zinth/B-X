"""Observability: structured logs + request IDs + Prometheus + OpenTelemetry hooks.

Every request gets an ``X-Request-ID``. Logs are single-line JSON consumable
by OTel collectors. Counters stay in-process for hermetic tests; when
``prometheus_client`` is installed the same observations feed real histograms:
  xray_http_duration_seconds, xray_simulation_duration_seconds,
  xray_formula_eval_errors_total, xray_llm_tool_latency_seconds
"""
from __future__ import annotations
import json
import time
import uuid
from collections import Counter
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

METRICS: Counter = Counter()
FAILURES: Counter = Counter()

try:
    from prometheus_client import Histogram, Counter as _PCounter, generate_latest, CONTENT_TYPE_LATEST
    _PROM = True
    HTTP_HIST = Histogram("xray_http_duration_seconds", "HTTP latency", ["method", "path", "status"])
    SIM_HIST = Histogram("xray_simulation_duration_seconds", "Simulation runtime", ["status", "tenant"])
    FORMULA_ERR = _PCounter("xray_formula_eval_errors_total", "Formula errors", ["error_type"])
    LLM_HIST = Histogram("xray_llm_tool_latency_seconds", "LLM tool latency", ["tool_name", "provider"])
except Exception:
    _PROM = False
    HTTP_HIST = SIM_HIST = FORMULA_ERR = LLM_HIST = None

    def generate_latest():  # type: ignore
        return b""
    CONTENT_TYPE_LATEST = "text/plain"

try:
    from opentelemetry import trace as _trace
    _TRACER = _trace.get_tracer("xray.api")
except Exception:
    _TRACER = None


def log(event: str, **fields) -> None:
    rec = {"event": event, **fields}
    try:
        print(json.dumps(rec, default=str), flush=True)
    except Exception:
        print(f"event={event} fields={fields}", flush=True)


def observe_simulation(duration_s: float, status: str, tenant: str = "") -> None:
    METRICS["simulations"] += 1
    METRICS["sim_ms"] += int(duration_s * 1000)
    if _PROM and SIM_HIST is not None:
        try:
            SIM_HIST.labels(status=status, tenant=(tenant or "unknown")[:32]).observe(duration_s)
        except Exception:
            pass


def observe_formula_error(error_type: str) -> None:
    FAILURES["formula_eval"] += 1
    if _PROM and FORMULA_ERR is not None:
        try:
            FORMULA_ERR.labels(error_type=error_type[:32]).inc()
        except Exception:
            pass


def observe_llm_tool(tool_name: str, provider: str, duration_s: float) -> None:
    METRICS["llm_tools"] += 1
    if _PROM and LLM_HIST is not None:
        try:
            LLM_HIST.labels(tool_name=tool_name[:32], provider=provider[:32]).observe(duration_s)
        except Exception:
            pass


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
        start = time.perf_counter()
        tenant = ""
        try:
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer ") and len(auth) > 20:
                tenant = "jwt"
            elif request.cookies.get("access_token"):
                tenant = "cookie"
        except Exception:
            pass
        span = None
        if _TRACER is not None:
            try:
                span = _TRACER.start_span(f"{request.method} {request.url.path}")
            except Exception:
                span = None
        try:
            resp = await call_next(request)
            status = resp.status_code
        except Exception as e:
            FAILURES["unhandled"] += 1
            log("request_error", request_id=rid, path=request.url.path, error=str(e)[:300])
            raise
        finally:
            if span is not None:
                try:
                    span.end()
                except Exception:
                    pass
        dur = (time.perf_counter() - start) * 1000
        METRICS["requests"] += 1
        METRICS[f"route:{request.url.path}"] += 1
        if _PROM and HTTP_HIST is not None:
            try:
                HTTP_HIST.labels(method=request.method, path=request.url.path[:64],
                                 status=str(status)).observe(dur / 1000.0)
            except Exception:
                pass
        log("request", request_id=rid, tenant=tenant, method=request.method,
            path=request.url.path, status=status, duration_ms=round(dur, 1))
        resp.headers["X-Request-ID"] = rid
        return resp


def snapshot() -> dict:
    out = {"metrics": dict(METRICS), "failures": dict(FAILURES)}
    if _PROM:
        out["prometheus"] = True
    return out


def prometheus_bytes() -> tuple[bytes, str]:
    try:
        return generate_latest(), CONTENT_TYPE_LATEST
    except Exception:
        return b"", "text/plain"
