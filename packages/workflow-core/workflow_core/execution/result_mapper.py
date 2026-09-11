"""Turning an n8n execution back into a `SimulationResult` expressed in canonical ids.

This is the seam that lets everything downstream survive the move to real execution:
`AssertionEngine`, `CoverageCalculator` and `FuzzEngine` keep working unchanged because what
they receive is shaped exactly as the simulator's output was.

Three facts about n8n's execution data drive the design, all verified against 2.38.7 in the
step-0 spike (fixtures under `tests/fixtures/n8n/`):

1. ``taskData.source[]`` carries ``{previousNode, previousNodeOutput}``. That, plus the
   emitter's `EdgeMap`, is what makes `executed_edges` and `branch_decisions` recoverable.
2. **A failed node can report success.** Under ``onError: continueErrorOutput`` the node's
   ``executionStatus`` is ``"success"`` and it carries no ``error`` - the failure is an item on
   its error output. Reading status alone would report a workflow that swallowed every error as
   entirely healthy.
3. **Retry counts do not exist** anywhere in the data. They come from the mock server's call
   log, which is hit once per attempt.
"""

from __future__ import annotations

from typing import Any

from workflow_core.emitters.n8n.models import EmittedWorkflow
from workflow_core.testing.models import (
    NodeExecution,
    SimulatedCall,
    SimulationResult,
    TestRunStatus,
    WorkflowTest,
)

__all__ = ["map_execution"]


def map_execution(
    execution: dict[str, Any],
    emitted: EmittedWorkflow,
    test: WorkflowTest,
    *,
    workflow_id: str,
    external_calls: list[SimulatedCall] | None = None,
    retries: dict[str, int] | None = None,
) -> SimulationResult:
    """Build a `SimulationResult` from one n8n execution.

    Args:
        execution: the object from ``GET /api/v1/executions/{id}?includeData=true``.
        emitted: what the emitter produced for this run; supplies every id translation.
        external_calls / retries: from the mock registry's call log. n8n cannot supply either.
    """
    result_data = (execution.get("data") or {}).get("resultData") or {}
    run_data: dict[str, list[dict[str, Any]]] = result_data.get("runData") or {}

    result = SimulationResult(
        workflow_id=workflow_id,
        test_id=test.id,
        status=TestRunStatus.PASSED,
        external_calls=list(external_calls or []),
        retries=dict(retries or {}),
        warnings=list(emitted.warnings),
    )

    for n8n_name, task in _tasks_in_execution_order(run_data):
        canonical_id = emitted.nodes.canonical(n8n_name)
        error = _node_error(task, canonical_id, emitted)

        if canonical_id is not None:
            result.execution_order.append(canonical_id)
            result.node_executions.append(_node_execution(canonical_id, n8n_name, task, error))
            outputs = _first_output_items(task)
            if outputs:
                result.outputs[canonical_id] = outputs[-1]
            if error:
                result.failures.append(f"{n8n_name}: {error}")

        result.duration_ms += int(task.get("executionTime") or 0)
        _record_branch(result, n8n_name, task, emitted)
        _record_edges(result, task, emitted)

    result.approval_requests = [
        node_id for node_id in result.execution_order if node_id in emitted.nodes.approval_nodes
    ]
    result.token_estimate = _estimate_tokens(result.outputs)

    workflow_error = result_data.get("error")
    if workflow_error and workflow_error.get("message"):
        message = workflow_error["message"]
        if not any(message in failure for failure in result.failures):
            result.failures.append(message)

    if _is_error(execution, result):
        result.status = TestRunStatus.ERROR

    return result


def _tasks_in_execution_order(
    run_data: dict[str, list[dict[str, Any]]],
) -> list[tuple[str, dict[str, Any]]]:
    """Every task, ordered as n8n ran them.

    ``executionIndex`` is a monotonic counter and the right key; `startTime` ties at millisecond
    resolution on fast nodes, which is most of them when integrations are mocked. Falls back to
    startTime for older payloads that predate the field.
    """
    tasks = [(name, task) for name, runs in run_data.items() for task in runs]
    return sorted(
        tasks,
        key=lambda item: (
            item[1].get("executionIndex")
            if item[1].get("executionIndex") is not None
            else item[1].get("startTime", 0)
        ),
    )


def _node_error(task: dict[str, Any], canonical_id: str | None, emitted: EmittedWorkflow) -> str | None:
    """The node's error, whichever of the two shapes n8n used.

    Stop-on-error puts it on ``taskData.error``. Under `continueErrorOutput` there is no
    ``error`` key at all and ``executionStatus`` reads ``"success"`` - the only evidence is an
    item sitting on the error output, so the emitter's recorded index is required to find it.
    """
    error = task.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])

    if canonical_id is None:
        return None
    error_index = emitted.error_output_index.get(canonical_id)
    if error_index is None:
        return None
    outputs = _outputs(task)
    if len(outputs) <= error_index:
        return None
    for item in outputs[error_index] or []:
        json_body = (item or {}).get("json") or {}
        nested = json_body.get("error")
        if isinstance(nested, dict) and nested.get("message"):
            return str(nested["message"])
        if isinstance(nested, str) and nested:
            return nested
        if nested is not None:
            return "Node reported an error on its error output."
    return None


def _node_execution(
    canonical_id: str, n8n_name: str, task: dict[str, Any], error: str | None
) -> NodeExecution:
    items = _first_output_items(task)
    return NodeExecution(
        node_id=canonical_id,
        node_name=n8n_name,
        node_type=str(task.get("executionStatus") or "completed"),
        status="failed" if error else "completed",
        input_data={},
        output_data=items[-1] if items else {},
        latency_ms=int(task.get("executionTime") or 0),
        error=error,
    )


def _record_branch(
    result: SimulationResult, n8n_name: str, task: dict[str, Any], emitted: EmittedWorkflow
) -> None:
    """Which branch a routing node took.

    Filed under the *canonical* node even when a synthetic router made the decision: the router
    exists only because that node could not hold its own outputs, so the choice is still the
    canonical node's.
    """
    outputs = _outputs(task)
    if len(outputs) < 2:
        return
    decider = emitted.nodes.decider(n8n_name)
    if decider is None:
        return
    for index, items in enumerate(outputs):
        if not items:
            continue
        edge_id = emitted.edges.edge_for(n8n_name, index)
        if edge_id:
            result.branch_decisions[decider] = edge_id
        return


def _record_edges(result: SimulationResult, task: dict[str, Any], emitted: EmittedWorkflow) -> None:
    """Edges traversed to reach this task, read from where its input came from."""
    for source in task.get("source") or []:
        if not source or not source.get("previousNode"):
            continue
        edge_id = emitted.edges.edge_for(
            source["previousNode"], int(source.get("previousNodeOutput") or 0)
        )
        if edge_id and edge_id not in result.executed_edges:
            result.executed_edges.append(edge_id)


def _is_error(execution: dict[str, Any], result: SimulationResult) -> bool:
    if execution.get("status") == "error" or execution.get("finished") is False:
        return True
    return bool(result.failures)


def _outputs(task: dict[str, Any]) -> list[list[dict[str, Any]]]:
    return ((task.get("data") or {}).get("main")) or []


def _first_output_items(task: dict[str, Any]) -> list[dict[str, Any]]:
    """Item payloads on the node's first output, which is its success path."""
    outputs = _outputs(task)
    if not outputs:
        return []
    return [(item or {}).get("json") or {} for item in (outputs[0] or [])]


def _estimate_tokens(outputs: dict[str, Any]) -> int:
    return max(1, len(str(outputs)) // 4) if outputs else 0
