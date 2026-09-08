"""Which environment variable the database URL is read from, and in what order.

Managed Postgres add-ons inject a bare `DATABASE_URL` -- the Neon integration on Vercel
does -- while every other setting here is read with the `WORKFLOWGUARD_` prefix. Accepting
both avoids copying the connection string into a second variable that would drift the next
time credentials rotate, but the precedence has to hold: an explicitly prefixed value must
never be silently overridden by a generic one, or a deployment could end up pointed at a
database nobody chose.

`Settings` is constructed directly rather than through `get_settings()`, which is
`lru_cache`d and would return whichever instance an earlier test built first.
"""

import pytest

from workflowguard_api.core.config import Settings

PREFIXED = "postgresql://prefixed-host/db"
GENERIC = "postgresql://generic-host/db"


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """Both names start unset so each case controls exactly what is present."""
    monkeypatch.delenv("WORKFLOWGUARD_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)


def _settings() -> Settings:
    """_env_file=None keeps a developer's local .env out of the assertions."""
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_prefixed_variable_is_used(monkeypatch) -> None:
    monkeypatch.setenv("WORKFLOWGUARD_DATABASE_URL", PREFIXED)
    assert _settings().database_url == PREFIXED


def test_bare_database_url_is_accepted(monkeypatch) -> None:
    """What the Neon add-on injects, with no prefixed variable set."""
    monkeypatch.setenv("DATABASE_URL", GENERIC)
    assert _settings().database_url == GENERIC


def test_prefixed_wins_when_both_are_set(monkeypatch) -> None:
    """The explicit choice beats the one an integration set on our behalf."""
    monkeypatch.setenv("WORKFLOWGUARD_DATABASE_URL", PREFIXED)
    monkeypatch.setenv("DATABASE_URL", GENERIC)
    assert _settings().database_url == PREFIXED


def test_falls_back_to_the_local_default() -> None:
    assert "localhost" in _settings().database_url


def test_driver_is_normalised_whichever_variable_supplied_it(monkeypatch) -> None:
    """An add-on hands over a bare postgresql:// URL; psycopg has to be named explicitly."""
    monkeypatch.setenv("DATABASE_URL", GENERIC)
    assert _settings().sqlalchemy_database_url == "postgresql+psycopg://generic-host/db"


def test_query_string_survives_normalisation(monkeypatch) -> None:
    """Hosted Postgres requires SSL, so dropping ?sslmode=require would break the connection."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://host/db?sslmode=require")
    assert _settings().sqlalchemy_database_url.endswith("?sslmode=require")
