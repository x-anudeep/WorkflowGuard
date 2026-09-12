import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn
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

from workflowguard_api.core.config import get_settings  # noqa: E402
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
def served_client(client: TestClient):
    """The same app, additionally listening on a real port.

    Integration tests need this because n8n calls the `/mock` endpoints back over HTTP during a
    run, and `TestClient` never binds a socket. It has to be *this* app instance, not a fresh
    one: the engine opens runs against the module-level `mock_registry`, so a second process or
    a second app would hold a different registry and every mocked response would 404.
    """
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    config = uvicorn.Config(client.app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 30
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        pytest.fail("the API did not start listening for the integration run")

    settings = get_settings()
    previous = settings.mock_base_url
    settings.mock_base_url = f"http://127.0.0.1:{port}/mock"
    try:
        yield client
    finally:
        settings.mock_base_url = previous
        server.should_exit = True
        thread.join(timeout=10)


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
