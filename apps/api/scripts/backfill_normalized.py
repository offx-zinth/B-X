#!/usr/bin/env python3
"""Backfill xray_store (compat JSONB) -> normalized relational tables.

Usage (from apps/api, with DATABASE_URL pointing at the target database):

    python scripts/backfill_normalized.py            # mirror everything
    python scripts/backfill_normalized.py --verify   # backfill + verify counts
    python scripts/backfill_normalized.py --verify-only

Cutover checklist:
  1. Run this backfill (idempotent; safe to re-run any time).
  2. Run with --verify and require "MISMATCH 0".
  3. Set XRAY_READ_MODE=normalized on the API and worker, restart, smoke test.
  4. Rollback is instant: unset XRAY_READ_MODE (compat store remains the
     source of truth throughout the migration window).

Run as a database role that bypasses RLS (the default superuser owner) or as
xray_app with app.tenant_id='all' — this script scopes every batch explicitly.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core import store  # noqa: E402


def _collections() -> list[str]:
    """Dependency order: parents before children (edges FK -> nodes, runs -> scenarios)."""
    order = ["tenants", "users", "nodes", "edges", "formulas", "graph_versions",
             "data_sources", "scenarios", "simulation_runs", "ingest_jobs",
             "reports", "audit_log"]
    known = [c for c in order if c in store._NORMALIZED_TABLES]
    return known + [c for c in sorted(store._NORMALIZED_TABLES) if c not in known]


def _normalized_count(conn, coll: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {coll}").fetchone()[0]


def _compat_count(conn, coll: str) -> int:
    return conn.execute("SELECT count(*) FROM xray_store WHERE collection=%s",
                        (coll,)).fetchone()[0]


def run(verify: bool, verify_only: bool, batch: int) -> int:
    pool = store._connect()
    if pool is None:
        print(f"[backfill] database unavailable: {store.store_error()}", file=sys.stderr)
        return 2
    totals: dict[str, tuple[int, int]] = {}
    with pool.connection() as conn:
        with conn.transaction():
            conn.execute("SELECT set_config('app.tenant_id', 'all', true)")
            for coll in _collections():
                rows = conn.execute(
                    "SELECT id, data FROM xray_store WHERE collection=%s ORDER BY id",
                    (coll,)).fetchall()
                if not verify_only:
                    done = 0
                    for _id, data in rows:
                        obj = dict(data)
                        obj.setdefault("id", _id)
                        store._mirror_upsert(conn, coll, obj)
                        done += 1
                    print(f"[backfill] {coll}: mirrored {done} rows")
                if verify:
                    compat = _compat_count(conn, coll)
                    norm = _normalized_count(conn, coll)
                    totals[coll] = (compat, norm)
                    status = "OK" if compat == norm else "MISMATCH"
                    print(f"[verify]   {coll}: compat={compat} normalized={norm} {status}")
    if verify:
        bad = [c for c, (a, b) in totals.items() if a != b]
        print(f"[verify]   MISMATCH {len(bad)}" + (f" -> {bad}" if bad else ""))
        return 1 if bad else 0
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verify", action="store_true", help="compare counts after backfill")
    ap.add_argument("--verify-only", action="store_true", help="skip writes, only compare")
    ap.add_argument("--batch", type=int, default=500, help="reserved; batches stream per collection")
    args = ap.parse_args()
    if args.verify_only:
        args.verify = True
    return run(verify=args.verify, verify_only=args.verify_only, batch=args.batch)


if __name__ == "__main__":
    raise SystemExit(main())
