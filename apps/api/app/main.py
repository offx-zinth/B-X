from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    from fastapi.responses import JSONResponse
    _LIMITER = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
    _HAS_LIMITER = True
except ImportError:  # local test env without slowapi: degrade to no rate limiting
    _LIMITER = None
    _HAS_LIMITER = False

from .routers import auth, ingest, graph, formulas, simulations, ai, dashboard, reports, system
from .core.observability import ObservabilityMiddleware
from .core.store import backend, store_error
from .core.config import settings

# Sentry: release-tagged error monitoring when SENTRY_DSN is set (both API
# and worker processes share this entrypoint).
try:
    import os as _os
    import sentry_sdk as _sentry
    _dsn = _os.environ.get("SENTRY_DSN", "")
    if _dsn:
        _sentry.init(dsn=_dsn, traces_sample_rate=float(_os.environ.get("SENTRY_TRACES", "0.1")),
                     environment=_os.environ.get("ENV", "production"), release="xray-api@1.0.0")
except Exception:
    pass

limiter = _LIMITER

app = FastAPI(title="Business X-Ray API", version="1.0.0",
              description="Executable operational graph: graph is source of truth, AI orchestrates deterministic engines.",
              docs_url="/docs", openapi_url="/openapi.json")
if _HAS_LIMITER:
    from fastapi.responses import JSONResponse
    from slowapi.errors import RateLimitExceeded
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, lambda req, exc: JSONResponse({"detail": "rate limit exceeded"}, status_code=429))

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ObservabilityMiddleware)


@app.get("/health")
def health():
    be = backend()
    return {"ok": True, "graph": "source-of-truth", "ai": "orchestrator",
            "store": be, "degraded": be != "postgres",
            "store_error": store_error() or None, "version": "1.0.0"}

@app.get("/ready")
def ready():
    be = backend()
    return {"ready": True, "store": be, "degraded": be != "postgres"}


_ROUTERS = [auth.router, ingest.router, graph.router, formulas.router,
            simulations.router, ai.router, dashboard.router, reports.router, system.router]

for _r in _ROUTERS:
    app.include_router(_r)
    # Versioned API (spec section 32): /api/v1/* mirrors unprefixed routes.
    app.include_router(_r, prefix="/api/v1")


@app.get("/api/v1/health")
def v1_health():
    be = backend()
    return {"ok": True, "api": "v1", "store": be, "degraded": be != "postgres"}
