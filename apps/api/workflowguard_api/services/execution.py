"""Building the execution engine the API runs tests with.

One factory, so the engine is configured identically wherever a test is run - the testing
service, the repair service and the fuzzer all go through here - and so tests have a single
seam to substitute at.
"""

from __future__ import annotations

from workflow_core.emitters.n8n import N8nEmitter
from workflow_core.execution import N8nClient, N8nExecutionEngine

from workflowguard_api.core.config import Settings, get_settings
from workflowguard_api.services.mock_registry import mock_registry


def build_engine(
    settings: Settings | None = None, *, propagate_failures: bool = False
) -> N8nExecutionEngine:
    """The n8n-backed engine.

    `propagate_failures` is True only for fuzzing, which measures behaviour past the point of
    failure and learns nothing from a run that halts at the first throw.
    """
    settings = settings or get_settings()
    return N8nExecutionEngine(
        N8nClient(
            settings.n8n_base_url,
            settings.n8n_api_key,
            poll_interval_seconds=settings.n8n_poll_interval_seconds,
        ),
        emitter=N8nEmitter(mock_base_url=settings.mock_base_url),
        mocks=mock_registry,
        propagate_failures=propagate_failures,
        run_timeout_seconds=settings.n8n_run_timeout_seconds,
    )
