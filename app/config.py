import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Gemini / LangChain
    google_api_key: str
    reasoning_model: str = "gemini-2.5-pro"
    cheap_model: str = "gemini-2.5-flash"
    max_tokens: int = 8192

    # Search
    tavily_api_key: str

    # LangSmith tracing (optional — enabled when key present)
    langsmith_api_key: str = ""
    langsmith_tracing: bool = False
    langsmith_project: str = "feasibility-study"

    # Database
    database_url: str = "sqlite:///./app.db"

    # App
    app_env: str = "development"
    debug: bool = False
    allowed_origins: str = "http://localhost:5173,http://localhost:3000"

    # Deep Agents rollout — master flag gates whether chat/phase-agents/
    # orchestrator run their deepagents-based implementation or the legacy
    # single-shot-LLM one. Off by default; flip per-environment once each
    # layer's own tests + the cross-layer integration tests pass.
    deepagents_enabled: bool = False
    # Per-layer LLM-call budgets, tuned bottom-up (phase agents first, then
    # orchestrator ~6x that, then chat ~orchestrator's ceiling) since the
    # layers nest — a single shared limit would either starve the innermost
    # layer or make the outermost layer's cap meaningless.
    phase_model_call_limit: int = 6
    orchestrator_model_call_limit: int = 20
    chat_model_call_limit: int = 8

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


def _validate(settings: Settings) -> None:
    missing = []
    if not settings.google_api_key:
        missing.append("GOOGLE_API_KEY")
    if not settings.tavily_api_key:
        missing.append("TAVILY_API_KEY")
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Check your .env file."
        )


def _apply_langsmith_env(settings: Settings) -> None:
    """Propagate LangSmith settings into the process environment.

    pydantic-settings parses .env into this Settings model directly — it
    never touches os.environ. But the langsmith SDK (and every LangChain/
    LangGraph/deepagents tracing hook) reads LANGSMITH_* purely from
    os.environ, not from this app's Settings object. Without this, a
    correctly-filled-in .env silently does nothing: settings.langsmith_tracing
    reads True, but no trace ever reaches LangSmith. Must run before any
    chain/agent is invoked — langsmith caches some of these lookups
    (functools.lru_cache), so setting them any later than app startup risks
    a stale cached miss for the lifetime of the process."""
    if not settings.langsmith_tracing or not settings.langsmith_api_key:
        return
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _validate(_settings)
        _apply_langsmith_env(_settings)
    return _settings
