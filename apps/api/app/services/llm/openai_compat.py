"""OpenAI-compatible provider (also serves local/self-hosted gateways).

Included so the product is not hard-wired to one vendor; the default
configuration is Gemini/Gemma.
"""
from __future__ import annotations
import json
from .base import LLMClient, LLMResponse, ToolCall, ToolSpec


class OpenAICompatClient(LLMClient):
    name = "openai"

    def __init__(self, model: str, api_key: str = "", base_url: str = ""):
        super().__init__(model)
        self._api_key = api_key
        self._base_url = base_url or "https://api.openai.com/v1"
        self._init_error = ""
        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=api_key or "not-set", base_url=self._base_url)
        except Exception as e:
            self._init_error = f"{type(e).__name__}: {e}"
            self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def list_models(self) -> list[str]:
        if not self._client:
            return []
        try:
            return sorted(m.id for m in self._client.models.list())
        except Exception as e:
            self._init_error = f"{type(e).__name__}: {e}"
            return []

    def generate(self, messages: list[dict], tools: list[ToolSpec],
                 system: str = "") -> LLMResponse:
        if not self._client:
            return LLMResponse(provider=self.name, model=self.model,
                               error=self._init_error or "openai client not initialised")
        payload = list(messages)
        if system:
            payload = [{"role": "system", "content": system}] + payload
        oai_tools = [{
            "type": "function",
            "function": {"name": t.name, "description": t.description,
                         "parameters": t.parameters},
        } for t in tools]
        try:
            resp = self._client.chat.completions.create(
                model=self.model, messages=payload,
                tools=oai_tools or None, temperature=0.0)
        except Exception as e:
            return LLMResponse(provider=self.name, model=self.model,
                               error=f"{type(e).__name__}: {e}")
        msg = resp.choices[0].message
        calls = []
        for tc in (getattr(msg, "tool_calls", None) or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            calls.append(ToolCall(name=tc.function.name, args=args, id=tc.id or ""))
        return LLMResponse(text=(msg.content or "").strip(), tool_calls=calls,
                           provider=self.name, model=self.model,
                           finish_reason=str(resp.choices[0].finish_reason or ""),
                           usage={"input_tokens": getattr(resp.usage, "prompt_tokens", None),
                                  "output_tokens": getattr(resp.usage, "completion_tokens", None)})
