"""Environment-based configuration.

The AI layer is provider-agnostic: no application code imports a vendor SDK
directly. Select a provider and model purely through the environment.
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- storage / graph ---
    DATABASE_URL: str = "postgresql://xray:xray@localhost:5432/xray"
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "xraypass"

    # --- auth ---
    JWT_SECRET: str = "dev-secret-change-me"
    JWT_ALG: str = "HS256"

    # --- frontend / CORS ---
    # Comma-separated origins for production deployments behind a real domain.
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- AI provider abstraction ---
    # LLM_PROVIDER: gemini | openai | none (deterministic offline fallback)
    LLM_PROVIDER: str = "gemini"
    LLM_MODEL: str = "gemma-4-31b-it"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""
    LLM_TIMEOUT: int = 60
    LLM_MAX_TOOL_ROUNDS: int = 6
    # Context budget: how much graph the model may see at once. Keeps the
    # prompt small and grounded instead of dumping the whole graph.
    LLM_MAX_CONTEXT_NODES: int = 60
    LLM_TEMPERATURE: float = 0.0

    # Gemini (used when LLM_PROVIDER=gemini and LLM_API_KEY is unset)
    GEMINI_API_KEY: str = ""
    # Backwards-compatible with the previous OpenAI-only settings.
    OPENAI_BASE_URL: str = ""
    OPENAI_API_KEY: str = ""

    model_config = {"extra": "ignore"}


settings = Settings()


def resolved_key() -> str:
    if settings.LLM_API_KEY:
        return settings.LLM_API_KEY
    if settings.LLM_PROVIDER == "gemini":
        return settings.GEMINI_API_KEY
    return settings.OPENAI_API_KEY


def resolved_base_url() -> str:
    if settings.LLM_BASE_URL:
        return settings.LLM_BASE_URL
    if settings.LLM_PROVIDER == "openai":
        return settings.OPENAI_BASE_URL
    return ""
