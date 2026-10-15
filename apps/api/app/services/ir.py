"""Discovery Engine: raw tables -> Business IR.
MVP heuristics: column classification + entity/relationship detection.
Not random nodes: orders.csv with customer_id/product_id/... -> Customer-places->Order-contains->Product etc.
"""
from __future__ import annotations
import re

ID_RE = re.compile(r"^(.*)_id$", re.I)
# Single source of truth lives in app/core/ontology.py. This mirror keeps the
# discovery engine importable without the API package (tests, offline runs).
PRIMITIVES = ["Entity", "Resource", "Actor", "Process", "Task", "Event", "Transaction",
              "Dependency", "Flow", "State", "Capacity", "Constraint", "Time", "Cost"]
NODE_KINDS = ["Entity", "Resource", "Actor", "Process", "Task", "Event", "Transaction"]

# ---- Canonical property normalization -------------------------------------
# Industry exports name the same business fact differently ("capacity_kg",
# "lead_time_days", "available_kg"). Normalizing them onto canonical slots is
# what lets heterogeneous uploads compile into one executable graph.
_UNIT_SUFFIX = re.compile(
    r"_(kg|kgs|g|gm|tons|tonnes|litres|ltrs|l|pcs|units|unit|per_unit|each|day|days|days?|"
    r"hrs|hours|min|minutes|inr|rs|rupees|usd|dollars|pct|percent|percent_)$", re.I)

# canonical slot -> (accepted name stems, aggregation)
CANONICAL: list[tuple[str, tuple[str, ...], str]] = [
    ("capacity",        ("capacity", "daily_capacity", "max_capacity", "throughput"), "mean"),
    ("lead_time",       ("lead_time", "leadtime", "delivery_time", "cycle_time"), "mean"),
    ("available",       ("available", "available_stock", "on_hand", "stock", "inventory"), "sum"),
    ("required",        ("required", "required_per_unit", "material_required", "requirement"), "mean"),
    ("quantity",        ("quantity", "qty", "units", "volume"), "sum"),
    ("demand",          ("demand", "demand_units", "demand_qty", "ordered"), "sum"),
    ("avg_value",       ("avg_value", "average_value", "unit_price", "price", "rate"), "mean"),
    ("unit_cost",       ("unit_cost", "cost_per_unit", "cost", "cost_price"), "mean"),
    ("fulfilled",       ("fulfilled", "orders_fulfilled", "shipped"), "sum"),
    ("backlog",         ("backlog", "pending", "open_orders"), "sum"),
    ("utilization",     ("utilization", "utilisation", "util"), "mean"),
    ("outstanding",     ("outstanding", "receivable", "pending_payment"), "sum"),
    ("overdue",         ("overdue", "overdue_amount", "delinquent"), "sum"),
]


def canonical_name(col: str) -> str:
    """Strip unit/quantity suffixes: capacity_kg -> capacity, lead_time_days -> lead_time."""
    c = col.strip().lower()
    prev = None
    while prev != c:
        prev = c
        c = _UNIT_SUFFIX.sub("", c)
    return c


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        try:
            return float(s)
        except ValueError:
            return None
    return None


def normalize_measures(columns: list[str], rows: list[dict]) -> dict[str, float]:
    """Aggregate raw columns onto canonical business properties.

    Deterministic: numeric columns only, sum for stock-like slots, mean for
    rate-like slots. Returns {} when nothing numeric can be mapped — values
    are never invented.
    """
    out: dict[str, float] = {}
    for col in columns:
        cname = canonical_name(col)
        slot = None
        agg = None
        for name, stems, a in CANONICAL:
            if cname == name or cname in stems or cname.startswith(name):
                slot, agg = name, a
                break
        if not slot or slot in out:
            continue
        vals = [_num((r or {}).get(col)) for r in rows]
        vals = [v for v in vals if v is not None]
        if not vals:
            continue
        out[slot] = sum(vals) if agg == "sum" else (sum(vals) / len(vals))
    return out


def classify_column(col: str) -> str:
    c = col.lower()
    if ID_RE.match(col): return "reference"
    if any(k in c for k in ("date","time","created","updated")): return "date"
    if any(k in c for k in ("price","cost","amount","revenue","capacity","quantity","qty","available","required")): return "measure"
    if any(k in c for k in ("email","phone","address","location","name")): return "attribute"
    return "attribute"

def _kind_for_type(rtype: str) -> str:
    """General business-type -> core node kind. Domain-agnostic.

    Uses ontology domain maps first (tea shop and factory share the same
    lookup), then generic name heuristics. Unknown vocabularies fall back to
    Entity so unseen businesses stay executable.
    """
    try:
        from ..core.ontology import kind_for as _onto_kind
        mapped = _onto_kind(rtype)
        if mapped != "ENTITY":
            return {"ENTITY": "Entity", "RESOURCE": "Resource", "ACTOR": "Actor",
                    "PROCESS": "Process", "TASK": "Task", "EVENT": "Event",
                    "TRANSACTION": "Transaction"}.get(mapped, "Entity")
    except Exception:
        pass
    low = rtype.lower()
    if any(k in low for k in ("customer", "employee", "supplier", "user", "brewer",
                              "staff", "team", "vendor", "agent", "manager", "operator")):
        return "Actor"
    if any(k in low for k in ("product", "material", "inventory", "machine", "stock",
                              "milk", "sugar", "cup", "ingredient", "equipment", "resource")):
        return "Resource"
    if any(k in low for k in ("order", "payment", "invoice", "sale", "purchase", "transaction")):
        return "Transaction"
    if any(k in low for k in ("brew", "serve", "approv", "task", "ticket", "review", "fulfill")):
        return "Task"
    if any(k in low for k in ("rush", "outage", "delay", "arrival", "event")):
        return "Event"
    if any(k in low for k in ("production", "brewing", "fulfillment", "workflow", "process", "line")):
        return "Process"
    return "Entity"


def detect_ir(table_name: str, columns: list[str], rows: list[dict], source_doc: str) -> dict:
    """Returns versioned {version, nodes:[IRNode], edges:[IREdge], stats}.

    IR records are immutable snapshots: callers persist each result and never
    mutate prior versions (see graph_versions for the compiled counterpart).
    """
    import uuid
    from datetime import datetime, timezone
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    base = table_name.rstrip("s").capitalize() if table_name else "Record"
    # central record entity
    record_type = base
    refs = []
    for col in columns:
        m = ID_RE.match(col)
        if m: refs.append((col, m.group(1).capitalize().rstrip("s") or "Entity"))
    # emit referenced entity types as IR node types (dedup later at compile)
    for _, rtype in refs:
        nodes.setdefault(rtype, {"type": rtype, "examples": [], "kind": _kind_for_type(rtype)})
    nodes.setdefault(record_type, {"type": record_type, "examples": rows[:3], "kind": _kind_for_type(record_type)})
    # relationships: RefType --verb--> RecordType (skip self-loops: a file
    # describing Suppliers is not evidence that a Supplier supplies itself)
    for col, rtype in refs:
        if rtype == record_type: continue
        low = rtype.lower()
        if "customer" in low or "buyer" in low:
            verb = "places"
        elif "supplier" in low or "vendor" in low:
            verb = "supplies"
        elif any(k in low for k in ("employee", "brewer", "staff", "team", "agent")):
            verb = "handled_by"
        elif any(k in low for k in ("product", "material", "ingredient", "milk", "sugar", "cup")):
            verb = "contains"
        else:
            verb = {"customer":"places","product":"contains","employee":"handled_by","supplier":"supplied_by"}.get(low, "relates_to")
        edges.append({"source_type": rtype, "target_type": record_type, "type": verb, "via": col})
    # measures become properties of record, normalized onto canonical slots so
    # heterogeneous exports ("capacity_kg", "lead_time_days") compile into one
    # executable graph instead of opaque columns. Normalization scans every
    # column and only keeps numeric mappable values, so classification gaps
    # (e.g. "lead_time_days") never silently drop a business fact.
    measures = [c for c in columns if classify_column(c) == "measure"]
    normalized = normalize_measures(columns, rows)
    nodes[record_type]["properties"] = normalized
    nodes[record_type]["normalized_measures"] = normalized
    return {"ir_version": 1, "id": str(uuid.uuid4()),
            "source_doc": source_doc, "table": table_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "nodes": list(nodes.values()), "edges": edges, "measures": measures,
            "normalized_measures": normalized,
            "stats": {"columns": len(columns), "refs": len(refs), "sample_rows": len(rows)}}
