"""Provenance: every fact knows where it came from.

Each discovered value carries: source_file, source_type, source_record,
source_row, source_column, source_timestamp, extraction_method, confidence,
created_at, updated_at — plus a lifecycle level:

CONFIRMED (human-verified / system-of-record) > USER_DEFINED > INFERRED >
AI_SUGGESTED. Inferred information is never presented as confirmed.
"""
from __future__ import annotations
from datetime import datetime, timezone

LEVELS = ("CONFIRMED", "INFERRED", "USER_DEFINED", "AI_SUGGESTED")


def attach(source_doc: str, sheet: str = "", row: str = "", confidence: float = 1.0,
           level: str = "INFERRED", method: str = "heuristic",
           column: str = "", source_type: str = "file") -> dict:
    now = datetime.now(timezone.utc).isoformat()
    lvl = level if level in LEVELS else "INFERRED"
    return {
        "source_file": source_doc, "source_doc": source_doc,
        "source_type": source_type, "source_record": sheet, "sheet": sheet,
        "source_row": str(row), "row_ref": str(row),
        "source_column": column, "source_timestamp": now,
        "extraction_method": method, "confidence": float(confidence),
        "level": lvl, "created_at": now, "updated_at": now,
        "last_observed": now,
    }


def explain(node: dict) -> dict:
    """Answer 'Where did this value come from?' for any node/edge/formula."""
    prov = node.get("provenance") or node.get("source_docs") or []
    return {
        "id": node.get("id"), "type": node.get("type"),
        "level": node.get("level", "INFERRED"),
        "confidence": node.get("confidence", 0.0),
        "provenance": prov,
        "source_docs": node.get("source_docs", []),
        "last_observed": node.get("last_observed"),
    }
