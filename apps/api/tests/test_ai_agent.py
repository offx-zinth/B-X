"""AI layer: provider abstraction, tool-calling loop, and guardrails.

No network required. A FakeClient stands in for Gemini to prove the agent
loop, grounding, fallbacks and approval gates are correct independent of any
vendor SDK.
"""
import sys
sys.path.insert(0, "apps/api")
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.store import clear
from app.services.llm.base import LLMClient, LLMResponse, ToolCall
from app.services.ai import agent, tools
from app.services import llm as llm_pkg


# --------------------------------------------------------------- fake LLM --

class FakeClient(LLMClient):
    """Scripted tool-calling model. First round calls tools, then answers."""
    name = "fake"

    def __init__(self, model="fake-model", script=None, fail=False):
        super().__init__(model)
        self.script = script or []
        self.fail = fail
        self.rounds = 0
        self.saw_system = False
        self.saw_context = False
        self.tools_offered = []

    def generate(self, messages, tools, system=""):
        self.rounds += 1
        self.saw_system = "source of truth" in (system or "")
        self.tools_offered = [t.name for t in tools]
        joined = " ".join(str(m.get("content", "")) for m in messages)
        self.saw_context = "GRAPH CONTEXT" in joined
        if self.fail:
            return LLMResponse(provider=self.name, model=self.model, error="boom: network down")
        if self.rounds == 1:
            return LLMResponse(tool_calls=[ToolCall(n, a) for n, a in self.script],
                               provider=self.name, model=self.model)
        # answer from whatever tool results are in the transcript
        return LLMResponse(text="Supplier.capacity went 5000.0 -> 0.0, so Production.capacity "
                                "fell to 0.0 because it is MIN(Supplier.capacity, ...).",
                           provider=self.name, model=self.model)


@pytest.fixture()
def seeded():
    clear()
    c = TestClient(app)
    s = c.post("/auth/signup", json={"org": "AI Co", "email": "ai@x.co", "password": "secret123"}).json()
    H = {"Authorization": f"Bearer {s['token']}"}
    c.post("/ingest/seed", headers=H)
    return c, H


def _ctx_from(H):
    from app.core.security import decode_token
    t = decode_token(H["Authorization"].split()[1])
    return {"tenant_id": t["tenant_id"], "user_id": t["sub"], "email": t.get("email", "")}


# ------------------------------------------------------------------ tests --

def test_tool_registry_contracts():
    specs = {t.name: t for t in tools.registry()}
    assert "query_graph" in specs and "run_simulation" in specs and "explain_simulation" in specs
    for spec in specs.values():
        assert spec.description, f"{spec.name} needs a description for the model"
        assert spec.parameters.get("type") == "object"
        assert callable(spec.fn)


def test_deterministic_client_when_no_credential():
    llm_pkg.reset_client()
    st = llm_pkg.status()
    assert st["provider"] in ("deterministic", "gemini", "openai")
    if not st["credential_present"]:
        assert st["deterministic_fallback"] is True
        assert st["live"] is False


def test_agent_uses_tools_and_grounds(monkeypatch, seeded):
    c, H = seeded
    ctx = _ctx_from(H)
    fake = FakeClient(script=[("query_graph", {"q": "Supplier"}),
                              ("explain_simulation", {"changes": [{"target": "Supplier.capacity", "value": 0}],
                                                      "duration_days": 14})])
    monkeypatch.setattr(llm_pkg, "build_client", lambda: fake)
    res = agent.ask(ctx, "what happens if we lose our largest supplier?")
    assert fake.saw_system, "system prompt must enforce graph-as-truth"
    assert fake.saw_context, "bounded graph context must be supplied"
    assert "explain_simulation" in fake.tools_offered, "model must be offered tools"
    assert {t["tool"] for t in res["tool_calls"]} >= {"query_graph", "explain_simulation"}
    # grounded: cited refs came from tool output
    assert res["grounding"]["fully_grounded"] is True
    assert res["provider"] == "fake"


def test_agent_flags_ungrounded_claims(monkeypatch, seeded):
    c, H = seeded
    ctx = _ctx_from(H)

    class Liar(FakeClient):
        def generate(self, messages, tools, system=""):
            self.rounds += 1
            if self.rounds == 1:
                return LLMResponse(tool_calls=[ToolCall("query_graph", {"q": "Supplier"})],
                                   provider=self.name, model=self.model)
            return LLMResponse(text="Revenue.profit_margin is 42% and Widget.frobnicator is high.",
                               provider=self.name, model=self.model)

    monkeypatch.setattr(llm_pkg, "build_client", lambda: Liar())
    res = agent.ask(ctx, "what is our margin?")
    assert res["grounding"]["fully_grounded"] is False
    assert "Revenue.profit_margin" in res["grounding"]["ungrounded_refs"]
    assert "Grounding notice" in res["answer"]


def test_agent_degrades_to_deterministic_on_provider_error(monkeypatch, seeded):
    c, H = seeded
    ctx = _ctx_from(H)
    monkeypatch.setattr(llm_pkg, "build_client", lambda: FakeClient(fail=True))
    res = agent.ask(ctx, "what happens if we lose our largest supplier?")
    # provider failed but we still produce a tool-derived answer, labelled.
    assert res["error"] and "boom" in res["error"]
    assert res["degraded"] is True
    assert "fallback" in res["provider"]
    assert res["answer"]


def test_recovered_transient_error_is_not_reported_as_failure(monkeypatch, seeded):
    """A retry that succeeds must not look like a broken AI to the user."""
    c, H = seeded
    ctx = _ctx_from(H)
    state = {"n": 0}

    class FlakyThenOK(FakeClient):
        def generate(self, messages, tools, system=""):
            state["n"] += 1
            if state["n"] == 1:
                return LLMResponse(provider=self.name, model=self.model, error="500 INTERNAL")
            return LLMResponse(text="Supplier.capacity is 0.0 so Production.capacity is 0.0.",
                               provider=self.name, model=self.model)

    monkeypatch.setattr(llm_pkg, "build_client", lambda: FlakyThenOK())
    monkeypatch.setattr(agent.time, "sleep", lambda s: None)
    res = agent.ask(ctx, "what if the supplier stops?")
    assert res["degraded"] is False
    assert res["error"] is None
    assert res["recovered_error"], "transient failure should still be recorded"


def test_tools_reject_unknown_and_bad_args(seeded):
    c, H = seeded
    ctx = _ctx_from(H)
    assert "unknown tool" in tools.invoke("does_not_exist", {}, ctx)["error"]
    bad = tools.invoke("query_graph", {}, ctx)  # missing required q
    assert "invalid arguments" in bad["error"] or "error" in bad


def test_create_formula_is_pending_not_active(seeded):
    c, H = seeded
    ctx = _ctx_from(H)
    out = tools.invoke("create_formula", {"goal": "calculate revenue"}, ctx)
    assert out["proposal"]["status"] == "pending", "AI formula must never auto-apply"
    assert out["proposal"]["level"] == "AI_SUGGESTED"
    live = c.get("/formulas/", headers=H).json()
    assert all(f["status"] == "pending" for f in live if f.get("created_by") == "ai")


def test_get_metric_reads_formula_computed_values(seeded):
    """Computed metrics must resolve through the engine, not read as 0/unavailable.

    This is what stops the model from doing its own arithmetic.
    """
    c, H = seeded
    ctx = _ctx_from(H)
    for ref, expected in (("Production.capacity", 500.0), ("Order.fulfillable", 500.0),
                          ("Revenue.total", 60000.0), ("Order.backlog", 3000.0)):
        out = tools.invoke("get_metric", {"ref": ref}, ctx)
        assert out["available"] is True, out
        assert out["value"] == expected, f"{ref}: {out}"
        assert out.get("source") == "approved formula"


def test_get_metric_reports_unknown_ref_honestly(seeded):
    c, H = seeded
    ctx = _ctx_from(H)
    out = tools.invoke("get_metric", {"ref": "Nope.does_not_exist"}, ctx)
    assert out["available"] is False
    assert "not present" in out["message"]


def test_list_metrics_exposes_computed_values(seeded):
    c, H = seeded
    ctx = _ctx_from(H)
    out = tools.invoke("list_metrics", {}, ctx)
    assert out["count"] > 0
    assert "Revenue.total" in out["refs"]
    assert out["values"].get("Revenue.total") == 60000.0
    assert out["values"].get("Production.capacity") == 500.0


def test_offline_routing_intents(seeded):
    """Regression: 'what are the risks' must not be routed to get_metric."""
    from app.services.llm.deterministic import DeterministicClient
    names = set(tools.tool_names())
    plan = DeterministicClient()
    assert [n for n, _ in plan._plan("What are the risks?", names)] == ["find_risks"]
    assert [n for n, _ in plan._plan("Which nodes are bottlenecks?", names)] == ["find_bottlenecks"]
    assert [n for n, _ in plan._plan("Give me a business report", names)] == ["generate_report"]
    assert [n for n, _ in plan._plan("reduce delivery delays", names)] == ["suggest_optimization"]
    assert [n for n, _ in plan._plan("What is our current revenue?", names)] == ["get_metric"]


def test_offline_agent_executes_full_plan_then_stops(seeded, monkeypatch):
    """Regression: the offline client must run its whole plan, then stop —
    not abort after the first tool, and not loop forever."""
    from app.services.llm.deterministic import DeterministicClient
    c, H = seeded
    ctx = _ctx_from(H)
    client = DeterministicClient()
    monkeypatch.setattr(llm_pkg, "build_client", lambda: client)
    res = agent.ask(ctx, "What happens if we lose our largest supplier?")
    called = [t["tool"] for t in res["tool_calls"]
              if t["summary"] != "skipped (duplicate call)"]
    assert "explain_simulation" in called, f"full plan must run: {called}"
    assert "find_dependencies" in called
    # and it must terminate rather than repeating the plan each round
    assert len(res["tool_calls"]) == len(called), res["tool_calls"]
    assert "Revenue.total" in res["answer"] or "Bottleneck" in res["answer"], res["answer"]


def test_run_simulation_does_not_mutate_live(seeded):
    c, H = seeded
    ctx = _ctx_from(H)
    before = {n["id"]: dict(n.get("properties", {})) for n in c.get("/graph/nodes", headers=H).json()}
    out = tools.invoke("run_simulation", {"changes": [{"target": "Supplier.capacity", "value": 0}]}, ctx)
    assert "deltas" in out
    after = {n["id"]: dict(n.get("properties", {})) for n in c.get("/graph/nodes", headers=H).json()}
    assert before == after


def test_ask_endpoint_uses_agent_and_keeps_explanation(seeded, monkeypatch):
    c, H = seeded
    fake = FakeClient(script=[("explain_simulation", {"changes": [{"target": "Supplier.capacity", "value": 0}],
                                                  "duration_days": 14})])
    monkeypatch.setattr(llm_pkg, "build_client", lambda: fake)
    r = c.post("/ai/ask", json={"question": "what happens if we lose our largest supplier?"},
               headers=H).json()
    assert r["provider"] == "fake"
    assert "explanation" in r, "UI explanation payload must survive LLM path"
    assert r["explanation"]["bottleneck"]["reason"]


def test_ai_status_endpoint(seeded):
    c, H = seeded
    llm_pkg.reset_client()
    st = c.get("/ai/status").json()
    assert "provider" in st and "model" in st and "live" in st


def test_context_is_bounded(monkeypatch, seeded):
    c, H = seeded
    ctx = _ctx_from(H)
    from app.core.config import settings
    monkeypatch.setattr(settings, "LLM_MAX_CONTEXT_NODES", 3)
    built = agent.build_context(ctx, "supplier capacity")
    assert len(built["relevant_nodes"]) <= 3
    assert built["truncated"] is True


def test_duplicate_tool_calls_are_suppressed(monkeypatch, seeded):
    """A model that repeats the same call must not execute it twice."""
    c, H = seeded
    ctx = _ctx_from(H)

    class Repeater(FakeClient):
        def generate(self, messages, tools, system=""):
            self.rounds += 1
            if self.rounds == 1:
                # same call emitted twice in one turn
                return LLMResponse(tool_calls=[ToolCall("run_simulation",
                                                        {"changes": [{"target": "Supplier.capacity", "value": 0}]}),
                                               ToolCall("run_simulation",
                                                        {"changes": [{"target": "Supplier.capacity", "value": 0}]})],
                                   provider=self.name, model=self.model)
            if self.rounds == 2:
                return LLMResponse(tool_calls=[ToolCall("run_simulation",
                                                        {"changes": [{"target": "Supplier.capacity", "value": 0}]})],
                                   provider=self.name, model=self.model)
            return LLMResponse(text="Done. Supplier.capacity became 0.0.", provider=self.name, model=self.model)

    monkeypatch.setattr(llm_pkg, "build_client", lambda: Repeater())
    res = agent.ask(ctx, "what if the supplier stops?")
    executed = [t for t in res["tool_calls"] if t["summary"] != "skipped (duplicate call)"]
    assert len(executed) == 1, "identical call must execute exactly once"
    assert sum(1 for t in res["tool_calls"] if t["summary"] == "skipped (duplicate call)") >= 1


def test_tool_schemas_are_provider_portable():
    """Gemini rejects anyOf/oneOf; schemas must stay portable across providers."""
    assert tools.validate_schemas() == []


def test_grounding_accepts_refs_from_supplied_context(monkeypatch, seeded):
    """Citing a formula operand from the provided context is not fabrication."""
    c, H = seeded
    ctx = _ctx_from(H)

    class Citer(FakeClient):
        def generate(self, messages, tools, system=""):
            self.rounds += 1
            if self.rounds == 1:
                return LLMResponse(tool_calls=[ToolCall("find_bottlenecks", {})],
                                   provider=self.name, model=self.model)
            return LLMResponse(text="Production.capacity depends on Machine.capacity.",
                               provider=self.name, model=self.model)

    monkeypatch.setattr(llm_pkg, "build_client", lambda: Citer())
    res = agent.ask(ctx, "what limits production?")
    assert res["grounding"]["fully_grounded"] is True, res["grounding"]


def test_grounding_rejects_refs_absent_everywhere(monkeypatch, seeded):
    c, H = seeded
    ctx = _ctx_from(H)

    class Citer(FakeClient):
        def generate(self, messages, tools, system=""):
            self.rounds += 1
            if self.rounds == 1:
                return LLMResponse(tool_calls=[ToolCall("find_bottlenecks", {})],
                                   provider=self.name, model=self.model)
            return LLMResponse(text="Widget.frobnicator is 42.", provider=self.name, model=self.model)

    monkeypatch.setattr(llm_pkg, "build_client", lambda: Citer())
    res = agent.ask(ctx, "what is the frobnicator?")
    assert res["grounding"]["fully_grounded"] is False
    assert "Widget.frobnicator" in res["grounding"]["ungrounded_refs"]


def test_transient_provider_error_retries_then_falls_back(monkeypatch, seeded):
    """429/500 should back off and retry before degrading."""
    c, H = seeded
    ctx = _ctx_from(H)
    attempts = {"n": 0}

    class Flaky(FakeClient):
        def generate(self, messages, tools, system=""):
            attempts["n"] += 1
            return LLMResponse(provider=self.name, model=self.model, error="429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(llm_pkg, "build_client", lambda: Flaky())
    monkeypatch.setattr(agent.time, "sleep", lambda s: None)
    res = agent.ask(ctx, "what happens if we lose our supplier?")
    assert attempts["n"] >= 2, "must retry before giving up"
    assert "fallback" in res["provider"]
    assert res["error"]


def test_answer_is_sanitized(monkeypatch, seeded):
    """Echoed rules / internal deliberation must not reach the user."""
    c, H = seeded
    ctx = _ctx_from(H)

    class Rambler(FakeClient):
        def generate(self, messages, tools, system=""):
            self.rounds += 1
            if self.rounds == 1:
                return LLMResponse(tool_calls=[ToolCall("find_bottlenecks", {})],
                                   provider=self.name, model=self.model)
            return LLMResponse(
                text="The user asked about bottlenecks.\n"
                     "According to the absolute rules, I must use tools.\n"
                     "Revenue.total is 60000.0 because Order.fulfillable is 500.0.",
                provider=self.name, model=self.model)

    monkeypatch.setattr(llm_pkg, "build_client", lambda: Rambler())
    res = agent.ask(ctx, "which nodes are bottlenecks?")
    low = res["answer"].lower()
    assert "the user asked" not in low
    assert "absolute rules" not in low
    assert "Revenue.total is 60000.0" in res["answer"]


def test_offline_planner_reads_metrics_instead_of_proposing_formulas(seeded):
    """"What is our revenue" must READ, not create a formula."""
    c, H = seeded
    _ = _ctx_from(H)
    from app.services.llm.deterministic import DeterministicClient
    from app.services.ai import tools as reg
    names = set(reg.tool_names())
    plan = DeterministicClient()._plan("What is our current revenue and backlog?", names)
    called = [n for n, _ in plan]
    assert "get_metric" in called, plan
    assert "create_formula" not in called, plan
    refs = [a.get("ref") for n, a in plan if n == "get_metric"]
    assert "Revenue.total" in refs and "Order.backlog" in refs
