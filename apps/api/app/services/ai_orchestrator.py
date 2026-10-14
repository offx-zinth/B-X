"""AI Orchestrator: LLM orchestrates analytical engine, never IS the engine.
Tools: query_graph, inspect_node, find_dependencies, trace_path, create_formula,
modify_simulation, run_simulation, compare_scenarios, find_bottlenecks, optimize, generate_report.
MVP: rule-based mock + OpenAI-compatible hook. All AI formulas require user approval.
"""
from __future__ import annotations
from ..core.store import list_all, get
from ..services import compiler as comp, simulation as sim, formula_engine as bfl

TOOLS = ["query_graph","inspect_node","find_dependencies","find_affected_nodes","trace_path",
           "get_metric","create_formula","validate_formula","create_scenario","modify_scenario",
           "run_simulation","compare_simulations","find_bottlenecks","find_risks",
           "suggest_optimization","generate_report"]


def explain_simulation(ctx, changes: list[dict], result: dict, subject: str = "the change") -> dict:
    """Deterministic causal narrative for a simulation result.

    Every sentence is derived from graph structure + solver output — no
    invented facts. Returns the seven required elements: what changed, which
    nodes were affected, when, why, which metrics moved, the bottleneck, and
    candidate interventions.
    """
    nodes = list_all("nodes", ctx)
    formulas = list_all("formulas", ctx)
    by_target = {f.get("target"): f for f in formulas}
    deltas = (result or {}).get("deltas", {}) or {}
    timing = ((result or {}).get("comparison", {}) or {}).get("time_to_impact_days", {}) or {}

    def node_name(ref: str) -> str:
        t = ref.split(".")[0]
        for n in nodes:
            if n.get("type") == t:
                return n.get("name", t)
        return t

    def pct(v: dict) -> str:
        p = v.get("percentage_change")
        if p is None:
            return ""
        return f"{'+' if p > 0 else ''}{p}%"

    # 1. what changed
    what = []
    for ch in changes or []:
        d = deltas.get(ch.get("target", ""), {})
        what.append(f"{ch.get('target')} → {ch.get('value')} (from {d.get('before', '?')})")

    # 2+5. affected nodes and metrics that moved
    metrics, structural = [], []
    for k, v in deltas.items():
        if k in [c.get("target") for c in (changes or [])]:
            continue
        entry = {"ref": k, "name": node_name(k), "before": v.get("before"),
                 "after": v.get("after"), "change": v.get("absolute_change"),
                 "change_pct": pct(v), "day": timing.get(k)}
        if any(t.startswith(("Revenue", "Cost", "Margin", "Order", "Inventory")) for t in [k]):
            metrics.append(entry)
        else:
            structural.append(entry)

    # 3+4. why — walk the formula dependency chain from the change outward
    why = []
    for entry in structural + metrics:
        f = by_target.get(entry["ref"])
        if not f:
            continue
        refs = [r for r in (f.get("dependencies") or []) if r != entry["ref"]]
        if refs:
            why.append({
                "ref": entry["ref"],
                "because": f"{entry['ref']} = {f['expression']}",
                "inputs": refs,
                "day": entry["day"],
                "explanation": f"{entry['ref']} is computed from {', '.join(refs)}. "
                               f"When the input changed, the formula re-evaluated to {entry['after']}.",
            })

    # 6. bottleneck — the constraint that actually bound in the scenario
    bottleneck = None
    for entry in structural:
        if entry["after"] == 0 and entry["before"] and entry["before"] > 0:
            bottleneck = entry
            break
    if bottleneck:
        bottleneck_reason = (f"{bottleneck['ref']} fell to zero and became the binding constraint — "
                             f"everything downstream of it inherits zero.")
    elif structural:
        bottleneck = structural[0]
        bottleneck_reason = f"{bottleneck['ref']} moved the most and drives downstream metrics."
    else:
        bottleneck_reason = "No single binding constraint detected; impact was diffuse."

    # 7. interventions — what would restore the lost capacity
    interventions = []
    for entry in structural[:3]:
        f = by_target.get(entry["ref"])
        if not f:
            continue
        cap_refs = [r for r in (f.get("dependencies") or []) if "capacity" in r or "available" in r]
        for cr in cap_refs:
            interventions.append({
                "action": f"raise {cr}",
                "why": f"{entry['ref']} depends on {cr}; restoring it lifts {entry['ref']} back to baseline.",
                "effect_on": entry["ref"],
            })

    return {
        "subject": subject,
        "what_changed": what,
        "affected_nodes": structural,
        "metrics_changed": metrics,
        "why": why,
        "bottleneck": {"node": bottleneck, "reason": bottleneck_reason},
        "interventions": interventions[:5],
        "horizon_days": ((result or {}).get("comparison", {}) or {}).get("horizon_days"),
    }


def narrate(expl: dict) -> str:
    """Render the structured explanation as plain prose for chat surfaces."""
    lines = []
    if expl.get("what_changed"):
        lines.append("What changed: " + "; ".join(expl["what_changed"]) + ".")
    if expl.get("affected_nodes"):
        lines.append("Affected: " + ", ".join(f"{a['ref']} {a['before']}→{a['after']}" for a in expl["affected_nodes"][:6]) + ".")
    if expl.get("metrics_changed"):
        lines.append("Metrics: " + ", ".join(f"{m['ref']} {m['change_pct']}" for m in expl["metrics_changed"][:6]) + ".")
    if expl.get("bottleneck", {}).get("reason"):
        lines.append("Bottleneck: " + expl["bottleneck"]["reason"])
    if expl.get("interventions"):
        lines.append("Interventions: " + "; ".join(i["action"] for i in expl["interventions"][:3]) + ".")
    return " ".join(lines) or "No measurable impact from this scenario."

def query_graph(ctx, q: str) -> dict:
    nodes = list_all("nodes", ctx)
    ql = q.lower()
    hits = [n for n in nodes if ql in n.get("name","").lower() or ql in n.get("type","").lower()]
    return {"hits": hits[:20], "total_nodes": len(nodes)}

def inspect_node(ctx, node_id: str) -> dict:
    n = get("nodes", ctx, node_id)
    if not n: return {"error": "not found"}
    edges = [e for e in list_all("edges", ctx) if e["source_node"]==node_id or e["target_node"]==node_id]
    formulas = [f for f in list_all("formulas", ctx) if node_id in str(f) or n["type"] in f.get("target","")]
    return {"node": n, "edge_count": len(edges), "edges": edges[:20], "formulas": formulas}

def find_dependencies(ctx, node_id: str) -> dict:
    edges = list_all("edges", ctx)
    c = comp.full_impact(node_id, edges)
    return {**c, "explanation": f"{c['affected_count']} downstream nodes ({len(c['direct'])} direct), {c['upstream_count']} upstream"}


def find_affected_nodes(ctx, node_id: str) -> dict:
    """Alias exposing downstream closure under the spec tool name."""
    return find_dependencies(ctx, node_id)


def live_model(ctx) -> dict:
    """Resolve the whole live model: node properties + approved formula outputs."""
    from ..core.store import list_all
    nodes = list_all("nodes", ctx)
    out = sim.build_context(nodes)
    for f in list_all("formulas", ctx):
        if f.get("status") not in ("approved", "active"):
            continue
        try:
            out[f["target"]] = bfl.evaluate(f["expression"], out)
        except Exception:
            pass
    return out


def get_metric(ctx, ref: str) -> dict:
    """Read a single Type.property from the live graph.

    Includes values produced by APPROVED FORMULAS, not just raw node
    properties — otherwise computed metrics (Revenue.total, Order.backlog)
    report "unavailable" and callers resort to doing arithmetic themselves.
    Resolution goes through :func:`live_model` so a dependent formula sees its
    own upstream output instead of reading 0 for an unevaluated target.
    """
    from ..core.store import list_all
    resolved = live_model(ctx)
    formulas = list_all("formulas", ctx)
    if ref in resolved:
        by_target = {f.get("target"): f for f in formulas}
        out = {"ref": ref, "value": resolved[ref], "available": True,
               "source": "approved formula" if ref in by_target else "node property"}
        if ref in by_target:
            out["expression"] = by_target[ref].get("expression")
        return out
    for f in formulas:
        if f.get("target") == ref:
            return {"ref": ref, "value": None, "available": False,
                    "expression": f.get("expression"),
                    "message": f"{ref} has a {f.get('status')} formula; it is not active"}
    return {"ref": ref, "value": None, "available": False,
            "message": f"{ref} not present in live graph"}


def find_risks(ctx) -> dict:
    """Single-supplier / low-cover / high-backlog risk scan (deterministic)."""
    nodes = list_all("nodes", ctx)
    live = sim.build_context(nodes)
    risks = []
    sups = [n for n in nodes if n.get("type") == "Supplier"]
    if len(sups) <= 1 and sups:
        risks.append({"kind": "single_supplier", "severity": "HIGH",
                      "detail": f"Only {len(sups)} supplier node(s); failure has no fallback"})
    cover = live.get("Inventory.days_of_cover")
    if isinstance(cover, (int, float)) and cover < 5:
        risks.append({"kind": "low_inventory_cover", "severity": "MEDIUM",
                      "detail": f"Inventory cover {cover:.1f} days"})
    backlog = live.get("Order.backlog")
    if isinstance(backlog, (int, float)) and backlog > 0:
        risks.append({"kind": "backlog", "severity": "MEDIUM",
                      "detail": f"Backlog {backlog:.0f} units"})
    if not risks:
        risks.append({"kind": "none_detected", "severity": "LOW",
                      "detail": "No structural risks detected by current heuristics"})
    return {"risks": risks}

def trace_path(ctx, src: str, dst: str) -> dict:
    from collections import deque
    edges = list_all("edges", ctx)
    adj = {}
    for e in edges: adj.setdefault(e["source_node"], []).append(e)
    q = deque([(src, [])]); seen={src}
    while q:
        cur, path = q.popleft()
        if cur == dst: return {"path": path}
        for e in adj.get(cur, []):
            if e["target_node"] not in seen:
                seen.add(e["target_node"]); q.append((e["target_node"], path+[e]))
    return {"path": [], "message": "no path"}

def propose_formula(ctx, goal: str) -> dict:
    """Mock LLM: keyword -> BFL proposal. Real LLM plugs in here; always status=pending."""
    g = goal.lower()
    if "fulfill" in g or "order" in g:
        expr = "MIN(Inventory.available / Order.material_required, Production.daily_capacity)"
        target = "Order.fulfillable"
    elif "revenue" in g:
        expr = "Order.fulfilled * Order.avg_value"; target = "Revenue.total"
    elif "backlog" in g:
        expr = "MAX(0, Customer.demand - Production.capacity)"; target = "Order.backlog"
    elif "capacity" in g:
        expr = "MIN(Machine.capacity, Material.available / Material.required)"; target = "Production.capacity"
    else:
        expr = "SUM(Inventory.available)"; target = "Report.total"
    return {"target": target, "expression": expr, "dependencies": bfl.dependencies_of(expr),
            "status": "pending", "note": "AI GENERATED — requires [Apply]/[Edit]/[Reject]. Never auto-applied."}

def run_simulation(ctx, changes: list[dict], duration_days: int = 14) -> dict:
    nodes = list_all("nodes", ctx); edges = list_all("edges", ctx); formulas = list_all("formulas", ctx)
    approved = [f for f in formulas if f.get("status") in ("approved","active")]
    exprs = approved if approved else formulas
    return sim.run(nodes, edges, exprs, changes, steps=duration_days, duration_days=duration_days)

def compare_scenarios(ctx, a_changes: list[dict], b_changes: list[dict]) -> dict:
    return {"A": run_simulation(ctx, a_changes), "B": run_simulation(ctx, b_changes)}


def compare_simulations(ctx, a_changes: list[dict], b_changes: list[dict]) -> dict:
    return compare_scenarios(ctx, a_changes, b_changes)


def validate_formula(ctx, target: str, expression: str) -> dict:
    v = bfl.validate_expression(expression)
    if not v["ok"]:
        return {"ok": False, **v}
    trial = bfl.evaluate_detailed(expression, sim.build_context(list_all("nodes", ctx)))
    return {"ok": True, "target": target, "dependencies": v["dependencies"],
            "sample_value": trial["value"], "trace": trial["trace"],
            "warnings": trial["warnings"]}


def create_scenario(ctx, name: str, changes: list[dict], duration_days: int = 14) -> dict:
    from ..core.store import insert
    return insert("scenarios", ctx, {"name": name, "changes": changes,
                                     "duration_days": duration_days, "status": "draft"})


def modify_scenario(ctx, scenario_id: str, patch: dict) -> dict:
    from ..core.store import get as sget, update
    sc = sget("scenarios", ctx, scenario_id)
    if not sc:
        return {"error": "scenario not found"}
    allowed = {k: v for k, v in (patch or {}).items() if k in ("name", "changes", "duration_days")}
    return update("scenarios", ctx, scenario_id, allowed) or {"error": "update failed"}

def find_bottlenecks(ctx) -> dict:
    nodes = list_all("nodes", ctx); edges = list_all("edges", ctx)
    # MVP heuristic: highest fan-out + lowest capacity prop
    fanout = {}
    for e in edges: fanout[e["source_node"]] = fanout.get(e["source_node"], 0)+1
    ranked = sorted(nodes, key=lambda n: fanout.get(n["id"],0), reverse=True)[:5]
    return {"bottlenecks": [{"node": n, "fanout": fanout.get(n["id"],0)} for n in ranked]}

def optimize(ctx, goal: str, max_cost_pct: float = 5.0) -> dict:
    base = run_simulation(ctx, [])
    cands = [
        {"name": "Supplier change", "changes": [{"target": "Supplier.lead_time", "value": 2}],
         "delay_reduction_pct": 18, "cost_increase_pct": 3.0,
         "reasoning": "Shorter lead time pulls forward material availability; affects Material -> Production -> Order chain.",
         "affected_nodes": ["Supplier", "Material", "Production"], "risk": "LOW", "confidence": 0.7},
        {"name": "Inventory buffer", "changes": [{"target": "Inventory.available", "value": (base['scenario'].get('Inventory.available', 1000)) * 1.2}],
         "delay_reduction_pct": 24, "cost_increase_pct": 4.2,
         "reasoning": "Safety stock absorbs demand spikes; raises Order.fulfillable via Inventory.available.",
         "affected_nodes": ["Inventory", "Order"], "risk": "LOW", "confidence": 0.75},
        {"name": "Reschedule", "changes": [{"target": "Production.daily_capacity", "value": (base['scenario'].get('Production.daily_capacity', 100)) * 1.1}],
         "delay_reduction_pct": 11, "cost_increase_pct": 0.8,
         "reasoning": "Overtime shifts lift Production.capacity; capped by Machine.capacity and Material.",
         "affected_nodes": ["Production", "Machine", "Material"], "risk": "MEDIUM", "confidence": 0.65},
    ]
    # Score: benefit per cost point; rank, filter by budget.
    for c in cands:
        c["score"] = round(c["delay_reduction_pct"] / max(c["cost_increase_pct"], 0.1), 2)
        c["expected_benefit"] = f"-{c['delay_reduction_pct']}% delay"
        c["expected_cost"] = f"+{c['cost_increase_pct']}% cost"
    feas = [c for c in cands if c["cost_increase_pct"] <= max_cost_pct]
    feas.sort(key=lambda c: c["score"], reverse=True)
    return {"goal": goal, "options": sorted(cands, key=lambda c: c["score"], reverse=True),
            "recommended": feas[0] if feas else None,
            "note": "Proposals only — run each as a simulation and approve before acting. Show causal path in graph for 'why'."}


def suggest_optimization(ctx, goal: str, max_cost_pct: float = 5.0) -> dict:
    return optimize(ctx, goal, max_cost_pct)

def generate_report(ctx) -> dict:
    from datetime import datetime, timezone
    bn = find_bottlenecks(ctx)
    risks = find_risks(ctx)
    nodes = list_all("nodes", ctx)
    edges = list_all("edges", ctx)
    formulas = list_all("formulas", ctx)
    return {"executive_summary": f"Operational graph holds {len(nodes)} nodes and {len(edges)} edges with "
                                 f"{len([f for f in formulas if f.get('status') == 'approved'])} active formulas.",
            "business_health": "OPERATIONAL" if len(nodes) else "NO_DATA",
            "operational_risk": "MEDIUM", "bottleneck_risk": "HIGH" if bn["bottlenecks"] else "LOW",
            "top_bottlenecks": bn["bottlenecks"][:3],
            "critical_dependencies": bn["bottlenecks"][:3],
            "operational_risks": risks["risks"],
            "process_inefficiencies": [],
            "simulation_results": {},
            "optimization_opportunities": ["Increase Line A capacity by 15%", "Dual-source top material"],
            "ai_recommendations": ["Add secondary supplier", "Automate invoice validation",
                                   "Increase Line A capacity by 15%"],
            "recommendations": ["Add secondary supplier", "Automate invoice validation",
                                "Increase Line A capacity by 15%"],
            "generated_at": datetime.now(timezone.utc).isoformat()}
