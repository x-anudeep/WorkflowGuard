from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from workflowguard_api.core.config import get_settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs(database_url: str) -> dict[str, object]:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    # Serverless runs many short-lived instances against one shared pooler, so each
    # instance keeps a deliberately tiny pool and recycles it before the pooler would
    # drop it underneath us. pool_pre_ping still covers connections killed in between.
    #
    # prepare_threshold=None disables psycopg's server-side prepared statements, which
    # a transaction-mode pooler cannot support: it hands each transaction a different
    # backend, so a statement prepared on one is missing on the next. Leaving them on
    # surfaces as intermittent DuplicatePreparedStatement errors rather than a clean
    # failure. Set it back to psycopg's default of 5 if this ever moves off a pooler.
    return {
        "pool_pre_ping": True,
        "pool_size": 2,
        "max_overflow": 0,
        "pool_recycle": 300,
        "pool_timeout": 10,
        "connect_args": {"prepare_threshold": None},
    }


database_url = get_settings().sqlalchemy_database_url
engine = create_engine(database_url, **_engine_kwargs(database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
