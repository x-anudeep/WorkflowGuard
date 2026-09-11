"""Gating the tests that need a real execution engine.

Since the in-process simulator was removed, anything that actually runs a workflow needs a
live n8n. Those tests are marked `integration` and skip unless one is configured and answering,
so the default suite stays offline and fast.

Point them at an instance with:

    WORKFLOWGUARD_TEST_N8N_BASE_URL=http://localhost:5678 \\
    WORKFLOWGUARD_TEST_N8N_API_KEY=... \\
        pytest packages/workflow-core/tests

The mock endpoints are served by this process. That is not a convenience: the engine opens and
closes runs against a `MockRegistry` object, and n8n reaches those same runs over HTTP, so the
two have to be the same object. A separately running API would hold a *different* registry, and
every injected failure would silently fail to fire - leaving fuzz verdicts that look like
measurements but are not.
"""

from __future__ import annotations

import json
import os
import threading
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from workflow_core.emitters.n8n import N8nEmitter
from workflow_core.execution import MockRegistry, N8nClient, N8nExecutionEngine

_BASE_URL_ENV = "WORKFLOWGUARD_TEST_N8N_BASE_URL"
_API_KEY_ENV = "WORKFLOWGUARD_TEST_N8N_API_KEY"
_MOCK_URL_ENV = "WORKFLOWGUARD_TEST_MOCK_BASE_URL"


@lru_cache(maxsize=1)
def _reachable(base_url: str) -> bool:
    return N8nClient(base_url).health()


def n8n_skip_reason() -> str | None:
    """Why the engine cannot be used, or None when it can."""
    base_url = os.environ.get(_BASE_URL_ENV)
    if not base_url:
        return f"{_BASE_URL_ENV} is not set; no execution engine to run against"
    if not _reachable(base_url):
        return f"no n8n answering at {base_url}"
    return None


def pytest_collection_modifyitems(config, items):
    """Skip every `integration` test in one place rather than per test."""
    reason = n8n_skip_reason()
    if reason is None:
        return
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


def _handler_for(registry: MockRegistry):
    class Handler(BaseHTTPRequestHandler):
        """The transport the FastAPI router provides in production, minus FastAPI."""

        def _serve(self) -> None:
            parts = [p for p in self.path.split("?")[0].strip("/").split("/") if p]
            if len(parts) < 3 or parts[0] != "mock":
                return self._send(404, {"error": "not a mock endpoint"})
            run_token, node_id = parts[1], parts[2]
            length = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(length).decode() if length else ""
            try:
                body = json.loads(raw) if raw else None
            except ValueError:
                body = raw
            response = registry.respond(
                run_token, node_id, {"method": self.command, "query": {}, "body": body}
            )
            if response is None:
                return self._send(404, {"error": f"no open run {run_token}"})
            if response.delay_seconds:
                threading.Event().wait(response.delay_seconds)
            if response.raw_text is not None:
                return self._send_raw(response.status_code, response.raw_text.encode())
            return self._send(response.status_code, response.body)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _serve

        def _send(self, status: int, body) -> None:
            self._send_raw(status, json.dumps(body).encode())

        def _send_raw(self, status: int, payload: bytes) -> None:
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args) -> None:  # quiet
            pass

    return Handler


@pytest.fixture(scope="session")
def mock_server():
    """A real HTTP surface over one registry, reachable by n8n.

    Session-scoped and on a port the OS picks, so a developer's own API on 8000 is never
    mistaken for this one.
    """
    registry = MockRegistry()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(registry))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield registry, f"http://127.0.0.1:{server.server_address[1]}/mock"
    finally:
        server.shutdown()
        server.server_close()


def _engine(mock_server, *, propagate_failures: bool) -> N8nExecutionEngine:
    registry, mock_base_url = mock_server
    return N8nExecutionEngine(
        N8nClient(os.environ[_BASE_URL_ENV], os.environ.get(_API_KEY_ENV)),
        emitter=N8nEmitter(mock_base_url=os.environ.get(_MOCK_URL_ENV) or mock_base_url),
        mocks=registry,
        propagate_failures=propagate_failures,
    )


@pytest.fixture()
def engine(mock_server) -> N8nExecutionEngine:
    """Strict engine, as stored test runs use."""
    return _engine(mock_server, propagate_failures=False)


@pytest.fixture()
def fuzz_engine(mock_server) -> N8nExecutionEngine:
    """Propagating engine: fuzzing measures behaviour past the point of failure."""
    return _engine(mock_server, propagate_failures=True)
