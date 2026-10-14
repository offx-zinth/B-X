"""AI tool registry.

Every capability the model has is an explicit, typed tool bound to an audited,
tenant-scoped function. The model cannot invent graph facts because it can
only obtain them by calling these.

Hard rules enforced here:
- tenant-scoped: tools receive the caller's ctx and never widen scope
- read tools are side-effect free
- write tools (create_formula, create_scenario, modify_scenario) are
  NON-DESTRUCTIVE by construction: formulas land as `pending` requiring human
  approval, scenarios land as `draft`
- every invocation is written to the audit log
"""
from __future__ import annotations
from ...core import audit as auditlog
from ...core import roles as RBAC
from ...core.store import scan
from ...services import ai_orchestrator as impl
from ...services.llm.base import ToolSpec

# ---------------------------------------------------------------- registry --

_REGISTRY: dict[str, ToolSpec] = {}


def tool(name: str, description: str, parameters: dict,
         action: str = "graph.read"):
    def deco(fn):
        _REGISTRY[name] = ToolSpec(name=name, description=description,
                                   parameters=parameters, fn=fn)
        fn._xr_action = action  # type: ignore[attr-defined]
        return fn
    return deco


def registry() -> list[ToolSpec]:
    return list(_REGISTRY.values())


# Providers reject some JSON-Schema keywords (Gemini rejects anyOf/oneOf).
# Validate at import time so a bad schema fails loudly in tests rather than as
# a confusing 400 from the provider mid-conversation.
_UNSUPPORTED = ("anyOf", "oneOf", "allOf", "$ref", "not")


def validate_schemas() -> list[str]:
    """Return a list of schema problems (empty when all tool schemas are clean)."""
    problems: list[str] = []

    def walk(spec, node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in _UNSUPPORTED:
                    problems.append(f"{spec.name}: '{k}' at {path or 'root'} is not provider-portable")
                if k == "required" and path and node.get("type") != "object":
                    problems.append(f"{spec.name}: 'required' on non-object at {path}")
                walk(spec, v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(spec, v, f"{path}[{i}]")

    for spec in _REGISTRY.values():
        walk(spec, spec.parameters or {}, "")
    return problems


def tool_names() -> list[str]:
    return list(_REGISTRY.keys())


def invoke(name: str, args: dict, ctx: dict) -> dict:
    """Execute a tool under the caller's authorization, and audit it."""
    spec = _REGISTRY.get(name)
    if spec is None:
        return {"error": f"unknown tool '{name}'", "available": tool_names()}
    args = args or {}
    if not isinstance(args, dict):
        return {"error": "tool arguments must be an object"}
    try:
        result = spec.fn(ctx=ctx, **args)
    except TypeError as e:
        return {"error": f"invalid arguments for {name}: {e}"}
    except Exception as e:  # never leak a traceback to the model
        return {"error": f"{name} failed: {type(e).__name__}: {e}"}
    auditlog.record(ctx, "ai.tool_call", f"ai:{name}",
                    metadata={"args_keys": sorted(args.keys()), "ok": "error" not in result})
    return result


def _user(ctx: dict) -> dict:
    for u in scan("users"):
        if u.get("id") == ctx.get("user_id"):
            return u
    return {"role": "Viewer"}


# ------------------------------------------------------------- read tools --

@tool("query_graph", "Find graph nodes whose type or name matches a query. Use this to locate entities before asking about them.",
      {"type": "object", "properties": {"q": {"type": "string", "description": "search text"}}, "required": ["q"]})
def query_graph(ctx: dict, q: str):
    return impl.query_graph(ctx, q)


@tool("inspect_node", "Get one node with its properties, provenance, edges and related formulas. Provide node_id when known, otherwise node_type.",
      {"type": "object", "properties": {
          "node_id": {"type": "string", "description": "exact node id"},
          "node_type": {"type": "string", "description": "node type when node_id is unknown, e.g. 'Supplier'"}}})
def inspect_node(ctx: dict, node_id: str = "", node_type: str = ""):
    nid = node_id
    if not nid and node_type:
        hits = impl.query_graph(ctx, node_type).get("hits", [])
        if not hits:
            return {"error": f"no node of type '{node_type}' exists in this graph"}
        nid = hits[0]["id"]
    if not nid:
        return {"error": "provide node_id or node_type"}
    return impl.inspect_node(ctx, nid)


@tool("find_dependencies", "Upstream and downstream dependency closure for a node: what it needs and what it affects. Provide node_id when known, otherwise node_type.",
      {"type": "object", "properties": {
          "node_id": {"type": "string"},
          "node_type": {"type": "string", "description": "used when node_id is unknown"}}})
def find_dependencies(ctx: dict, node_id: str = "", node_type: str = ""):
    nid = node_id
    if not nid and node_type:
        hits = impl.query_graph(ctx, node_type).get("hits", [])
        if not hits:
            return {"error": f"no node of type '{node_type}' exists in this graph"}
        nid = hits[0]["id"]
    if not nid:
        return {"error": "provide node_id or node_type"}
    return impl.find_dependencies(ctx, nid)


@tool("find_affected_nodes", "Nodes affected by a change to this node (downstream blast radius).",
      {"type": "object", "properties": {"node_id": {"type": "string"}}})
def find_affected_nodes(ctx: dict, node_id: str):
    return impl.find_affected_nodes(ctx, node_id)


@tool("trace_path", "Shortest causal path between two nodes in the graph.",
      {"type": "object", "properties": {
          "source": {"type": "string"}, "target": {"type": "string"}},
       "required": ["source", "target"]})
def trace_path(ctx: dict, source: str, target: str):
    return impl.trace_path(ctx, source, target)


@tool("get_metric", "Current value of a single Type.property metric in the live graph. Reports 'not available' if the graph has no such reference.",
      {"type": "object", "properties": {"ref": {"type": "string", "description": "e.g. Revenue.total"}},
       "required": ["ref"]})
def get_metric(ctx: dict, ref: str):
    return impl.get_metric(ctx, ref)


@tool("list_metrics", "All Type.property metrics resolvable in the live graph, including values produced by approved formulas.",
      {"type": "object", "properties": {}})
def list_metrics(ctx: dict):
    from ...core.store import list_all
    from ...services import ai_orchestrator as orch
    live = orch.live_model(ctx)
    keys = sorted(live.keys())
    # Values for the first 20 refs, plus every approved-formula output so
    # computed metrics are never hidden by alphabetical truncation.
    formula_targets = {f.get("target") for f in list_all("formulas", ctx)
                       if f.get("status") in ("approved", "active")}
    shown = list(dict.fromkeys(list(keys[:20]) + sorted(t for t in formula_targets if t in live)))
    return {"count": len(keys), "refs": keys[:120],
            "values": {k: live[k] for k in shown}}


@tool("find_bottlenecks", "Rank nodes by dependency fan-out and capacity constraint — structural bottlenecks.",
      {"type": "object", "properties": {}})
def find_bottlenecks(ctx: dict):
    return impl.find_bottlenecks(ctx)


@tool("find_risks", "Deterministic structural risk scan (single supplier, inventory cover, backlog).",
      {"type": "object", "properties": {}})
def find_risks(ctx: dict):
    return impl.find_risks(ctx)


@tool("generate_report", "Full business report: health, bottlenecks, risks, optimization opportunities.",
      {"type": "object", "properties": {}})
def generate_report(ctx: dict):
    return impl.generate_report(ctx)


@tool("explain_simulation", "Run a scenario and return the full causal explanation (what changed, what was affected, when, why, metrics, bottleneck, interventions).",
      {"type": "object", "properties": {
          "changes": {"type": "array", "items": {"type": "object", "properties": {
              "target": {"type": "string"}, "value": {"type": "number"}}, "required": ["target", "value"]}},
          "duration_days": {"type": "integer", "description": "1..365, default 14"}},
       "required": ["changes"]})
def explain_simulation(ctx: dict, changes: list, duration_days: int = 14):
    res = impl.run_simulation(ctx, changes or [], duration_days=int(duration_days or 14))
    expl = impl.explain_simulation(ctx, changes or [], res)
    return {"explanation": expl, "deltas": res.get("deltas", {}),
            "timeline_days": len(res.get("timeline", []))}


# ------------------------------------------------------------ write tools --
# These NEVER mutate production rules. Outputs require explicit human approval.

@tool("create_formula", "Propose a business formula from a natural-language goal. Returns a PENDING proposal that a human must approve before it affects anything.",
      {"type": "object", "properties": {"goal": {"type": "string"}}, "required": ["goal"]},
      action="formula.write")
def create_formula(ctx: dict, goal: str):
    RBAC.require(_user(ctx), "formula.write")
    from ...core.store import insert
    p = impl.propose_formula(ctx, goal)
    saved = insert("formulas", ctx, {**p, "created_by": "ai", "level": "AI_SUGGESTED"})
    return {"proposal": saved, "status": "pending",
            "notice": "Created as PENDING. A human must approve it before it becomes active."}


@tool("validate_formula", "Dry-run a formula against the live graph: dependencies, sample value, trace, warnings. Nothing is persisted.",
      {"type": "object", "properties": {"target": {"type": "string"}, "expression": {"type": "string"}},
       "required": ["target", "expression"]})
def validate_formula(ctx: dict, target: str, expression: str):
    return impl.validate_formula(ctx, target, expression)


@tool("create_scenario", "Create a DRAFT scenario definition. Running it is a separate, explicit step.",
      {"type": "object", "properties": {
          "name": {"type": "string"},
          "changes": {"type": "array", "items": {"type": "object"}},
          "duration_days": {"type": "integer"}},
       "required": ["name"]},
      action="simulation.write")
def create_scenario(ctx: dict, name: str, changes: list = None, duration_days: int = 14):
    RBAC.require(_user(ctx), "simulation.write")
    sc = impl.create_scenario(ctx, name, changes or [], int(duration_days or 14))
    return {"scenario": sc, "status": "draft",
            "notice": "Draft only. Nothing is executed until a human runs it."}


@tool("modify_scenario", "Modify an existing draft scenario definition.",
      {"type": "object", "properties": {
          "scenario_id": {"type": "string"},
          "patch": {"type": "object"}},
       "required": ["scenario_id", "patch"]},
      action="simulation.write")
def modify_scenario(ctx: dict, scenario_id: str, patch: dict):
    RBAC.require(_user(ctx), "simulation.write")
    return impl.modify_scenario(ctx, scenario_id, patch or {})


@tool("run_simulation", "Execute a scenario against a SNAPSHOT of the graph. Live data is never mutated. Returns baseline vs scenario deltas.",
      {"type": "object", "properties": {
          "changes": {"type": "array", "items": {"type": "object", "properties": {
              "target": {"type": "string"}, "value": {"type": "number"}}, "required": ["target", "value"]}},
          "duration_days": {"type": "integer"}},
       "required": ["changes"]},
      action="simulation.write")
def run_simulation(ctx: dict, changes: list, duration_days: int = 14):
    RBAC.require(_user(ctx), "simulation.write")
    res = impl.run_simulation(ctx, changes or [], duration_days=int(duration_days or 14))
    return {"deltas": res.get("deltas", {}), "comparison": res.get("comparison", {}),
            "timeline_days": len(res.get("timeline", []))}


@tool("compare_simulations", "Run two scenarios and return both sets of deltas for side-by-side comparison.",
      {"type": "object", "properties": {
          "a_changes": {"type": "array", "items": {"type": "object"}},
          "b_changes": {"type": "array", "items": {"type": "object"}},
          "duration_days": {"type": "integer"}},
       "required": ["a_changes", "b_changes"]},
      action="simulation.write")
def compare_simulations(ctx: dict, a_changes: list, b_changes: list, duration_days: int = 14):
    RBAC.require(_user(ctx), "simulation.write")
    return impl.compare_simulations(ctx, a_changes or [], b_changes or [])


@tool("suggest_optimization", "Rank candidate interventions by simulated benefit vs cost. Returns PROPOSALS ONLY — never executes anything.",
      {"type": "object", "properties": {
          "goal": {"type": "string"},
          "max_cost_pct": {"type": "number", "description": "max acceptable cost increase %, default 5"}},
       "required": ["goal"]})
def suggest_optimization(ctx: dict, goal: str, max_cost_pct: float = 5.0):
    return impl.suggest_optimization(ctx, goal, float(max_cost_pct or 5.0))
