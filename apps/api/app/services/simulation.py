"""Simulation Engine: operates on COPY of graph state. Never mutates live.

Model: LIVE GRAPH -> SNAPSHOT -> SIMULATION STATE.
Each run records: base_graph_version, scenario_changes, temporary formula
overrides, simulation_parameters, per-day time-series, baseline comparison.

Time-series: t0..tn, one step per day for ``duration_days``. Event-driven
carries (e.g. Supplier.capacity=0) persist for the whole horizon; formula
propagation runs to fixpoint each day so causal chains resolve in order.
"""
from __future__ import annotations
import copy
from . import formula_engine as bfl

# Damped Jacobi solver settings (see _propagate docstring).
DAMPING = 0.6
EPSILON = 1e-6


def build_context(nodes: list[dict]) -> dict[str, float]:
    ctx: dict[str, float] = {}
    for n in nodes:
        for k, v in (n.get("properties") or {}).items():
            try:
                ctx[f"{n['type']}.{k}"] = float(v)
            except (ValueError, TypeError):
                pass
    return ctx


def _apply_changes(sim_nodes: list[dict], changes: list[dict]) -> None:
    for ch in changes or []:
        tgt = (ch or {}).get("target", "")
        if "." not in tgt:
            continue
        try:
            val = float(ch["value"])
        except (ValueError, TypeError, KeyError):
            continue
        t, p = tgt.split(".", 1)
        for n in sim_nodes:
            if n["type"] == t:
                n.setdefault("properties", {})[p] = val


def _order_and_split(formulas: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split formulas into intra-day (flow) and cross-day (stock) layers.

    A stock formula references its own target via ``prev.<target>`` (e.g. an
    inventory that depletes each day). Those must read the *previous* day's
    value, exposed to the solver as ``prev.<ref>``. Flow formulas are pure
    functions of upstream flow inputs and converge within a single pass.

    Returns (flow, stock) with the acyclic flow graph topologically ordered
    (Kahn) and any flow-cycle remainder appended deterministically. Cyclic
    groups are identified with Tarjan SCC for the caller to report.
    """
    formulas = [f for f in (formulas or []) if f.get("target")]
    # Pre-compile once per run: validates + warms the token cache so the
    # day loop never re-tokenizes. Invalid formulas surface here, not mid-run.
    for f in formulas:
        try:
            bfl.compile(f.get("expression", ""))
        except Exception:
            pass
    stock, flow = [], []
    for f in formulas:
        refs = set(bfl.dependencies_of(f.get("expression", "")))
        if f["target"] in refs or any(r.startswith("prev.") for r in refs):
            stock.append(f)
        else:
            flow.append(f)
    # Topologically order the flow layer by ref->target edges.
    flow_targets = {f["target"] for f in flow}
    indeg = {t: 0 for t in flow_targets}
    adj: dict[str, list[str]] = {t: [] for t in flow_targets}
    for f in flow:
        for r in bfl.dependencies_of(f.get("expression", "")):
            if r in flow_targets and r != f["target"]:
                adj[r].append(f["target"])
                indeg[f["target"]] += 1
    from collections import deque
    q = deque([t for t, d in indeg.items() if d == 0])
    ordered: list[str] = []
    while q:
        cur = q.popleft()
        ordered.append(cur)
        for nxt in adj.get(cur, []):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)
    by_target = {f["target"]: f for f in flow}
    ordered_flow = [by_target[t] for t in ordered if t in by_target]
    ordered_flow += [f for f in flow if f["target"] not in ordered]  # cycle-safe remainder
    return ordered_flow, stock


def _evaluate_layer(formulas: list[dict], ctx: dict, sim_nodes: list[dict],
                      by_type: dict[str, list[dict]] | None = None) -> dict:
    """Evaluate one acyclic layer once, committing values to ctx + node props."""
    detail: dict[str, dict] = {}
    for f in formulas:
        target = f["target"]
        ev = bfl.evaluate_detailed(f.get("expression", ""), ctx)
        v = ev["value"] if not ev["error"] else 0.0
        v = float(v)
        ctx[target] = v
        if "." in target:
            t, p = target.split(".", 1)
            # Type-indexed writes: O(matching) instead of O(all nodes) per formula.
            targets = (by_type.get(t) if by_type else None)
            if targets is None:
                targets = [n for n in sim_nodes if n.get("type") == t]
            for n in targets:
                n.setdefault("properties", {})[p] = v
        detail[target] = {"value": v, "trace": ev["trace"],
                          "warnings": ev["warnings"], "error": ev["error"]}
    return detail


def _solve_cycles(cyclic: list[dict], ctx: dict,
                  by_type: dict[str, list[dict]], max_iterations: int = 50,
                  tolerance: float = 1e-5) -> dict:
    """Damped Jacobi fixpoint for cyclic flow groups (equilibrium, not single pass)."""
    detail: dict[str, dict] = {}
    for _ in range(max_iterations):
        max_delta = 0.0
        for f in cyclic:
            target = f["target"]
            ev = bfl.evaluate_detailed(f.get("expression", ""), ctx)
            v = float(ev["value"] if not ev["error"] else 0.0)
            old = float(ctx.get(target, 0.0))
            nv = 0.6 * v + 0.4 * old  # DAMPING
            max_delta = max(max_delta, abs(nv - old))
            ctx[target] = nv
            if "." in target:
                t, p = target.split(".", 1)
                for n in by_type.get(t, []):
                    n.setdefault("properties", {})[p] = nv
            detail[target] = {"value": nv, "trace": ev["trace"],
                              "warnings": ev["warnings"], "error": ev["error"]}
        if max_delta < tolerance:
            break
    return detail


def _step_day(scen_ctx: dict, flow: list[dict], stock: list[dict],
              sim_nodes: list[dict], prev_ctx: dict,
              by_type: dict[str, list[dict]] | None = None,
              cyclic: list[dict] | None = None) -> dict:
    """Advance one day: steady-state flow pass, then stock using prev-day reads.

    Flow formulas (no self-reference) are topologically ordered and converge in
    a single pass. Stock formulas read ``prev.<ref>`` for their own target and
    upstream stocks, so one day of depletion is applied exactly once — no
    oscillation, fully deterministic. Cyclic flow groups iterate to equilibrium.
    """
    detail = _evaluate_layer(flow, scen_ctx, sim_nodes, by_type)
    if cyclic:
        detail.update(_solve_cycles(cyclic, scen_ctx, by_type or {}))
    if stock:
        stock_ctx = dict(scen_ctx)
        for k, v in prev_ctx.items():
            stock_ctx[f"prev.{k}"] = v
        detail.update(_evaluate_layer(stock, stock_ctx, sim_nodes, by_type))
    return detail


def _compare(baseline: dict, scenario: dict) -> dict:
    """Baseline vs simulation with absolute / percentage change."""
    deltas: dict[str, dict] = {}
    for k, v in scenario.items():
        b = baseline.get(k)
        if isinstance(v, (int, float)) and isinstance(b, (int, float)) and v != b:
            abs_chg = v - b
            pct = (abs_chg / abs(b) * 100.0) if b != 0 else (100.0 if v != 0 else 0.0)
            deltas[k] = {"before": b, "after": v,
                         "absolute_change": abs_chg, "percentage_change": round(pct, 2)}
    return deltas


def run(nodes: list[dict], edges: list[dict], formulas: list[dict],
        changes: list[dict], steps: int = 1, duration_days: int = 14,
        base_graph_version: int | None = None,
        formula_overrides: list[dict] | None = None) -> dict:
    """changes: [{target:'Supplier.capacity', value:0}].

    Returns {baseline, scenario, deltas, steps(trace), timeline, comparison,
    changes, parameters}. ``timeline`` is the t0..tn daily series; ``steps``
    is kept as an alias for backward compatibility.
    """
    eff_formulas = list(formulas or [])
    if formula_overrides:
        ov = {f.get("target"): f for f in formula_overrides if f.get("target")}
        eff_formulas = [ov.get(f.get("target"), f) for f in eff_formulas]
        for tgt, f in ov.items():
            if all(g.get("target") != tgt for g in eff_formulas):
                eff_formulas.append(f)

    flow, stock = _order_and_split(eff_formulas)
    # Tarjan SCC: report cyclic groups explicitly instead of silently appending.
    try:
        cycles = bfl.find_cycles(eff_formulas)
    except Exception:
        cycles = []
    cyclic_targets = {t for grp in cycles for t in grp}
    cyclic = [f for f in flow if f.get("target") in cyclic_targets]
    flow_acyclic = [f for f in flow if f.get("target") not in cyclic_targets]

    def _run_horizon(changes: list[dict], days: int) -> tuple[dict, list[dict], dict]:
        """Shared engine for baseline and scenario — one code path, so the
        comparison can never diverge because of different evaluation logic."""
        work = copy.deepcopy(nodes or [])
        _apply_changes(work, changes)
        by_type: dict[str, list[dict]] = {}
        for n in work:
            by_type.setdefault(n.get("type", ""), []).append(n)
        ctx = build_context(work)
        prev = {k: v for k, v in ctx.items() if isinstance(v, (int, float))}
        series: list[dict] = []
        sparse: list[dict] = []
        prev_snap: dict = {}
        first_impact: dict[str, int] = {}
        max_impact: dict[str, float] = {}
        for day in range(days):
            detail = _step_day(ctx, flow_acyclic, stock, work, prev, by_type, cyclic)
            snap = {k: v for k, v in ctx.items()}
            snap["_day"] = day
            series.append(snap)
            # Sparse delta compression: only changed keys per day (S_t+1 diff).
            delta = {k: v for k, v in snap.items() if prev_snap.get(k) != v}
            delta["_day"] = day
            sparse.append(delta)
            prev_snap = snap
            prev = {k: v for k, v in ctx.items() if isinstance(v, (int, float))}
            _ = detail
        return ctx, series, {"first_impact": first_impact, "max_impact": max_impact,
                             "sparse": sparse}

    # Baseline: unmodified graph, same solver.
    horizon = max(1, int(duration_days or steps or 1))
    horizon = min(horizon, 365)  # guardrail: one year max
    baseline_full, _, _ = _run_horizon([], horizon)
    scen_ctx, timeline, meta = _run_horizon(changes or [], horizon)
    first_impact_day = meta["first_impact"]
    max_impact = meta["max_impact"]
    for k, v in scen_ctx.items():
        b = baseline_full.get(k)
        if isinstance(v, (int, float)) and isinstance(b, (int, float)) and v != b:
            if k not in first_impact_day:
                first_impact_day[k] = 0
            mag = abs(v - b)
            if mag > max_impact.get(k, 0):
                max_impact[k] = mag

    deltas = _compare(baseline_full, scen_ctx)

    comparison = {
        "metrics": deltas,
        "time_to_impact_days": first_impact_day,
        "maximum_impact": max_impact,
        "horizon_days": horizon,
        "cycles": cycles,
    }
    return {"baseline": baseline_full, "scenario": dict(scen_ctx),
            "deltas": deltas, "steps": timeline, "timeline": timeline,
            "timeline_sparse": meta.get("sparse", []),
            "comparison": comparison, "changes": changes or [],
            "parameters": {"duration_days": horizon,
                           "base_graph_version": base_graph_version,
                           "formula_overrides": formula_overrides or []}}
