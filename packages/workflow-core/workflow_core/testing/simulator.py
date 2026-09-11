from __future__ import annotations

from collections import defaultdict, deque
from time import perf_counter
from typing import Any

from workflow_core.analysis.failure_paths import is_failure_edge
from workflow_core.canonical.models import Edge, Node, NodeType, Workflow
from workflow_core.conditions import evaluate_condition
from workflow_core.testing.models import (
    FailureInjection,
    FailureType,
    MockIntegration,
    NodeExecution,
    SimulatedCall,
    SimulationResult,
    TestRunStatus,
    WorkflowTest,
)


class WorkflowSimulator:
    max_steps = 250

    def __init__(self, *, propagate_failures: bool = False) -> None:
        """
        Args:
            propagate_failures: when True, a failing node with no error edge of its own
                records the failure into workflow state and continues down its normal
                edges, instead of aborting the run. Real workflows commonly handle errors
                downstream - the call runs, then the next condition inspects
                ``result.success`` - and that handling is invisible to a run that stops at
                the failing node. Off by default so stored test runs keep their existing
                pass/fail semantics.
        """
        self.propagate_failures = propagate_failures

    def simulate(self, workflow: Workflow, test: WorkflowTest) -> SimulationResult:
        started = perf_counter()
        nodes = {node.id: node for node in workflow.nodes}
        outgoing: dict[str, list[Edge]] = defaultdict(list)
        for edge in workflow.edges:
            outgoing[edge.source].append(edge)
        mock_by_node = {mock.node_id: mock for mock in test.mocked_integrations}
        failure_by_node: dict[str, list[FailureInjection]] = defaultdict(list)
        for failure in test.failure_injections:
            failure_by_node[failure.node_id].append(failure)

        result = SimulationResult(workflow_id=workflow.id, test_id=test.id, status=TestRunStatus.PASSED)
        queue = deque(workflow.start_node_ids)
        visits: dict[str, int] = defaultdict(int)
        state: dict[str, Any] = dict(test.input_data)

        try:
            while queue and len(result.execution_order) < self.max_steps:
                node_id = queue.popleft()
                node = nodes.get(node_id)
                if node is None:
                    result.failures.append(f"Missing target node {node_id}.")
                    continue
                visits[node_id] += 1
                execution = self._execute_node(node, state, mock_by_node.get(node_id), failure_by_node[node_id], visits[node_id])
                result.node_executions.append(execution)
                result.execution_order.append(node_id)
                result.duration_ms += execution.latency_ms
                if execution.retries:
                    result.retries[node_id] = execution.retries
                if node.type == NodeType.LLM:
                    result.token_estimate += _estimate_tokens(state)
                if execution.error:
                    result.failures.append(f"{node.name}: {execution.error}")
                    if _has_failure_edge(outgoing[node_id]):
                        for edge in _failure_edges(outgoing[node_id]):
                            result.executed_edges.append(edge.id)
                            queue.append(edge.target)
                        continue
                    if not self.propagate_failures:
                        result.status = TestRunStatus.ERROR
                        break
                    # Let the failure travel downstream so a condition that inspects the
                    # result can take its remediation branch.
                    state.update(_failure_state(node, execution.error))
                    result.outputs[node_id] = dict(_failure_state(node, execution.error))
                    next_edges = self._select_edges(node, outgoing[node_id], state)
                    if not next_edges:
                        result.status = TestRunStatus.ERROR
                        break
                    for edge in next_edges:
                        result.executed_edges.append(edge.id)
                        if edge.condition or edge.label:
                            result.branch_decisions[node.id] = edge.label or edge.condition or edge.target
                        queue.append(edge.target)
                    continue
                state.update(execution.output_data)
                result.outputs[node_id] = execution.output_data
                if execution.mocked and node.type in {NodeType.EXTERNAL_API, NodeType.DATABASE, NodeType.EMAIL, NodeType.LLM}:
                    result.external_calls.append(
                        SimulatedCall(
                            node_id=node.id,
                            provider=node.provider,
                            operation=node.operation,
                            request=state,
                            response=execution.output_data,
                            status_code=(mock_by_node[node_id].status_code if node_id in mock_by_node else 200),
                            latency_ms=execution.latency_ms,
                            error=execution.error,
                        )
                    )
                if node.type == NodeType.HUMAN_APPROVAL:
                    result.approval_requests.append(node.id)

                next_edges = self._select_edges(node, outgoing[node_id], state)
                for edge in next_edges:
                    result.executed_edges.append(edge.id)
                    if edge.condition or edge.label:
                        result.branch_decisions[node.id] = edge.label or edge.condition or edge.target
                    queue.append(edge.target)

            if queue:
                result.status = TestRunStatus.ERROR
                result.failures.append("Simulation stopped after reaching the maximum step limit.")
        except (RuntimeError, ValueError, TypeError, KeyError) as exc:
            result.status = TestRunStatus.ERROR
            result.failures.append(str(exc))

        result.duration_ms = max(result.duration_ms, int((perf_counter() - started) * 1000))
        return result

    def _execute_node(
        self,
        node: Node,
        state: dict[str, Any],
        mock: MockIntegration | None,
        failures: list[FailureInjection],
        occurrence: int,
    ) -> NodeExecution:
        injected = next((failure for failure in failures if failure.occurrence == occurrence), None)
        if injected:
            return _failure_execution(node, state, injected)
        if mock:
            return NodeExecution(
                node_id=node.id,
                node_name=node.name,
                node_type=str(node.type),
                status="mocked",
                input_data=dict(state),
                output_data=mock.response if isinstance(mock.response, dict) else {"result": mock.response},
                mocked=True,
                latency_ms=mock.latency_ms,
                error=mock.error,
            )

        if node.type in {NodeType.TRIGGER, NodeType.EVENT}:
            output = {"triggered": True, **state}
        elif node.type == NodeType.CONDITION:
            output = {"condition_evaluated": True}
        elif node.type == NodeType.HUMAN_APPROVAL:
            output = {"approved": state.get("approved", True), "approval_requested": True}
        elif node.type == NodeType.LLM:
            output = {"llm_output": state.get("llm_output", "mocked llm response")}
        elif node.type in {NodeType.EXTERNAL_API, NodeType.DATABASE}:
            output = {"ok": True, "mocked": True}
        elif node.type == NodeType.EMAIL:
            output = {"email_processed": True}
        elif node.type == NodeType.END:
            output = {"terminated": True}
        else:
            output = {"ok": True}
        return NodeExecution(
            node_id=node.id,
            node_name=node.name,
            node_type=str(node.type),
            status="completed",
            input_data=dict(state),
            output_data=output,
            mocked=node.type in {NodeType.EXTERNAL_API, NodeType.DATABASE, NodeType.EMAIL, NodeType.LLM},
            latency_ms=10,
        )

    def _select_edges(self, node: Node, edges: list[Edge], state: dict[str, Any]) -> list[Edge]:
        if not edges:
            return []
        conditional = [edge for edge in edges if edge.condition]
        if not conditional:
            return edges[:1]
        matched = [edge for edge in conditional if evaluate_condition(edge.condition or "", state)]
        if matched:
            return matched[:1]
        fallback = [
            edge
            for edge in edges
            if not edge.condition or str(edge.label).lower() in ("else", "default", "false", "no")
        ]
        if fallback:
            return fallback[:1]
        if self.propagate_failures:
            # No branch matched and no default exists. Abandoning the run here would leave
            # most of the workflow unexercised and silently unmeasured, so take the first
            # branch rather than reporting a graph we never walked.
            return edges[:1]
        return []


def _failure_execution(node: Node, state: dict[str, Any], failure: FailureInjection) -> NodeExecution:
    message_by_type = {
        FailureType.TIMEOUT: "Simulated timeout.",
        FailureType.RATE_LIMIT: "Simulated HTTP 429/rate limit.",
        FailureType.HTTP_500: "Simulated HTTP 500.",
        FailureType.AUTHORIZATION: "Simulated authorization failure.",
        FailureType.UNAVAILABLE: "Simulated dependency unavailable.",
        FailureType.MALFORMED_OUTPUT: "Simulated malformed output.",
    }
    retries = int(node.configuration.get("retries") or node.configuration.get("retry") or 0)
    return NodeExecution(
        node_id=node.id,
        node_name=node.name,
        node_type=str(node.type),
        status="failed",
        input_data=dict(state),
        output_data={},
        mocked=True,
        retries=retries,
        latency_ms=50 * max(retries, 1),
        error=message_by_type.get(FailureType(failure.failure_type), "Simulated failure."),
    )


def _has_failure_edge(edges: list[Edge]) -> bool:
    return bool(_failure_edges(edges))


def _failure_edges(edges: list[Edge]) -> list[Edge]:
    return [edge for edge in edges if is_failure_edge(edge)]




def _estimate_tokens(state: dict[str, Any]) -> int:
    return max(1, len(str(state)) // 4)


def _failure_state(node: Node, error: str) -> dict[str, Any]:
    """State a downstream condition would see after this node failed.

    Written under both the node's declared output variable and bare field names, because
    conditions reference results either way (``result.success`` or plain ``success``).
    """
    marker: dict[str, Any] = {
        "success": False,
        "ok": False,
        "error": error,
        "status": "failed",
        "statusCode": 500,
        "status_code": 500,
    }
    output_variable = node.configuration.get("saveOutputAs") or node.configuration.get("save_output_as")
    if isinstance(output_variable, str) and output_variable:
        marker[output_variable] = dict(marker)
    return marker
