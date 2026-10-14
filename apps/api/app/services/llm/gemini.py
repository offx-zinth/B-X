"""Gemini / Gemma provider (Google AI Studio or Vertex AI).

Uses the official `google-genai` SDK. Gemma open-weight models (e.g.
`gemma-4-31b-it`) are served through the same Gemini API surface, so no
separate code path is needed — only the model id changes.

Never imported by application code directly: construct via
:func:`app.services.llm.factory.build_client`.
"""
from __future__ import annotations
from .base import LLMClient, LLMResponse, ToolCall, ToolSpec


def _to_gemini_tools(tools: list[ToolSpec]):
    from google.genai import types
    out = []
    for t in tools:
        decl = types.FunctionDeclaration(
            name=t.name,
            description=t.description,
            parameters=t.parameters,
        )
        out.append(types.Tool(function_declarations=[decl]))
    return out


def _to_gemini_contents(messages: list[dict]):
    """Convert [{'role','content'}] into google.genai Content objects.

    The SDK validates strictly, so plain dicts are rejected; tool results are
    sent back as a user-role turn containing their JSON payload.
    """
    from google.genai import types
    out = []
    for m in messages or []:
        role = m.get("role", "user")
        text = m.get("content", "")
        if not isinstance(text, str):
            text = str(text)
        out.append(types.Content(role="model" if role == "assistant" else "user",
                                 parts=[types.Part(text=text)]))
    return out


class GeminiClient(LLMClient):
    name = "gemini"

    def __init__(self, model: str, api_key: str = "", vertexai: bool = False):
        super().__init__(model)
        self._api_key = api_key
        self._client = None
        self._init_error = ""
        try:
            from google import genai
            if vertexai:
                self._client = genai.Client(vertexai=True)
            else:
                self._client = genai.Client(api_key=api_key)
        except Exception as e:  # missing key / SDK / network
            self._init_error = f"{type(e).__name__}: {e}"

    @property
    def available(self) -> bool:
        return self._client is not None

    def list_models(self) -> list[str]:
        if not self._client:
            return []
        try:
            out = []
            for m in self._client.models.list():
                name = getattr(m, "name", "") or ""
                if name:
                    out.append(name.split("/")[-1])
            return sorted(out)
        except Exception as e:
            self._init_error = f"{type(e).__name__}: {e}"
            return []

    def generate(self, messages: list[dict], tools: list[ToolSpec],
                 system: str = "") -> LLMResponse:
        if not self._client:
            return LLMResponse(provider=self.name, model=self.model,
                               error=self._init_error or "gemini client not initialised")
        try:
            from google.genai import types
            cfg_kwargs = {"temperature": 0.0, "top_p": 0.95}
            if system:
                cfg_kwargs["system_instruction"] = system
            if tools:
                cfg_kwargs["tools"] = _to_gemini_tools(tools)
            config = types.GenerateContentConfig(**cfg_kwargs)
            resp = self._client.models.generate_content(
                model=self.model, contents=_to_gemini_contents(messages), config=config)
        except Exception as e:
            return LLMResponse(provider=self.name, model=self.model,
                               error=f"{type(e).__name__}: {e}")

        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for cand in (getattr(resp, "candidates", None) or []):
            content = getattr(cand, "content", None)
            for part in (getattr(content, "parts", None) or []):
                if getattr(part, "text", None):
                    text_parts.append(part.text)
                fc = getattr(part, "function_call", None)
                if fc and getattr(fc, "name", None):
                    args = getattr(fc, "args", None) or {}
                    if not isinstance(args, dict):
                        args = {}
                    calls.append(ToolCall(name=fc.name, args=dict(args),
                                          id=getattr(fc, "id", "") or ""))
        usage = {}
        um = getattr(resp, "usage_metadata", None)
        if um:
            usage = {"input_tokens": getattr(um, "prompt_token_count", None),
                     "output_tokens": getattr(um, "candidates_token_count", None)}
        finish = ""
        if getattr(resp, "candidates", None):
            finish = str(getattr(resp.candidates[0], "finish_reason", "") or "")
        return LLMResponse(text="".join(text_parts).strip(), tool_calls=calls,
                           provider=self.name, model=self.model,
                           finish_reason=finish, usage=usage)
