"""Sample businesses: one-click executable graphs per vertical.

Every business compiles to the SAME 14-primitive engine (no per-industry
forks). Manufacturing + tea shop are the reference proofs; hospital,
logistics, SaaS and retail follow the identical capacity -> fulfillable ->
backlog -> revenue/cost pattern with domain vocabularies as config.
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


TEA_NODES = [
    # Same 14 primitives as the factory — different business, same engine.
    # MilkSupplier/Brewer=ACTOR, MilkStock=RESOURCE, Brew=TASK, Sale=TRANSACTION.
    ("MilkSupplier", "Morning Milk Co", {"capacity": 200, "lead_time": 1, "unit_cost": 30}),
    ("MilkStock", "Milk Stock", {"available": 200, "required": 1, "unit_cost": 30}),
    ("Brewer", "Chai Brewer", {"capacity": 180, "daily_capacity": 180}),
    ("Brew", "Morning Brew", {"daily_capacity": 180}),
    ("Cup", "Cutting Chai", {"avg_value": 15}),
    ("TeaDemand", "Daily Demand", {"quantity": 150}),
    ("TeaSale", "Tea Sales", {"avg_value": 15}),
    ("TeaRevenue", "Tea Revenue", {}),
    ("TeaCost", "Tea Cost", {}),
]

TEA_EDGES = [
    ("MilkSupplier", "MilkStock", "supplies"),
    ("MilkStock", "Brew", "feeds"),
    ("Brewer", "Brew", "operates"),
    ("Brew", "Cup", "produces"),
    ("Cup", "TeaSale", "listed_in"),
    ("TeaSale", "TeaRevenue", "settles"),
]

TEA_FORMULAS = [
    ("Brew.capacity", "MIN(MilkSupplier.capacity, Brewer.capacity, MilkStock.available / MilkStock.required)"),
    ("TeaSale.fulfillable", "MIN(Brew.capacity, TeaDemand.quantity)"),
    ("TeaSale.backlog", "MAX(0, TeaDemand.quantity - TeaSale.fulfillable)"),
    ("TeaRevenue.total", "TeaSale.fulfillable * TeaSale.avg_value"),
    ("TeaCost.production", "TeaSale.fulfillable * MilkStock.unit_cost"),
]

HOSPITAL_NODES = [
    ("Doctor", "Dr Asha + team", {"capacity": 36, "daily_capacity": 36, "lead_time": 1}),
    ("Nurse", "Nursing pool", {"capacity": 30, "daily_capacity": 30}),
    ("MedicalSupply", "Ward supplies", {"available": 820, "required": 1, "unit_cost": 12}),
    ("PatientDemand", "Daily demand", {"quantity": 28}),
    ("Appointment", "Appointments", {"avg_value": 500}),
    ("HospitalRevenue", "Hospital Revenue", {}),
    ("HospitalCost", "Care Cost", {}),
]

HOSPITAL_EDGES = [
    ("Doctor", "Appointment", "handles"),
    ("Nurse", "Appointment", "supports"),
    ("MedicalSupply", "Appointment", "feeds"),
    ("PatientDemand", "Appointment", "places"),
    ("Appointment", "HospitalRevenue", "settles"),
]

HOSPITAL_FORMULAS = [
    ("Appointment.capacity", "MIN(Doctor.capacity, Nurse.capacity, MedicalSupply.available / MedicalSupply.required)"),
    ("Appointment.fulfillable", "MIN(Appointment.capacity, PatientDemand.quantity)"),
    ("Appointment.backlog", "MAX(0, PatientDemand.quantity - Appointment.fulfillable)"),
    ("HospitalRevenue.total", "Appointment.fulfillable * Appointment.avg_value"),
    ("HospitalCost.production", "Appointment.fulfillable * MedicalSupply.unit_cost"),
]

LOGISTICS_NODES = [
    ("Vehicle", "Fleet", {"capacity": 4000, "available": 4000, "utilization": 68}),
    ("Driver", "Driver pool", {"capacity": 10, "daily_capacity": 10}),
    ("Cargo", "Booked cargo", {"available": 4100, "required": 500}),
    ("ShipmentDemand", "Daily demand", {"quantity": 6}),
    ("Shipment", "Shipments", {"avg_value": 10500, "unit_cost": 4000}),
    ("LogisticsRevenue", "Freight Revenue", {}),
    ("LogisticsCost", "Trip Cost", {}),
]

LOGISTICS_EDGES = [
    ("Vehicle", "Shipment", "powers"),
    ("Driver", "Shipment", "operates"),
    ("Cargo", "Shipment", "feeds"),
    ("ShipmentDemand", "Shipment", "places"),
    ("Shipment", "LogisticsRevenue", "settles"),
]

LOGISTICS_FORMULAS = [
    ("Shipment.capacity", "MIN(Vehicle.capacity / Cargo.required, Driver.capacity, Cargo.available / Cargo.required)"),
    ("Shipment.fulfillable", "MIN(Shipment.capacity, ShipmentDemand.quantity)"),
    ("Shipment.backlog", "MAX(0, ShipmentDemand.quantity - Shipment.fulfillable)"),
    ("LogisticsRevenue.total", "Shipment.fulfillable * Shipment.avg_value"),
    ("LogisticsCost.production", "Shipment.fulfillable * Shipment.unit_cost"),
]

SAAS_NODES = [
    ("Agent", "Support team", {"capacity": 30, "daily_capacity": 30, "unit_cost": 800}),
    ("Automation", "Bot + macros", {"capacity": 25}),
    ("TicketDemand", "Daily tickets", {"quantity": 22}),
    ("Ticket", "Support tickets", {"avg_value": 4000}),
    ("SaaSRevenue", "Protected MRR", {}),
    ("SaaSCost", "Support Cost", {}),
]

SAAS_EDGES = [
    ("Agent", "Ticket", "handles"),
    ("Automation", "Ticket", "powers"),
    ("TicketDemand", "Ticket", "places"),
    ("Ticket", "SaaSRevenue", "settles"),
]

SAAS_FORMULAS = [
    ("Ticket.capacity", "MIN(Agent.capacity, Automation.capacity)"),
    ("Ticket.fulfillable", "MIN(Ticket.capacity, TicketDemand.quantity)"),
    ("Ticket.backlog", "MAX(0, TicketDemand.quantity - Ticket.fulfillable)"),
    ("SaaSRevenue.total", "Ticket.fulfillable * Ticket.avg_value"),
    ("SaaSCost.production", "Ticket.fulfillable * Agent.unit_cost"),
]

RETAIL_NODES = [
    ("Store", "T Nagar + Madurai", {"capacity": 520, "daily_capacity": 520}),
    ("Stock", "Shelf stock", {"available": 1000, "required": 1, "unit_cost": 9}),
    ("RetailDemand", "Daily demand", {"quantity": 300}),
    ("Sale", "Store sales", {"avg_value": 17}),
    ("RetailRevenue", "Retail Revenue", {}),
    ("RetailCost", "COGS", {}),
]

RETAIL_EDGES = [
    ("Store", "Sale", "fulfills"),
    ("Stock", "Sale", "stocks"),
    ("RetailDemand", "Sale", "places"),
    ("Sale", "RetailRevenue", "settles"),
]

RETAIL_FORMULAS = [
    ("Sale.capacity", "MIN(Store.capacity, Stock.available / Stock.required)"),
    ("Sale.fulfillable", "MIN(Sale.capacity, RetailDemand.quantity)"),
    ("Sale.backlog", "MAX(0, RetailDemand.quantity - Sale.fulfillable)"),
    ("RetailRevenue.total", "Sale.fulfillable * Sale.avg_value"),
    ("RetailCost.production", "Sale.fulfillable * Stock.unit_cost"),
]

BUSINESS_SEEDS: dict[str, dict] = {
    "manufacturing": {"label": "Manufacturing", "description": "Supplier → Material → Production → Order → Revenue. Capacity-constrained factory.",
                      "nodes": NODES, "edges": EDGES, "formulas": FORMULAS,
                      "sample_dir": None, "tag": "demo seed"},
    "tea_shop": {"label": "Tea Shop", "description": "Milk → Brew → Sale → Revenue. Micro food stall with perishable stock.",
                 "nodes": TEA_NODES, "edges": TEA_EDGES, "formulas": TEA_FORMULAS,
                 "sample_dir": "tea_shop", "tag": "tea seed"},
    "hospital": {"label": "Hospital", "description": "Doctors + nurses + supplies → appointments → revenue. Staff-capacity clinic.",
                 "nodes": HOSPITAL_NODES, "edges": HOSPITAL_EDGES, "formulas": HOSPITAL_FORMULAS,
                 "sample_dir": "hospital", "tag": "hospital seed"},
    "logistics": {"label": "Logistics", "description": "Vehicles + drivers + cargo → shipments → freight revenue.",
                  "nodes": LOGISTICS_NODES, "edges": LOGISTICS_EDGES, "formulas": LOGISTICS_FORMULAS,
                  "sample_dir": "logistics", "tag": "logistics seed"},
    "saas": {"label": "SaaS Support", "description": "Agents + automation → ticket resolution → protected MRR.",
             "nodes": SAAS_NODES, "edges": SAAS_EDGES, "formulas": SAAS_FORMULAS,
             "sample_dir": "saas", "tag": "saas seed"},
    "retail": {"label": "Retail", "description": "Stores + shelf stock → sales → revenue. Two-store chain.",
               "nodes": RETAIL_NODES, "edges": RETAIL_EDGES, "formulas": RETAIL_FORMULAS,
               "sample_dir": "retail", "tag": "retail seed"},
}


def seed_business(business: str, ctx: dict, store_insert, store_list, store_update=None) -> dict:
    """Generic one-click seed for any registered business. Idempotent merge."""
    key = (business or "").lower()
    if key not in BUSINESS_SEEDS:
        raise ValueError(f"unknown business '{business}'; choose from {sorted(BUSINESS_SEEDS)}")
    spec = BUSINESS_SEEDS[key]
    if key == "manufacturing":
        return seed_demo(ctx, store_insert, store_list, store_update)
    return _seed_graph(ctx, store_insert, store_list, spec["nodes"], spec["edges"],
                       spec["formulas"], spec["tag"])


def _seed_graph(ctx: dict, store_insert, store_list, nodes, edges, formulas, tag: str) -> dict:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    try:
        from ..core.ontology import kind_for
    except Exception:
        def kind_for(t, domain=None):  # type: ignore
            return "ENTITY"
    existing = store_list("nodes", ctx)
    by_type = {n["type"]: n for n in existing}
    ids: dict[str, str] = {}
    created = merged = 0
    for t, name, props in nodes:
        cur = by_type.get(t)
        if cur:
            ids[t] = cur["id"]; merged += 1; continue
        kind_title = kind_for(t).title() if isinstance(kind_for(t), str) else "Entity"
        n = store_insert("nodes", ctx, {"type": t, "name": name,
            "properties": {"kind": kind_title, **dict(props)},
            "state": "active", "confidence": 0.95, "level": "CONFIRMED",
            "source_docs": [tag], "last_observed": now,
            "provenance": [{"source_file": tag, "level": "CONFIRMED",
                             "confidence": 0.95, "last_observed": now}]})
        ids[t] = n["id"]; by_type[t] = n; created += 1
        try:
            from . import graph_mirror as _mirror
            _mirror.mirror_node(ctx.get("tenant_id", ""), n)
        except Exception:
            pass
    existing_edges = store_list("edges", ctx)
    seen = {(e.get("source_node"), e.get("target_node"), e.get("type")) for e in existing_edges}
    edges_added = 0
    for s, t, typ in edges:
        a, b = ids.get(s), ids.get(t)
        if not a or not b or (a, b, typ) in seen:
            continue
        seen.add((a, b, typ))
        rec = store_insert("edges", ctx, {"source_node": a, "target_node": b,
            "type": typ, "properties": {}, "source_docs": [tag],
            "confidence": 0.95, "level": "CONFIRMED"})
        edges_added += 1
        try:
            from . import graph_mirror as _mirror
            _mirror.mirror_edge(ctx.get("tenant_id", ""), rec)
        except Exception:
            pass
    existing_formulas = {f.get("target") for f in store_list("formulas", ctx)}
    formulas_added = 0
    for target, expr in formulas:
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


def seed_tea_shop(ctx: dict, store_insert, store_list, store_update=None) -> dict:
    """Tea-shop reference graph. Same engine as the factory, different business."""
    return _seed_graph(ctx, store_insert, store_list, TEA_NODES, TEA_EDGES, TEA_FORMULAS, "tea seed")


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
    try:
        from ..core.ontology import kind_for as _kf
    except Exception:
        _kf = lambda t, domain=None: "ENTITY"  # type: ignore
    for t, name, props in NODES:
        cur = by_type.get(t)
        if cur:
            # Reuse the tenant's own node — never clobber discovered values.
            ids[t] = cur["id"]
            merged += 1
            continue
        try:
            _kind_title = _kf(t).title()
        except Exception:
            _kind_title = "Entity"
        n = store_insert("nodes", ctx, {"type": t, "name": name,
            "properties": {"kind": _kind_title, **dict(props)},
            "state": "active", "confidence": 0.95, "level": "CONFIRMED",
            "source_docs": ["demo seed"], "last_observed": now,
            "provenance": [{"source_file": "demo seed", "level": "CONFIRMED",
                             "confidence": 0.95, "last_observed": now}]})
        ids[t] = n["id"]
        by_type[t] = n
        created += 1
        try:
            from . import graph_mirror as _mirror
            _mirror.mirror_node(ctx.get("tenant_id", ""), n)
        except Exception:
            pass

    existing_edges = store_list("edges", ctx)
    seen = {(e.get("source_node"), e.get("target_node"), e.get("type")) for e in existing_edges}
    edges_added = 0
    for s, t, typ in EDGES:
        a, b = ids.get(s), ids.get(t)
        if not a or not b or (a, b, typ) in seen:
            continue
        seen.add((a, b, typ))
        rec = store_insert("edges", ctx, {"source_node": a, "target_node": b,
            "type": typ, "properties": {}, "source_docs": ["demo seed"],
            "confidence": 0.95, "level": "CONFIRMED"})
        edges_added += 1
        try:
            from . import graph_mirror as _mirror
            _mirror.mirror_edge(ctx.get("tenant_id", ""), rec)
        except Exception:
            pass

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
