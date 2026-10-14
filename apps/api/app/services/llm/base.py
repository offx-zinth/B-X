"""Provider-agnostic LLM interface.

Application code depends only on these types. Swapping or adding a provider is
a matter of implementing :class:`LLMClient`; no router, tool or agent code
changes. Every response carries the provider + model so answers are auditable
and attributable.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolSpec:
    """A callable the model may invoke. Names are unique per agent run."""
    name: str
    description: str
    parameters: dict           # JSON Schema (draft-07 subset)
    fn: Callable[..., Any] = field(repr=False, default=None)


@dataclass
class ToolCall:
    name: str
    args: dict = field(default_factory=dict)
    id: str = ""


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    finish_reason: str = ""
    usage: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class LLMClient:
    """Interface every provider implements."""

    name = "base"

    def __init__(self, model: str):
        self.model = model

    def generate(self, messages: list[dict], tools: list[ToolSpec],
                 system: str = "") -> LLMResponse:  # pragma: no cover - interface
        raise NotImplementedError

    def list_models(self) -> list[str]:  # pragma: no cover - interface
        return []
