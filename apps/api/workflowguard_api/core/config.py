from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "WorkflowGuard API"
    environment: str = "development"
    api_prefix: str = "/api"
    database_url: str = Field(
        default="postgresql+psycopg://workflowguard:workflowguard@localhost:5432/workflowguard"
    )
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    max_upload_bytes: int = 5 * 1024 * 1024
    ai_provider: str = "none"
    ai_api_key: str | None = None
    ai_model: str = "gpt-4o-mini"
    ai_timeout_seconds: float = 20.0

    model_config = SettingsConfigDict(env_file=".env", env_prefix="WORKFLOWGUARD_", extra="ignore")

    @property
    def sqlalchemy_database_url(self) -> str:
        """Return a SQLAlchemy URL that always uses the installed psycopg driver."""
        parsed = urlsplit(self.database_url)
        if parsed.scheme == "postgres":
            return urlunsplit(parsed._replace(scheme="postgresql+psycopg"))
        if parsed.scheme == "postgresql":
            return urlunsplit(parsed._replace(scheme="postgresql+psycopg"))
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
