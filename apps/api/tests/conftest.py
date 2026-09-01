import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages" / "workflow-core"))
sys.path.insert(0, str(ROOT / "apps" / "api"))
os.environ["WORKFLOWGUARD_DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
# Settings reads a repo-root .env, so a developer with a real provider configured would
# otherwise have the suite make live API calls with their own key. Tests that exercise a
# provider inject a mock one explicitly; the default must be deterministic and offline.
os.environ["WORKFLOWGUARD_AI_PROVIDER"] = "none"
os.environ["WORKFLOWGUARD_AI_API_KEY"] = ""

from workflowguard_api.db.session import Base, get_db  # noqa: E402
from workflowguard_api.main import create_app  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)
