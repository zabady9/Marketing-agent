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


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _validate(_settings)
    return _settings
