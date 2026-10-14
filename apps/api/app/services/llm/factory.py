"""LLM provider factory + availability reporting.

Selection is environment-driven so the application is never hard-wired to a
single vendor. When no credential is configured we fall back to the
deterministic client — the product keeps working, explicitly and visibly.
"""
from __future__ import annotations
import threading
from .base import LLMClient
from .deterministic import DeterministicClient
from ...core.config import settings, resolved_key, resolved_base_url

_LOCK = threading.Lock()
_CLIENT: LLMClient | None = None
_CACHE_KEY: tuple = ()


def build_client() -> LLMClient:
    """Return the configured client, or the deterministic fallback."""
    global _CLIENT, _CACHE_KEY
    key = (settings.LLM_PROVIDER, settings.LLM_MODEL,
           bool(resolved_key()), resolved_base_url())
    with _LOCK:
        if _CLIENT is not None and _CACHE_KEY == key:
            return _CLIENT
        provider = (settings.LLM_PROVIDER or "none").strip().lower()
        model = settings.LLM_MODEL
        api_key = resolved_key()
        client: LLMClient | None = None
        if provider in ("gemini", "google", "vertex") and api_key:
            from .gemini import GeminiClient
            client = GeminiClient(model, api_key=api_key, vertexai=(provider == "vertex"))
            if not getattr(client, "available", False):
                client = None
        elif provider == "openai" and api_key:
            from .openai_compat import OpenAICompatClient
            client = OpenAICompatClient(model, api_key=api_key, base_url=resolved_base_url())
            if not getattr(client, "available", False):
                client = None
        if client is None:
            client = DeterministicClient()
        _CLIENT, _CACHE_KEY = client, key
        return client


def reset_client() -> None:
    """Drop the cached client (used by tests and by credential rotation)."""
    global _CLIENT, _CACHE_KEY
    with _LOCK:
        _CLIENT, _CACHE_KEY = None, ()


def status() -> dict:
    """Human- and machine-readable AI status for /ai/status and /health."""
    client = build_client()
    return {
        "provider": client.name,
        "model": client.model,
        "configured_provider": settings.LLM_PROVIDER,
        "configured_model": settings.LLM_MODEL,
        "credential_present": bool(resolved_key()),
        "live": client.name != "deterministic",
        "deterministic_fallback": client.name == "deterministic",
        "note": ("Live LLM not configured or unavailable — deterministic engine "
                 "answers from graph tools only." if client.name == "deterministic"
                 else f"Live provider '{client.name}' using model '{client.model}'."),
    }


def list_models() -> list[str]:
    return build_client().list_models()
