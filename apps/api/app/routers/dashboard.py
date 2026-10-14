"""Dashboard: operational system state (not a generic BI dashboard).

Shows business state, critical dependencies, bottlenecks, risk hotspots,
recent changes, active simulations, recommended actions, model confidence,
data freshness — all computed deterministically from the graph.
"""
from fastapi import APIRouter, Depends
from ..core.tenant import get_ctx
from ..core.store import list_all
from ..core import versions as ver
from ..services import ai_orchestrator as ai
from ..services import simulation as sim

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/")
def overview(ctx: dict = Depends(get_ctx)):
    nodes = list_all("nodes", ctx)
    edges = list_all("edges", ctx)
    formulas = list_all("formulas", ctx)
    sources = list_all("data_sources", ctx)
    runs = list_all("simulation_runs", ctx)
    bn = ai.find_bottlenecks(ctx)
    risks = ai.find_risks(ctx)
    live = sim.build_context(nodes)
    approved = [f for f in formulas if f.get("status") in ("approved", "active")]
    confs = [n.get("confidence", 0) for n in nodes if isinstance(n.get("confidence"), (int, float))]
    model_conf = round(sum(confs) / len(confs), 3) if confs else 0.0
    fresh = sorted([n.get("last_observed", "") for n in nodes if n.get("last_observed")], reverse=True)
    recent_audit = sorted(list_all("audit_log", ctx), key=lambda r: r.get("timestamp", ""), reverse=True)[:10]
    return {
        "business_state": {"nodes": len(nodes), "edges": len(edges),
                           "active_formulas": len(approved), "pending_formulas": len([f for f in formulas if f.get("status") == "pending"])},
        "live_metrics": {k: live[k] for k in list(live)[:25]},
        "critical_dependencies": bn["bottlenecks"][:5],
        "current_bottlenecks": bn["bottlenecks"][:5],
        "risk_hotspots": risks["risks"],
        "recent_changes": recent_audit,
        "active_simulations": runs[:5],
        "recommended_actions": ai.generate_report(ctx)["recommendations"],
        "model_confidence": model_conf,
        "data_freshness": {"sources": len(sources), "last_observed": fresh[0] if fresh else None,
                           "graph_version": ver.current_version(ctx)},
    }
