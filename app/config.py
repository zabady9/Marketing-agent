import os

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "marketing-agent"
    app_version: str = "0.1.0"
    environment: str = Field(default="development", alias="APP_ENV")
    debug: bool = False
    allowed_origins: list[str] = ["http://localhost:3000", "http://localhost:8001"]

    # Database
    database_url: str = "postgresql+asyncpg://postgres:changeme@db:5432/marketing"

    @field_validator("database_url", mode="before")
    @classmethod
    def ensure_asyncpg_driver(cls, v: str) -> str:
        if v.startswith("postgresql://") or v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql://", 1)
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @property
    def checkpointer_conn_str(self) -> str:
        """psycopg v3 connection string for AsyncPostgresSaver (strips +asyncpg driver suffix)."""
        return self.database_url.replace("+asyncpg", "", 1)

    # Gemini
    google_api_key: SecretStr = Field(default=SecretStr("placeholder"))
    reasoning_model: str = "gemini-2.5-pro"
    cheap_model: str = "gemini-2.5-flash"
    max_tokens: int = 8192

    # LangSmith
    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "marketing-agent"

    # Admin
    admin_api_key: SecretStr = Field(default=SecretStr(""))

    # Postiz
    postiz_api_url: str = "http://postiz:5000"
    postiz_api_key: SecretStr = Field(default=SecretStr("placeholder"))

    # Embeddings (open-source, in-process via sentence-transformers)
    embedding_model: str = "BAAI/bge-base-en-v1.5"
    embedding_dimension: int = 768

    # File uploads (document knowledge base)
    uploads_dir: str = "/app/uploads"


settings = Settings()

if settings.langsmith_tracing:
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    if settings.langsmith_api_key:
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key.get_secret_value()
