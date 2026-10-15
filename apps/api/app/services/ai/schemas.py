"""Strict tool JSON Schemas generated from Pydantic (single source of truth)."""
from __future__ import annotations
from pydantic import BaseModel, Field


class QueryGraphArgs(BaseModel):
    q: str = Field(description="search text")


class InspectNodeArgs(BaseModel):
    node_id: str = ""
    node_type: str = ""


class TracePathArgs(BaseModel):
    source: str
    target: str


class GetMetricArgs(BaseModel):
    ref: str = Field(description="e.g. Revenue.total")


class SimChange(BaseModel):
    target: str
    value: float


class ExplainSimArgs(BaseModel):
    changes: list[SimChange]
    duration_days: int = 14


class CreateFormulaArgs(BaseModel):
    goal: str


class ValidateFormulaArgs(BaseModel):
    target: str
    expression: str


class CreateScenarioArgs(BaseModel):
    name: str
    changes: list[SimChange] = []
    duration_days: int = 14


def schema_of(model: type[BaseModel]) -> dict:
    """Pydantic-generated JSON Schema, checked for provider-portable keywords."""
    s = model.model_json_schema()
    defs = s.get("$defs", {})

    def _resolve(node):
        if isinstance(node, dict):
            if "$ref" in node and len(node) == 1:
                ref = node["$ref"]
                name = ref.split("/")[-1]
                if name in defs:
                    return _resolve(defs[name])
                return {"type": "object"}
            return {k: _resolve(v) for k, v in node.items() if k not in ("$defs", "title", "description")}
        if isinstance(node, list):
            return [_resolve(v) for v in node]
        return node

    props = _resolve(s.get("properties", {}))
    return {"type": "object", "properties": props,
            "required": s.get("required", [])}
