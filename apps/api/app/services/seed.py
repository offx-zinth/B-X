"""One-click Acme Manufacturing demo. Idempotent per tenant.

Real backend + real simulation engine: no fake frontend data. Covers the
reference chain Supplier -> Material -> Production -> Product -> Orders ->
Revenue plus Customers / Employees / Inventory / Payments so dependency
propagation, bottleneck detection and the supplier-failure scenario work
end to end.
"""
from __future__ import annotations
from datetime import datetime, timezone
from . import formula_engine as bfl

NODES = [
    ("Supplier", "ABC Metals", {"capacity": 5000, "lead_time": 4, "location": "Chennai", "unit_cost": 120}),
    ("Material", "Steel Rod 8mm", {"available": 5000, "required": 10, "unit_cost": 120}),
    ("Machine", "Press M1", {"capacity": 4000, "utilization": 82}),
    ("Production", "Line A", {"daily_capacity": 400, "shift": "Morning"}),
    ("Product", "Hex Bolt M12", {"avg_value": 120}),
    ("Inventory", "WH1 Chennai", {"available": 20000, "reorder_level": 4000}),
    ("Customer", "Anjali Traders", {"location": "Madurai"}),
    ("Employee", "Ravi Kumar", {"daily_capacity": 120, "role": "Line Operator"}),
    ("Demand", "Daily Demand", {"quantity": 3500}),
    ("Order", "Orders", {"avg_value": 120}),
    ("Revenue", "Revenue", {}),
    ("Cost", "Production Cost", {}),
    ("Margin", "Margin", {}),
    ("Payment", "Receivables", {"outstanding": 45000, "overdue": 8000}),
]

EDGES = [
    ("Supplier", "Material", "supplies"),
    ("Material", "Production", "feeds"),
    ("Machine", "Production", "powers"),
    ("Production", "Product", "produces"),
    ("Inventory", "Order", "stocks"),
    ("Production", "Order", "fulfills"),
    ("Product", "Order", "listed_in"),
    ("Customer", "Order", "places"),
    ("Employee", "Production", "operates"),
    ("Order", "Payment", "settles"),
]

FORMULAS = [
    # Causal chain from spec section 40: the supplier cap is a real binding
    # constraint through material inflow, so capacity moves to 0 when the
    # supplier stops — not only when a machine stops.
    ("Production.capacity", "MIN(Supplier.capacity, Machine.capacity, Material.available / Material.required)"),
    ("Order.fulfillable", "MIN(Production.capacity, Demand.quantity)"),
    ("Order.backlog", "MAX(0, Demand.quantity - Order.fulfillable)"),
    ("Revenue.total", "Order.fulfillable * Order.avg_value"),
    # Stock formula: depletes one day at a time by reading previous day's close.
    ("Inventory.available", "MAX(0, prev.Inventory.available - Order.fulfillable + Order.backlog)"),
    ("Inventory.days_of_cover", "RATE(Inventory.available, Demand.quantity)"),
    ("Cost.production", "Order.fulfillable * Material.unit_cost"),
    ("Margin.total", "Revenue.total - Cost.production"),
]


def _key(t: str, name: str) -> str:
    return f"{t}:{name}"


def seed_demo(ctx: dict, store_insert, store_list, store_update) -> dict:
    """Seed the Acme reference graph. Idempotent and non-destructive.

    If the tenant already uploaded data, the demo graph MERGES into it:
    existing node types are reused (user data is never overwritten) and only
    missing nodes, edges and formulas are added. This is what makes an
    uploaded tenant executable instead of being blocked by a seed guard.
    """
    now = datetime.now(timezone.utc).isoformat()
    existing = store_list("nodes", ctx)
    by_type = {n["type"]: n for n in existing}
    demo_present = any(n.get("source_docs") == ["demo seed"] or "demo seed" in (n.get("source_docs") or [])
                       for n in existing)
    if existing and demo_present and len(existing) >= len(NODES):
        return {"seeded": False, "reason": "demo graph already present",
                "nodes": len(existing), "edges": len(store_list("edges", ctx))}

    ids: dict[str, str] = {}
    created = merged = 0
    for t, name, props in NODES:
        cur = by_type.get(t)
        if cur:
            # Reuse the tenant's own node — never clobber discovered values.
            ids[t] = cur["id"]
            merged += 1
            continue
        n = store_insert("nodes", ctx, {"type": t, "name": name, "properties": dict(props),
            "state": "active", "confidence": 0.95, "level": "CONFIRMED",
            "source_docs": ["demo seed"], "last_observed": now,
            "provenance": [{"source_file": "demo seed", "level": "CONFIRMED",
                             "confidence": 0.95, "last_observed": now}]})
        ids[t] = n["id"]
        by_type[t] = n
        created += 1

    existing_edges = store_list("edges", ctx)
    seen = {(e.get("source_node"), e.get("target_node"), e.get("type")) for e in existing_edges}
    edges_added = 0
    for s, t, typ in EDGES:
        a, b = ids.get(s), ids.get(t)
        if not a or not b or (a, b, typ) in seen:
            continue
        seen.add((a, b, typ))
        store_insert("edges", ctx, {"source_node": a, "target_node": b,
            "type": typ, "properties": {}, "source_docs": ["demo seed"],
            "confidence": 0.95, "level": "CONFIRMED"})
        edges_added += 1

    existing_formulas = {f.get("target") for f in store_list("formulas", ctx)}
    formulas_added = 0
    for target, expr in FORMULAS:
        if target in existing_formulas:
            continue
        store_insert("formulas", ctx, {"target": target, "expression": expr,
            "dependencies": bfl.dependencies_of(expr), "status": "approved",
            "created_by": "seed", "level": "CONFIRMED"})
        formulas_added += 1

    return {"seeded": True, "merged_into_existing": merged, "nodes_created": created,
            "nodes": len(store_list("nodes", ctx)),
            "edges": len(store_list("edges", ctx)), "edges_added": edges_added,
            "formulas": len(store_list("formulas", ctx)), "formulas_added": formulas_added}
