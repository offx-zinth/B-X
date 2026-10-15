"""Per-tenant token bucket (Redis-backed, in-memory fallback).

Enforces LLM token/rate budgets per tenant_id with automatic fallback:
over-budget callers get deterministic answers instead of 429s for reads.
"""
from __future__ import annotations
import time

_MEM: dict[str, list[float]] = {}
LIMIT = 60  # LLM calls per minute per tenant
WINDOW = 60.0


def _redis():
    import os
    url = os.environ.get("REDIS_URL", "")
    if not url:
        return None
    try:
        import redis
        return redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=2)
    except Exception:
        return None


def allow(tenant_id: str, limit: int = LIMIT) -> bool:
    r = _redis()
    now = time.time()
    if r is not None:
        try:
            key = f"xray:bucket:{tenant_id}"
            pipe = r.pipeline()
            pipe.zremrangebyscore(key, 0, now - WINDOW)
            pipe.zcard(key)
            _, count = pipe.execute()
            if int(count) >= limit:
                return False
            r.zadd(key, {str(now): now})
            r.expire(key, int(WINDOW) + 5)
            return True
        except Exception:
            pass
    buf = _MEM.setdefault(tenant_id, [])
    while buf and buf[0] <= now - WINDOW:
        buf.pop(0)
    if len(buf) >= limit:
        return False
    buf.append(now)
    return True
