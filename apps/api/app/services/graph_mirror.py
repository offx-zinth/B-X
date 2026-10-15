"""Neo4j traversal mirror. Postgres stays the system of record.

Best-effort projection: every node/edge write is mirrored to Neo4j when the
service is reachable; failures never block the request (the app works without
Neo4j — see docker-compose `neo4j` service comments). Reads always come from
Postgres/memory store so tenant isolation (RLS) stays authoritative.
"""
from __future__ import annotations
import os
import threading

_LOCK = threading.Lock()
_DRIVER = None
_INIT_DONE = False
_LAST_ERROR = ""


def _config() -> tuple[str, str, str]:
    return (
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        os.environ.get("NEO4J_USER", "neo4j"),
        os.environ.get("NEO4J_PASSWORD", "xraypass"),
    )


def driver():
    global _DRIVER, _INIT_DONE, _LAST_ERROR
    with _LOCK:
        if _DRIVER is not None:
            return _DRIVER
        uri, user, password = _config()
        try:
            from neo4j import GraphDatabase
            d = GraphDatabase.driver(uri, auth=(user, password))
            d.verify_connectivity()
            with d.session() as s:
                s.run("CREATE CONSTRAINT node_id IF NOT EXISTS FOR (n:XNode) REQUIRE n.id IS UNIQUE")
            _DRIVER = d
            _INIT_DONE = True
            return d
        except Exception as e:
            _LAST_ERROR = f"{type(e).__name__}: {e}"
            return None


def status() -> dict:
    d = driver()
    if d is None:
        return {"enabled": False, "error": _LAST_ERROR or "unreachable"}
    return {"enabled": True, "uri": _config()[0]}


def mirror_node(tenant_id: str, node: dict) -> None:
    d = driver()
    if d is None:
        return
    try:
        with d.session() as s:
            s.run("MERGE (n:XNode {id: $id}) SET n.tenant_id=$t, n.type=$typ, n.name=$nm",
                  id=node.get("id"), t=tenant_id,
                  typ=node.get("type", ""), nm=node.get("name", ""))
    except Exception:
        return


def mirror_edge(tenant_id: str, edge: dict) -> None:
    d = driver()
    if d is None:
        return
    try:
        with d.session() as s:
            s.run("""MATCH (a:XNode {id:$s}), (b:XNode {id:$t})
                     MERGE (a)-[r:XREL {id:$id}]->(b)
                     SET r.tenant_id=$tenant, r.type=$typ""",
                  s=edge.get("source_node"), t=edge.get("target_node"),
                  id=edge.get("id"), tenant=tenant_id, typ=edge.get("type", ""))
    except Exception:
        return


def last_error() -> str:
    return _LAST_ERROR
