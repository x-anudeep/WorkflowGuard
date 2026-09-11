"""Running a workflow test as a real n8n execution.

A drop-in replacement for the old `WorkflowSimulator`: same ``simulate(workflow, test)``
signature, same `SimulationResult` back, with ``propagate_failures`` fixed at construction.
That is deliberate - `WorkflowTestRunner` and `FuzzEngine` both call `simulate` and neither
needs to know that a workflow is now compiled, published, triggered over HTTP and read back.

One run is: compile -> create -> publish -> POST the webhook -> wait -> map -> tear down. The
teardown is in a ``finally``, because a workflow left published keeps its webhook path claimed
and n8n then refuses the *next* run with 409.

The mock server is reached through a protocol rather than imported. It lives in the API layer
(it is served by the same FastAPI app n8n calls back into), and workflow-core must not depend
upwards on that.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol, runtime_checkable

from workflow_core.canonical.models import Workflow
from workflow_core.emitters.n8n import N8nEmitter
from workflow_core.execution.n8n_client import N8nClient, N8nError
from workflow_core.execution.result_mapper import map_execution
from workflow_core.testing.models import SimulatedCall, SimulationResult, TestRunStatus, WorkflowTest

__all__ = ["ENGINE_WORKFLOW_PREFIX", "MockRun", "MockSink", "N8nExecutionEngine"]

#: Every workflow this engine creates is named with it, so `sweep` can find orphans.
ENGINE_WORKFLOW_PREFIX = "wg-"


@runtime_checkable
class MockRun(Protocol):
    """The per-run view the engine needs of the mock server's call log."""

    calls: list[Any]

    def retries_by_node(self) -> dict[str, int]: ...


class MockSink(Protocol):
    """Opens and closes a run's mocked endpoints."""

    def open(self, run_token: str, test: WorkflowTest) -> MockRun: ...

    def close(self, run_token: str) -> MockRun | None: ...


class N8nExecutionEngine:
    """Executes a `WorkflowTest` against a real n8n instance."""

    def __init__(
        self,
        client: N8nClient,
        *,
        emitter: N8nEmitter | None = None,
        mocks: MockSink | None = None,
        propagate_failures: bool = False,
        run_timeout_seconds: float = 60.0,
    ) -> None:
        self.client = client
        self.emitter = emitter or N8nEmitter()
        self.mocks = mocks
        self.propagate_failures = propagate_failures
        self.run_timeout_seconds = run_timeout_seconds

    def simulate(self, workflow: Workflow, test: WorkflowTest) -> SimulationResult:
        """Run one test. Raises `N8nError` if the engine itself is unusable.

        An engine failure is deliberately *not* folded into a failing result here: "n8n was
        unreachable" and "the workflow under test is broken" are different facts, and a caller
        that cannot tell them apart will report infrastructure trouble as a workflow defect.
        `WorkflowTestRunner` makes that distinction explicit when it records the run.
        """
        run_token = uuid.uuid4().hex[:16]
        emitted = self.emitter.emit(
            workflow, run_token=run_token, propagate_failures=self.propagate_failures
        )

        mock_run = self.mocks.open(run_token, test) if self.mocks else None
        workflow_id: str | None = None
        try:
            workflow_id = self.client.create_workflow(emitted.workflow_json)
            self.client.publish(workflow_id)
            self.client.trigger(emitted.webhook_path, dict(test.input_data))
            execution = self.client.wait_for_execution(
                workflow_id, timeout_seconds=self.run_timeout_seconds
            )
        finally:
            if workflow_id is not None:
                self.client.unpublish(workflow_id)
                self.client.delete_workflow(workflow_id)
            if self.mocks is not None:
                self.mocks.close(run_token)

        if execution is None:
            # Published and triggered, but n8n recorded nothing. Reporting a pass here would
            # claim coverage for a run that never happened.
            result = SimulationResult(
                workflow_id=workflow.id,
                test_id=test.id,
                status=TestRunStatus.ERROR,
                warnings=list(emitted.warnings),
            )
            result.failures.append(
                "n8n recorded no execution for this run within "
                f"{self.run_timeout_seconds:g}s, so nothing was measured."
            )
            return result

        return map_execution(
            execution,
            emitted,
            test,
            workflow_id=workflow.id,
            external_calls=_external_calls(mock_run, emitted.mocked_nodes),
            retries=mock_run.retries_by_node() if mock_run else {},
        )

    def sweep(self) -> int:
        """Delete workflows left behind by runs that died mid-flight."""
        return self.client.sweep(ENGINE_WORKFLOW_PREFIX)

    def available(self) -> bool:
        return self.client.health()


def _external_calls(mock_run: MockRun | None, mocked_nodes: set[str]) -> list[SimulatedCall]:
    """The mock server's log, as `SimulatedCall`s.

    Only nodes the emitter actually redirected are included: a call logged for anything else
    would be an endpoint answering for a node it does not represent, which is worth not
    silently reporting as an integration call.
    """
    if mock_run is None:
        return []
    return [
        SimulatedCall(
            node_id=call.node_id,
            request=call.request if isinstance(call.request, dict) else {"body": call.request},
            response=call.response,
            status_code=call.status_code,
            latency_ms=call.latency_ms,
            error=call.error,
        )
        for call in mock_run.calls
        if call.node_id in mocked_nodes
    ]


def engine_unavailable_result(
    workflow: Workflow, test: WorkflowTest, error: N8nError
) -> SimulationResult:
    """An ERROR result that says the engine failed, not that the workflow did.

    Used by `WorkflowTestRunner` so a run still gets recorded - a missing run row looks like a
    test nobody ran, which is worse than a recorded one that explains itself.
    """
    result = SimulationResult(
        workflow_id=workflow.id, test_id=test.id, status=TestRunStatus.ERROR
    )
    result.failures.append(f"Execution engine unavailable: {error}")
    result.warnings.append(
        "This run did not execute. The result reflects the test engine, not the workflow."
    )
    return result
