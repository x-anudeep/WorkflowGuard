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

    # A swallowed error rides the item all the way downstream, so every later node's output
    # carries it too. Only the node that *introduced* it actually failed; attributing it to the
    # rest would report one fault as a cascade and make every terminal node look like a crash.
    seen_errors: set[str] = set()

    for n8n_name, task in _tasks_in_execution_order(run_data):
        canonical_id = emitted.nodes.canonical(n8n_name)
        error = _node_error(task, canonical_id, emitted, seen_errors)

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

    # A connection to a node that does not exist could not be emitted, so n8n cannot report it.
    # The run still has to fail when it reaches that edge's source, or a workflow with a broken
    # connection quietly passes.
    executed = set(result.execution_order)
    for dropped in emitted.dropped_edges:
        if dropped.get("source") in executed:
            result.failures.append(f"Missing target node {dropped.get('target')}.")

    workflow_error = result_data.get("error")
    if workflow_error and workflow_error.get("message"):
        message = workflow_error["message"]
        if not any(message in failure for failure in result.failures):
            result.failures.append(message)

    if _is_error(execution, result) or _failed_with_nowhere_to_go(result, emitted):
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


def _node_error(
    task: dict[str, Any],
    canonical_id: str | None,
    emitted: EmittedWorkflow,
    seen_errors: set[str],
) -> str | None:
    """The node's error, whichever of the two shapes n8n used.

    Stop-on-error puts it on ``taskData.error``. Under `continueErrorOutput` there is no
    ``error`` key at all and ``executionStatus`` reads ``"success"`` - the only evidence is an
    item sitting on the error output, so the emitter's recorded index is required to find it.
    """
    error = task.get("error")
    if isinstance(error, dict) and error.get("message"):
        seen_errors.add(str(error["message"]))
        return str(error["message"])

    if canonical_id is None:
        return None

    outputs = _outputs(task)
    error_index = emitted.error_output_index.get(canonical_id)
    if error_index is not None and len(outputs) > error_index:
        found = _error_in(outputs[error_index], "its error output")
        if found:
            seen_errors.add(found)
            return found

    if canonical_id in emitted.swallowing_nodes and outputs:
        # `continueRegularOutput`: the node threw and carried on regardless, so the error rides
        # the *normal* output. Missing this is how a workflow that swallows every failure comes
        # back looking healthy. n8n reports `executionStatus: "success"` and no task error here
        # (verified against 2.38.7), so the item really is the only evidence.
        found = _error_in(outputs[0], "and execution continued")
        if found and found not in seen_errors:
            seen_errors.add(found)
            return found

    return None


def _error_in(items: list[dict[str, Any]] | None, where: str) -> str | None:
    for item in items or []:
        json_body = (item or {}).get("json") or {}
        nested = json_body.get("error")
        if isinstance(nested, dict) and nested.get("message"):
            return str(nested["message"])
        if isinstance(nested, str) and nested:
            return nested
        if nested is not None:
            return f"Node reported an error {where}."
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
        label = emitted.edges.branch_label(n8n_name, index)
        if label:
            result.branch_decisions[decider] = label
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
    """Whether the *run* failed, as opposed to a node having failed within it.

    n8n already makes this judgement: a node that throws with nowhere to send the error stops
    the execution (`status: "error"`), while one whose workflow declares an error path - or
    which is configured to carry on - completes. That is exactly the distinction the simulator
    drew, and it is the one the fuzzer's verdicts rest on: a failure routed down a declared
    error path is *handled*, not a crash, so marking the run ERROR merely because a failure was
    recorded would collapse `handled` and `unhandled_crash` into the same answer.

    Node failures are still recorded in `failures` either way, so assertions like
    TERMINATED_SUCCESSFULLY and ERROR_OCCURRED keep working.
    """
    del result  # failures alone do not make a run an error; see above.
    return execution.get("status") == "error" or execution.get("finished") is False


def _failed_with_nowhere_to_go(result: SimulationResult, emitted: EmittedWorkflow) -> bool:
    """A node that failed and has no successor.

    n8n completes such a run happily when the node is set to carry on, but there is nothing to
    carry on *to*: the failure is unhandled by definition, and the fuzzer has to see that.
    """
    return any(
        execution.error and execution.node_id in emitted.terminal_nodes
        for execution in result.node_executions
    )


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
