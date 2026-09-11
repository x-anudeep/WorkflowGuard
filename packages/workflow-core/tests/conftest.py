"""Gating the tests that need a real execution engine.

Since the in-process simulator was removed, anything that actually runs a workflow needs a
live n8n. Those tests are marked `integration` and skip unless one is configured and answering,
so the default suite stays offline and fast.

Point them at an instance with:

    WORKFLOWGUARD_TEST_N8N_BASE_URL=http://localhost:5678 \\
    WORKFLOWGUARD_TEST_N8N_API_KEY=... \\
    WORKFLOWGUARD_TEST_MOCK_BASE_URL=http://localhost:8000/mock \\
        pytest packages/workflow-core/tests

The mock base URL matters: emitted workflows send their integration calls there, and n8n has to
be able to reach it. Without it, injected failures never fire and a fuzz verdict means nothing.
"""

from __future__ import annotations

import os
from functools import lru_cache

import pytest

from workflow_core.emitters.n8n import N8nEmitter
from workflow_core.execution import N8nClient, N8nExecutionEngine

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


def _engine(*, propagate_failures: bool) -> N8nExecutionEngine:
    return N8nExecutionEngine(
        N8nClient(os.environ[_BASE_URL_ENV], os.environ.get(_API_KEY_ENV)),
        emitter=N8nEmitter(
            mock_base_url=os.environ.get(_MOCK_URL_ENV, "http://localhost:8000/mock")
        ),
        propagate_failures=propagate_failures,
    )


@pytest.fixture()
def engine() -> N8nExecutionEngine:
    """Strict engine, as stored test runs use."""
    return _engine(propagate_failures=False)


@pytest.fixture()
def fuzz_engine() -> N8nExecutionEngine:
    """Propagating engine: fuzzing measures behaviour past the point of failure."""
    return _engine(propagate_failures=True)
