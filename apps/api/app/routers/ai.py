from fastapi import APIRouter, Depends
from pydantic import BaseModel
from ..core.tenant import get_ctx
from ..core.store import insert, list_all
from ..core import audit as auditlog
from ..services import ai_orchestrator as ai
from ..services.ai import agent as ai_agent
from ..services.ai import tools as ai_tools
from ..services import llm as llm

router = APIRouter(prefix="/ai", tags=["ai"])


class Ask(BaseModel):
    question: str
    selected_node_id: str = ""
    use_llm: bool = True


class ToolArgs(BaseModel):
    args: dict = {}


@router.get("/tools")
def tools():
    """Registered AI tools with their JSON schemas."""
    return [{"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in ai_tools.registry()]


@router.get("/status")
def status():
    """Which provider/model is active, and whether it is live or deterministic."""
    return llm.status()


@router.get("/models")
def models():
    """Models exposed by the active provider (empty for the offline client)."""
    return {"provider": llm.status()["provider"], "models": llm.list_models()}


@router.post("/ask")
def ask(b: Ask, ctx: dict = Depends(get_ctx)):
    """Copilot entry point.

    Uses the configured LLM (Gemini/Gemma by default) with real tool calling.
    Deterministic engine results are attached so the UI keeps rendering the
    causal explanation. If no LLM is configured the deterministic path runs —
    the product never depends on the model being present.
    """
    from ..core import ratelimit as _rl
    if b.use_llm and not _rl.allow(ctx.get("tenant_id", "")):
        # Over budget: deterministic fallback cascade instead of a 429.
        return {**_deterministic_answer(b.question, ctx), "degraded": True,
                "rate_limited": True,
                "note": "LLM budget exceeded for this tenant; deterministic answer returned."}
    if not b.use_llm or not b.question.strip():
        return _deterministic_answer(b.question, ctx)

    res = ai_agent.ask(ctx, b.question, selected_node_id=b.selected_node_id)
    auditlog.record(ctx, "ai.ask", "ai:copilot",
                    after={"provider": res["provider"], "tools": res["steps"][:8],
                           "grounded": res["grounding"]["fully_grounded"]})

    # Attach the rich deterministic payload the frontend renders.
    extra = _enrich(b.question, ctx)
    extra.update({"answer": res["answer"], "provider": res["provider"],
                  "model": res["model"], "llm_status": res["llm_status"],
                  "tool_calls": res["tool_calls"], "grounding": res["grounding"],
                  "context": res["context"], "error": res["error"],
                  "degraded": res.get("degraded", False)})
    if res["recovered_error"]:
        extra["recovered_error"] = str(res["recovered_error"])[:200]
    if res["steps"]:
        extra.setdefault("steps", res["steps"])
    return extra


def _deterministic_answer(question: str, ctx: dict) -> dict:
    """Tool-derived answer with no LLM involved (LLM removed => still works)."""
    q = (question or "").lower()
    if "supplier" in q and any(w in q for w in ("lose", "disappear", "largest", "fail", "stop")):
        sups = [n for n in list_all("nodes", ctx) if n["type"].lower() == "supplier"]
        target = max(sups, key=lambda n: float((n.get("properties") or {}).get("capacity", 0))) if sups else None
        if not target:
            return {"answer": "No Supplier nodes yet. Upload supplier data first.",
                    "steps": [], "provider": "deterministic"}
        dep = ai.find_dependencies(ctx, target["id"])
        changes = [{"target": "Supplier.capacity", "value": 0}]
        res = ai.run_simulation(ctx, changes, duration_days=14)
        expl = ai.explain_simulation(ctx, changes, res, subject=target.get("name", "supplier"))
        return {"steps": ["query_graph: largest supplier", "find_dependencies",
                          "run_simulation cap=0", "compare vs baseline"],
                "supplier": target, "impact": dep, "simulation": res,
                "explanation": expl, "answer": ai.narrate(expl),
                "provider": "deterministic", "grounding": {"fully_grounded": True,
                                                            "ungrounded_refs": []}}
    if "bottleneck" in q:
        return {"answer": "Top bottlenecks by dependency fan-out.",
                "provider": "deterministic", **ai.find_bottlenecks(ctx)}
    if "risk" in q:
        return {"answer": "Structural risks from deterministic scan.",
                "provider": "deterministic", **ai.find_risks(ctx)}
    if "optim" in q:
        return {"answer": "Ranked interventions (proposals only).",
                "provider": "deterministic", **ai.optimize(ctx, question)}
    if "formula" in q or "fulfill" in q or "revenue" in q or "backlog" in q or "capacity" in q:
        p = ai.propose_formula(ctx, question)
        saved = insert("formulas", ctx, {**p, "created_by": "ai", "level": "AI_SUGGESTED"})
        auditlog.record(ctx, "ai.propose_formula", f"formula:{saved['id']}", after={"target": saved["target"]})
        return {"answer": "AI GENERATED FORMULA — review [Apply/Edit/Reject].",
                "proposal": saved, "provider": "deterministic"}
    hits = ai.query_graph(ctx, question)
    if not hits["hits"]:
        return {"answer": "That information is unavailable in the current graph.",
                "provider": "deterministic", **hits}
    return {"answer": f"Found {len(hits['hits'])} matching nodes.",
            "provider": "deterministic", **hits}


def _enrich(question: str, ctx: dict) -> dict:
    """Deterministic extras the UI renders (explanation, deltas, impact)."""
    q = (question or "").lower()
    out: dict = {}
    if "supplier" in q and any(w in q for w in ("lose", "disappear", "largest", "fail", "stop")):
        sups = [n for n in list_all("nodes", ctx) if n["type"].lower() == "supplier"]
        if sups:
            target = max(sups, key=lambda n: float((n.get("properties") or {}).get("capacity", 0)))
            changes = [{"target": "Supplier.capacity", "value": 0}]
            res = ai.run_simulation(ctx, changes, duration_days=14)
            out["supplier"] = target
            out["impact"] = ai.find_dependencies(ctx, target["id"])
            out["simulation"] = res
            out["explanation"] = ai.explain_simulation(ctx, changes, res,
                                                       subject=target.get("name", "supplier"))
    if "bottleneck" in q:
        out.update(ai.find_bottlenecks(ctx))
    if "risk" in q:
        out.update(ai.find_risks(ctx))
    if "optim" in q:
        out.update(ai.optimize(ctx, question))
    if "formula" in q or "fulfill" in q or "revenue" in q or "backlog" in q or "capacity" in q:
        if "formula" in q:
            p = ai.propose_formula(ctx, question)
            saved = insert("formulas", ctx, {**p, "created_by": "ai", "level": "AI_SUGGESTED"})
            out["proposal"] = saved
    return out


@router.get("/search/semantic")
def search_semantic(q: str, k: int = 10, ctx: dict = Depends(get_ctx)):
    """Semantic node search: pgvector when available, in-memory fallback.

    Deterministic hash embeddings (no network) rank nodes by cosine distance
    to the query. Content-addressed index refresh keeps repeat queries cheap.
    """
    from ..services import search as sem
    nodes = list_all("nodes", ctx)
    return {"query": q, "hits": sem.search(ctx, q, nodes, k=max(1, min(k, 50)))}


@router.post("/optimize")
def optimize(b: Ask, ctx: dict = Depends(get_ctx)):
    out = ai.optimize(ctx, b.question)
    auditlog.record(ctx, "ai.optimize", "ai:optimize", after={"goal": b.question})
    return out


@router.post("/ask/stream")
def ask_stream(b: Ask, ctx: dict = Depends(get_ctx)):
    """Server-Sent Events: streams reasoning steps, tool calls, answer deltas."""
    from fastapi.responses import StreamingResponse
    import json as _json

    def _gen():
        for ev in ai_agent.ask_stream(ctx, b.question, selected_node_id=b.selected_node_id):
            yield f"data: {_json.dumps(ev, default=str)}\n\n"
    auditlog.record(ctx, "ai.ask.stream", "ai:copilot", after={"question": b.question[:200]})
    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/report")
def report(ctx: dict = Depends(get_ctx)):
    return ai.generate_report(ctx)


@router.post("/tools/{name}")
def call_tool(name: str, b: ToolArgs, ctx: dict = Depends(get_ctx)):
    if name not in ai_tools.tool_names():
        return {"error": f"unknown tool {name}", "tools": ai_tools.tool_names()}
    return ai_tools.invoke(name, b.args, ctx)


@router.get("/forecast-models")
def forecast_models(ctx: dict = Depends(get_ctx)):
    from ..services import forecast as fc
    return {"models": fc.list_models()}
