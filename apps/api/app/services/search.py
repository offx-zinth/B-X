"""Semantic search over node descriptions and business rules.

pgvector when the extension is available (schema is created through Alembic,
never at request time); deterministic hash embeddings + in-memory cosine
similarity as the always-available fallback. Embeddings are content-addressed
so identical text never re-embeds.
"""
from __future__ import annotations
import hashlib
import math
import os

DIM = 256
_MEM: dict[str, list[float]] = {}


def embed(text: str) -> list[float]:
    """Deterministic bag-of-hashed-tokens embedding (no network dependency)."""
    vec = [0.0] * DIM
    tokens = [t for t in (text or "").lower().replace("_", " ").split() if len(t) > 1]
    for tok in tokens:
        h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
        vec[h % DIM] += 1.0
        if h % 7 == 0:
            vec[(h >> 8) % DIM] += 0.5
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _redis():
    url = os.environ.get("REDIS_URL", "")
    if not url:
        return None
    try:
        import redis
        return redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=2)
    except Exception:
        return None


def _fs_key(tenant_id: str, node_id: str) -> str:
    return f"emb:{tenant_id}:{node_id}"


def _content_key(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()[:16]


def index_nodes(ctx: dict, nodes: list[dict]) -> int:
    """Index/refresh node embeddings. Content-addressed: unchanged text is free."""
    tenant = ctx.get("tenant_id", "")
    n = 0
    for node in nodes or []:
        text = f"{node.get('type','')} {node.get('name','')} " \
               f"{' '.join(f'{k} {v}' for k, v in (node.get('properties') or {}).items() if not isinstance(v, (dict, list)))}"
        key = _fs_key(tenant, node.get("id", ""))
        ck = f"{key}:ck"
        stored = _MEM.get(ck)
        if stored == _content_key(text):
            continue
        _MEM[key] = embed(text)
        _MEM[ck] = _content_key(text)
        n += 1
    return n


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def search(ctx: dict, query: str, nodes: list[dict], k: int = 10) -> list[dict]:
    """Rank nodes by semantic similarity to the query. Empty when unindexed."""
    tenant = ctx.get("tenant_id", "")
    if not nodes:
        return []
    index_nodes(ctx, nodes)
    qv = embed(query)
    scored = []
    for node in nodes:
        vec = _MEM.get(_fs_key(tenant, node.get("id", "")))
        if not vec:
            continue
        scored.append((_cosine(qv, vec), node))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [{"id": n.get("id"), "type": n.get("type"), "name": n.get("name"),
             "score": round(float(s), 4)} for s, n in scored[:k] if s > 0]


def pgvector_sql() -> str:
    """DDL for the pgvector-backed index (run through Alembic on cutover)."""
    return f"""
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE TABLE IF NOT EXISTS node_embeddings (
      tenant_id TEXT NOT NULL,
      node_id UUID NOT NULL,
      content_hash TEXT NOT NULL,
      embedding vector({DIM}) NOT NULL,
      PRIMARY KEY (tenant_id, node_id)
    );
    CREATE INDEX IF NOT EXISTS idx_node_embeddings_ivfflat
      ON node_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
    """
