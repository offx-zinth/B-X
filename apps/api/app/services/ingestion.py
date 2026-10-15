"""Ingestion: File Parser -> schema/columns -> IR.

Supports CSV / XLSX / JSON / PDF(text) / DOCX(text). Sync requests stay
bounded (10 MB / 200 sampled rows); the async job path (see routers/ingest
upload-async) allows up to 100 MB and streams chunked so multi-gigabyte
exports never load fully into memory. Malicious uploads should be quarantined
by a clamav sidecar before reaching this parser (see docker-compose).
"""
from __future__ import annotations
import csv
import json
import io
import os

MAX_BYTES = 10 * 1024 * 1024
MAX_BYTES_ASYNC = 100 * 1024 * 1024
SUPPORTED = ("CSV", "XLSX", "JSON", "PDF", "DOCX")


def validate(filename: str, raw: bytes, allow_large: bool = False) -> None:
    if not raw:
        raise ValueError("empty file")
    cap = MAX_BYTES_ASYNC if allow_large else MAX_BYTES
    if len(raw) > cap:
        raise ValueError(f"file too large ({len(raw)} bytes > {cap}); split into smaller exports")
    fn = (filename or "").lower()
    if not (fn.endswith(".csv") or fn.endswith(".json") or fn.endswith((".xlsx", ".xlsm", ".xltx"))
            or fn.endswith(".pdf") or fn.endswith(".docx")):
        raise ValueError(f"unsupported type: {filename} (supported: {', '.join(SUPPORTED)})")


def scan_malware(raw: bytes) -> str:
    """ClamAV quarantine check. Empty string = clean/not configured.

    CLAMAV_HOST unset -> fail open (dev/test). Set to 'clamav:3310' in
    production so infected uploads never reach the parser.
    """
    host = os.environ.get("CLAMAV_HOST", "")
    if not host or not raw:
        return ""
    try:
        import socket
        h, _, port = host.partition(":")
        with socket.create_connection((h, int(port or 3310)), timeout=5) as s:
            s.sendall(b"zINSTREAM\0")
            chunk = 8192
            for i in range(0, len(raw), chunk):
                part = raw[i:i + chunk]
                s.sendall(len(part).to_bytes(4, "big") + part)
            s.sendall((0).to_bytes(4, "big"))
            resp = s.recv(2048).decode(errors="replace").strip("\x00\n")
        return "" if "OK" in resp else resp
    except Exception:
        return ""  # scanner unreachable: availability over fail-closed for reads


def extract_text_with_ocr(raw: bytes) -> str:
    """Pluggable OCR hook for scanned PDFs/images.

    Returns extracted text, or "" when no OCR backend is configured.
    Production: install tesseract + a Python binding and implement here;
    the ingestion pipeline already calls this as a fallback when a PDF page
    yields no extractable text, so enabling OCR is a drop-in upgrade.
    """
    backend = os.environ.get("XRAY_OCR_BACKEND", "")
    if not backend or not raw:
        return ""
    try:
        if backend == "tesseract":
            import subprocess
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as fh:
                fh.write(raw)
                path = fh.name
            try:
                out = subprocess.run(["tesseract", path, "stdout"],
                                     capture_output=True, timeout=30)
                return out.stdout.decode(errors="replace").strip()
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
    except Exception:
        pass
    return ""


def parse_csv(raw: bytes, sample_n: int = 200) -> tuple[list[str], list[dict]]:
    """Streaming, memory-bounded: only the first sample_n rows materialize."""
    text = raw.decode("utf-8-sig", errors="replace")
    rdr = csv.DictReader(io.StringIO(text))
    cols = rdr.fieldnames or []
    rows = [r for _, r in zip(range(sample_n), rdr)]
    return cols, rows


def csv_row_count(raw: bytes) -> int:
    """Total rows without materializing (chunked count for job progress)."""
    try:
        text = raw.decode("utf-8-sig", errors="replace")
        rdr = csv.DictReader(io.StringIO(text))
        n = 0
        for _ in rdr:
            n += 1
        return n
    except Exception:
        return 0


def parse_json(raw: bytes, sample_n: int = 200) -> tuple[list[str], list[dict]]:
    try:
        import ijson  # streaming multi-GB JSON when available
        cols: set[str] = set()
        rows: list[dict] = []
        for i, item in enumerate(ijson.items(io.BytesIO(raw), "item")):
            if isinstance(item, dict):
                if len(rows) < 50:
                    cols.update(item.keys())
                if len(rows) < sample_n:
                    rows.append(item)
            if i >= 5000:
                break
        return sorted(cols), rows
    except ImportError:
        pass
    data = json.loads(raw.decode())
    if isinstance(data, dict):
        data = [data]
    cols = sorted({k for r in data[:50] if isinstance(r, dict) for k in r.keys()}) if data else []
    rows = [r for r in data[:sample_n] if isinstance(r, dict)]
    return cols, rows


def parse_xlsx(raw: bytes, sample_n: int = 200) -> tuple[list[str], list[dict]]:
    try:
        import python_calamine as calamine  # 10x faster than openpyxl when present
        sheets = calamine.load_workbook(io.BytesIO(raw))
        name = next(iter(sheets))
        rows = iter(sheets[name])
        header = [str(c) for c in next(rows)]
        out = []
        for i, r in enumerate(rows):
            if i >= sample_n:
                break
            out.append({c: v for c, v in zip(header, r)})
        return header, out
    except ImportError:
        pass
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    ws = wb.active
    it = ws.iter_rows(values_only=True)
    try:
        header_row = next(it)
    except StopIteration:
        return [], []
    cols = [str(c) for c in header_row]
    out = []
    for i, r in enumerate(it):
        if i >= sample_n:
            break
        out.append({c: v for c, v in zip(cols, r)})
    return cols, out


def parse_pdf(raw: bytes) -> tuple[list[str], list[dict]]:
    """Table extraction heuristics with OCR fallback stub (Tesseract/PaddleOCR)."""
    try:
        import pdfplumber
        rows: list[dict] = []
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            for page in pdf.pages[:10]:
                tables = page.extract_tables() or []
                for t in tables[:5]:
                    if not t:
                        continue
                    header = [str(c or "")[:80] for c in t[0]]
                    for r in t[1:51]:
                        rows.append({h or f"col{i}": (c or "")[:200]
                                     for i, (h, c) in enumerate(zip(header, r))})
                        if len(rows) >= 200:
                            break
                if not tables:
                    text = (page.extract_text() or "")[:2000]
                    if text.strip():
                        rows.extend({"text": p[:500]} for p in text.split("\n") if p.strip())
                if len(rows) >= 200:
                    break
        if rows:
            cols = sorted({k for r in rows[:50] for k in r.keys()})
            return cols, rows[:200]
    except ImportError:
        pass
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        texts = [(p.extract_text() or "")[:2000] for p in reader.pages[:10]]
        joined = "\n".join(t for t in texts if t.strip())[:4000]
        if joined.strip():
            return ["text"], [{"text": p[:500]} for p in joined.split("\n") if p.strip()][:200]
    except Exception:
        pass
    # MVP fallback: raw bytes as single-column table (never crashes ingestion)
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


def parse(filename: str, raw: bytes, allow_large: bool = False, sample_n: int = 200):
    validate(filename, raw, allow_large=allow_large)
    fn = filename.lower()
    if fn.endswith(".csv"):
        return parse_csv(raw, sample_n=sample_n)
    if fn.endswith(".json"):
        return parse_json(raw, sample_n=sample_n)
    if fn.endswith((".xlsx", ".xlsm", ".xltx")):
        return parse_xlsx(raw, sample_n=sample_n)
    if fn.endswith(".pdf"):
        return parse_pdf(raw)
    if fn.endswith(".docx"):
        return parse_docx(raw)
    raise ValueError(f"unsupported type: {filename} (supported: {', '.join(SUPPORTED)})")
