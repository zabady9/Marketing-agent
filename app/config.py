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

    # Chat turn: deepagents-based loop (True) or the hand-rolled tool loop.
    deepagents_enabled: bool = False
    chat_model_call_limit: int = 8

    # Analysis engine (app.analysis) — steps that don't depend on each other
    # run concurrently, at most this many at once (per process). Searches are
    # capped separately by app.tools.web_search's semaphore.
    analysis_step_concurrency: int = 3
    # Upper bound on steps in one plan; "comprehensive" requests use the max.
    analysis_max_steps: int = 12
    analysis_max_steps_comprehensive: int = 16
    # Model calls a single step may spend on tool use (search / calculator)
    # before it must write its blocks.
    analysis_step_tool_rounds: int = 4

    # Artifact generation (DOCX/PPTX/PDF via MCP) rollout — off by default,
    # like deepagents_enabled, since it depends on three sibling Docker
    # services (see docker-compose.yml) that a given environment may not
    # have running yet.
    mcp_artifacts_enabled: bool = True
    artifact_storage_dir: str = "./generated_artifacts"
    presenton_url: str = "http://presenton:80"
    presenton_api_key: str = ""
    # Presenton's bootstrap admin — lets the backend mint a fresh API key when
    # Presenton restarts and forgets the old one (see app.services.presenton_auth).
    presenton_admin_username: str = "admin"
    presenton_admin_password: str = ""
    mcp_office_docs_url: str = "http://mcp-office-docs:8958"
    mcp_office_docs_api_key: str = ""
    mcp_pdf_url: str = "http://mcp-pdf:3010"
    # Office-docs/Presenton's "LOCAL" storage strategy writes generated files
    # to their own container's disk, not into the MCP response body — this is
    # a Docker volume mounted into both that container and this backend's
    # container at the same path, so a returned filename can be read straight
    # off disk. See docker-compose.yml.
    mcp_shared_output_dir: str = "/shared_artifacts"

    # User file attachments in chat. "local" streams uploads through this
    # backend onto upload_local_dir (dev); "gcs" has the browser PUT straight
    # to upload_bucket via a signed URL (production — Cloud Run caps request
    # bodies at 32MB, far below max_upload_bytes).
    upload_storage: str = "local"
    upload_bucket: str = "marketing-agent-uploads"
    upload_local_dir: str = "./uploads"
    max_upload_bytes: int = 2 * 1024**3
    # Cap on text pulled out of DOCX/XLSX/PPTX/CSV/code attachments before
    # it's replayed into every later turn's prompt.
    max_extracted_chars: int = 200_000

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
