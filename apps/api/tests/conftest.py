"""Test bootstrap: hermetic by default, live-Postgres mode on request.

Unit runs pin the store to the in-memory backend so a developer's local
Postgres (or a CI sidecar) can never leak into assertions.

Integration mode: set ``XRAY_TEST_PG=postgresql://…`` (throwaway database).
DATABASE_URL is routed there for every test and the graph tables are
truncated once per session so reruns are deterministic. The RLS isolation
tests use the same DSN with a non-superuser role.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PG_URL = os.environ.get("XRAY_TEST_PG", "")

if PG_URL:
    os.environ["DATABASE_URL"] = PG_URL
else:
    os.environ.pop("DATABASE_URL", None)

_TRUNCATE = ["audit_log", "simulation_runs", "scenarios", "graph_versions",
             "formulas", "node_states", "edges", "nodes", "data_sources",
             "ingest_jobs", "reports", "outbox_events", "users", "tenants",
             "xray_store"]


@pytest.fixture(scope="session", autouse=True)
def _clean_pg():
    """Once-per-session truncate for integration runs (never in hermetic mode)."""
    if PG_URL:
        try:
            import psycopg
            with psycopg.connect(PG_URL, autocommit=True) as conn:
                for table in _TRUNCATE:
                    try:
                        conn.execute(f"TRUNCATE {table} CASCADE")
                    except Exception:
                        pass
        except Exception:
            pass
    yield
