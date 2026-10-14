"""Ingestion: File Parser -> schema/columns -> IR.

Supports CSV / XLSX / JSON / PDF(text) / DOCX(text). DOCX paragraphs and
tables are flattened into rows. Validation caps file size (10 MB) and row
count (5000 raw, 200 sampled into IR) so synchronous API requests stay
bounded; large files are meant to move to background jobs (see ingest
router statuses QUEUED -> PROCESSING -> COMPLETED/FAILED/PARTIAL).
"""
from __future__ import annotations
import csv, json, io

MAX_BYTES = 10 * 1024 * 1024
SUPPORTED = ("CSV", "XLSX", "JSON", "PDF", "DOCX")


def validate(filename: str, raw: bytes) -> None:
    if not raw:
        raise ValueError("empty file")
    if len(raw) > MAX_BYTES:
        raise ValueError(f"file too large ({len(raw)} bytes > {MAX_BYTES}); split into smaller exports")
    fn = (filename or "").lower()
    if not (fn.endswith(".csv") or fn.endswith(".json") or fn.endswith((".xlsx", ".xlsm", ".xltx"))
            or fn.endswith(".pdf") or fn.endswith(".docx")):
        raise ValueError(f"unsupported type: {filename} (supported: {', '.join(SUPPORTED)})")


def parse_csv(raw: bytes) -> tuple[list[str], list[dict]]:
    text = raw.decode("utf-8-sig", errors="replace")
    rdr = csv.DictReader(io.StringIO(text))
    cols = rdr.fieldnames or []
    rows = [r for _, r in zip(range(200), rdr)]
    return cols, rows


def parse_json(raw: bytes) -> tuple[list[str], list[dict]]:
    data = json.loads(raw.decode())
    if isinstance(data, dict):
        data = [data]
    cols = sorted({k for r in data[:50] if isinstance(r, dict) for k in r.keys()}) if data else []
    rows = [r for r in data[:200] if isinstance(r, dict)]
    return cols, rows


def parse_xlsx(raw: bytes) -> tuple[list[str], list[dict]]:
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return [], []
    cols = [str(c) for c in rows[0]]
    out = []
    for r in rows[1:201]:
        out.append({c: v for c, v in zip(cols, r)})
    return cols, out


def parse_pdf(raw: bytes) -> tuple[list[str], list[dict]]:
    # MVP: store raw text as single-column table; full OCR/table-extract later
    text = raw[:4000].decode("latin1", errors="replace")
    return ["text"], [{"text": text[:500]}]


def parse_docx(raw: bytes) -> tuple[list[str], list[dict]]:
    try:
        import docx  # python-docx
    except ImportError as e:
        raise ValueError("DOCX support needs python-docx installed") from e
    doc = docx.Document(io.BytesIO(raw))
    paras = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()][:100]
    rows: list[dict] = [{"text": p[:500]} for p in paras]
    for table in doc.tables[:5]:
        for row in table.rows[:50]:
            cells = [c.text.strip()[:200] for c in row.cells]
            if any(cells):
                rows.append({"text": " | ".join(cells)[:500]})
    if not rows:
        return ["text"], [{"text": ""}]
    return ["text"], rows[:200]


def parse(filename: str, raw: bytes):
    validate(filename, raw)
    fn = filename.lower()
    if fn.endswith(".csv"):
        return parse_csv(raw)
    if fn.endswith(".json"):
        return parse_json(raw)
    if fn.endswith((".xlsx", ".xlsm", ".xltx")):
        return parse_xlsx(raw)
    if fn.endswith(".pdf"):
        return parse_pdf(raw)
    if fn.endswith(".docx"):
        return parse_docx(raw)
    raise ValueError(f"unsupported type: {filename} (supported: {', '.join(SUPPORTED)})")
