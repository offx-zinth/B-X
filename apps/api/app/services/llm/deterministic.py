"""Deterministic offline provider — the product's floor, not a stub.

Business X-Ray must remain a valid deterministic simulation platform with the
LLM removed. This client never fabricates: it routes the question through the
same audited tools the model would call, and composes an answer from tool
output only. Used when no API key is configured, in tests, and as the
guaranteed fallback if a live provider errors mid-run.
"""
from __future__ import annotations
from .base import LLMClient, LLMResponse, ToolCall, ToolSpec


class DeterministicClient(LLMClient):
    name = "deterministic"

    def __init__(self, model: str = "rules-v1"):
        super().__init__(model)
        self._issued = False

    @property
    def available(self) -> bool:
        return True

    def list_models(self) -> list[str]:
        return [self.model]

    def generate(self, messages: list[dict], tools: list[ToolSpec],
                 system: str = "") -> LLMResponse:
        # Emit the plan exactly once. The agent then composes the final answer
        # from those tool results, so there is nothing left to call.
        if self._issued:
            return LLMResponse(text="", provider=self.name, model=self.model,
                               finish_reason="STOP")
        question = ""
        for m in reversed(messages or []):
            if m.get("role") == "user":
                question = str(m.get("content", ""))
                break
        plan = self._plan(question, {t.name for t in tools or []})
        self._issued = True
        if not plan:
            return LLMResponse(text="", provider=self.name, model=self.model,
                               finish_reason="STOP")
        return LLMResponse(text="", tool_calls=[ToolCall(name=n, args=a) for n, a in plan],
                           provider=self.name, model=self.model, finish_reason="TOOL_CALLS")

    def _plan(self, q: str, available: set[str]) -> list[tuple[str, dict]]:
        ql = q.lower()
        plan: list[tuple[str, dict]] = []

        # Intent checks that must win before the generic "what is X" read,
        # otherwise "what are the risks" is mis-routed to get_metric.
        if "risk" in ql and "find_risks" in available:
            return [("find_risks", {})]
        if "bottleneck" in ql and "find_bottlenecks" in available:
            return [("find_bottlenecks", {})]
        if any(w in ql for w in ("optimiz", "improve", "reduce", "recommend", "best way",
                                 "how would we", "how can we")) \
                and "suggest_optimization" in available:
            return [("suggest_optimization", {"goal": q, "max_cost_pct": 5.0})]
        if "report" in ql and "generate_report" in available:
            return [("generate_report", {})]

        supplier_failure = "supplier" in ql and any(
            w in ql for w in ("lose", "fail", "disappear", "largest", "stop", "goes down", "down"))
        if supplier_failure and {"query_graph", "find_dependencies", "explain_simulation"} <= available:
            return [("query_graph", {"q": "Supplier"}),
                    ("find_dependencies", {"node_type": "Supplier"}),
                    ("explain_simulation", {"changes": [{"target": "Supplier.capacity", "value": 0}],
                                            "duration_days": 14})]

        # "What is / how much is X" is a READ, never a formula proposal.
        asking_value = any(p in ql for p in
                           ("what is", "what are", "how much", "current value", "show me"))
        if asking_value and "get_metric" in available:
            known = ("Revenue.total", "Order.backlog", "Order.fulfillable",
                     "Production.capacity", "Cost.production", "Margin.total",
                     "Inventory.available", "Supplier.capacity")
            refs = [r for r in known
                    if r.lower() in ql
                    or r.split(".")[0].lower() in ql
                    or r.split(".")[1].lower() in ql]
            if refs:
                return [("get_metric", {"ref": r}) for r in refs]

        if any(w in ql for w in ("formula", "fulfill", "backlog", "capacity")) \
                and "create_formula" in available:
            return [("create_formula", {"goal": q})]

        if "query_graph" in available:
            return [("query_graph", {"q": q})]
        return plan
