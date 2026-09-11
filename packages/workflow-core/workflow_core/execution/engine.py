"""Running a workflow test as a real n8n execution.

A drop-in replacement for the old `WorkflowSimulator`: same ``simulate(workflow, test)``
signature, same `SimulationResult` back, with ``propagate_failures`` fixed at construction.
That is deliberate - `WorkflowTestRunner` and `FuzzEngine` both call `simulate` and neither
needs to know that a workflow is now compiled, published, triggered over HTTP and read back.

A workflow is compiled, created and published **once per engine**, then triggered once per
test. Creating and deleting one per test was the obvious shape and the wrong one: a suite of
270 tests meant 270 create/publish/unpublish/delete cycles, each registering and tearing down a
webhook, and n8n's memory tracked that churn - 5 GB and climbing on a full differential run,
with execution pruning already on. Reuse takes the same run down to one activation per distinct
workflow.

The consequence is that published workflows now outlive a single `simulate` call, so the engine
owns them until `release()`. Use it as a context manager where there is a natural scope; the
`sweep()` of `wg-` prefixed workflows is the backstop for anything that escapes.

The mock server is reached through a protocol rather than imported. It lives in the API layer
(it is served by the same FastAPI app n8n calls back into), and workflow-core must not depend
upwards on that.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Protocol, runtime_checkable

from workflow_core.canonical.models import Workflow
from workflow_core.emitters.n8n import N8nEmitter
from workflow_core.emitters.n8n.models import EmittedWorkflow
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
        # Keep n8n's own deadline just inside ours, so a runaway workflow is stopped by the
        # engine that is running it rather than merely abandoned by the client waiting on it.
        self.emitter = emitter or N8nEmitter(
            execution_timeout_seconds=max(5, int(run_timeout_seconds) - 5)
        )
        self.mocks = mocks
        self.propagate_failures = propagate_failures
        self.run_timeout_seconds = run_timeout_seconds
        #: Namespaces this engine's webhook paths. Two engines running at once must not claim
        #: the same path - n8n answers the second publish with a 409.
        self._session = uuid.uuid4().hex[:8]
        #: fingerprint -> (n8n workflow id, what was emitted for it)
        self._published: dict[str, tuple[str, EmittedWorkflow]] = {}

    def simulate(self, workflow: Workflow, test: WorkflowTest) -> SimulationResult:
        """Run one test. Raises `N8nError` if the engine itself is unusable.

        An engine failure is deliberately *not* folded into a failing result here: "n8n was
        unreachable" and "the workflow under test is broken" are different facts, and a caller
        that cannot tell them apart will report infrastructure trouble as a workflow defect.
        `WorkflowTestRunner` makes that distinction explicit when it records the run.
        """
        fingerprint, workflow_id, emitted = self._publish(workflow)
        run_token = emitted.webhook_path.removeprefix("wg-")

        # Re-opening resets this run's occurrence counters and call log, so a reused workflow
        # never inherits the previous test's injections.
        mock_run = self.mocks.open(run_token, test) if self.mocks else None
        try:
            self.client.trigger(emitted.webhook_path, dict(test.input_data))
            execution = self.client.wait_for_execution(
                workflow_id, timeout_seconds=self.run_timeout_seconds
            )
        except N8nError:
            # The published workflow may be the problem; do not keep handing it to later tests.
            self._drop(fingerprint)
            raise
        finally:
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

        try:
            return map_execution(
                execution,
                emitted,
                test,
                workflow_id=workflow.id,
                external_calls=_external_calls(mock_run, emitted.mocked_nodes),
                retries=mock_run.retries_by_node() if mock_run else {},
            )
        finally:
            # Mapped, so n8n's copy is now redundant. Dropping it here keeps a long suite from
            # accumulating hundreds of full execution payloads in the engine's own store.
            execution_id = execution.get("id")
            if execution_id:
                self.client.delete_execution(str(execution_id))

    def _publish(self, workflow: Workflow) -> tuple[str, str, EmittedWorkflow]:
        """The published n8n workflow for this canonical workflow, creating it once.

        Keyed by a fingerprint of the emitted JSON rather than the workflow id, so a workflow
        edited between runs is correctly republished rather than silently reused.
        """
        emitted = self.emitter.emit(
            workflow,
            run_token=self._run_token(workflow),
            propagate_failures=self.propagate_failures,
        )
        fingerprint = _fingerprint(emitted.workflow_json)
        cached = self._published.get(fingerprint)
        if cached is not None:
            return fingerprint, cached[0], cached[1]

        workflow_id = self.client.create_workflow(emitted.workflow_json)
        try:
            self.client.publish(workflow_id)
        except N8nError:
            self.client.delete_workflow(workflow_id)
            raise
        self._published[fingerprint] = (workflow_id, emitted)
        return fingerprint, workflow_id, emitted

    def _run_token(self, workflow: Workflow) -> str:
        """Stable for one workflow within one engine, unique across both.

        Stability is what makes reuse possible; uniqueness is what stops two workflows claiming
        the same webhook path, which n8n rejects with a 409.
        """
        digest = hashlib.sha1(
            f"{workflow.id}:{workflow.name}".encode(), usedforsecurity=False
        ).hexdigest()[:8]
        return f"{self._session}{digest}"

    def _drop(self, fingerprint: str) -> None:
        entry = self._published.pop(fingerprint, None)
        if entry is not None:
            self.client.unpublish(entry[0])
            self.client.delete_workflow(entry[0])

    def release(self) -> None:
        """Unpublish and delete everything this engine published.

        Published workflows outlive a single run now, so someone has to end their life. A
        workflow left published keeps its webhook path claimed, and the next engine to use that
        path gets a 409 that has nothing to do with the workflow being tested.
        """
        for fingerprint in list(self._published):
            self._drop(fingerprint)

    def __enter__(self) -> "N8nExecutionEngine":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()

    def sweep(self) -> int:
        """Delete workflows left behind by runs that died mid-flight."""
        return self.client.sweep(ENGINE_WORKFLOW_PREFIX)

    def available(self) -> bool:
        return self.client.health()


def _fingerprint(workflow_json: dict[str, Any]) -> str:
    """Identity of an emitted workflow. Emission is deterministic, so this is stable."""
    return hashlib.sha1(
        json.dumps(workflow_json, sort_keys=True).encode(), usedforsecurity=False
    ).hexdigest()


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
