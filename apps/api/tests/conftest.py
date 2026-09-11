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

from workflow_core.execution import N8nClient  # noqa: E402

from workflowguard_api.db.session import Base, get_db  # noqa: E402
from workflowguard_api.main import create_app  # noqa: E402


def pytest_collection_modifyitems(config, items):
    """Skip tests that need a live execution engine.

    Since the simulator was removed, running a workflow means running it in n8n. These tests
    skip unless one is configured and answering, so the default suite stays offline.
    """
    base_url = os.environ.get("WORKFLOWGUARD_TEST_N8N_BASE_URL")
    reason = None
    if not base_url:
        reason = "WORKFLOWGUARD_TEST_N8N_BASE_URL is not set; no execution engine to run against"
    elif not N8nClient(base_url).health():
        reason = f"no n8n answering at {base_url}"
    if reason is None:
        return
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


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
