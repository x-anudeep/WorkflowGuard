from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "WorkflowGuard API"
    environment: str = "development"
    api_prefix: str = "/api"
    # WORKFLOWGUARD_DATABASE_URL wins, but a bare DATABASE_URL is accepted as a
    # fallback because that is what managed Postgres add-ons inject -- the Neon
    # integration on Vercel sets it, and copying the value into a second, prefixed
    # variable would only create something to drift when credentials rotate.
    # AliasChoices is needed because env_prefix does not apply to explicit aliases,
    # which is precisely what lets the unprefixed name be read here and nowhere else.
    database_url: str = Field(
        default="postgresql+psycopg://workflowguard:workflowguard@localhost:5432/workflowguard",
        validation_alias=AliasChoices("WORKFLOWGUARD_DATABASE_URL", "DATABASE_URL"),
    )
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    max_upload_bytes: int = 5 * 1024 * 1024
    ai_provider: str = "none"
    ai_api_key: str | None = None
    ai_model: str = "gpt-4o-mini"
    ai_timeout_seconds: float = 20.0
    n8n_base_url: str = "http://n8n:5678"
    n8n_api_key: str | None = None
    n8n_run_timeout_seconds: float = 60.0
    n8n_poll_interval_seconds: float = 0.25
    #: Where emitted workflows send their integration calls. n8n must be able to reach this
    #: host, so in docker-compose it is the API's service name rather than localhost.
    mock_base_url: str = "http://api:8000/mock"
    fuzz_max_cases: int = 60
    fuzz_default_seed: int = 1337

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
