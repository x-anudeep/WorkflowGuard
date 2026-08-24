from __future__ import annotations

from typing import Any

from workflow_core.testing.models import AssertionResult, AssertionType, SimulationResult, WorkflowAssertion, WorkflowTest


class AssertionEngine:
    def evaluate(self, test: WorkflowTest, simulation: SimulationResult) -> list[AssertionResult]:
        return [self._evaluate(assertion, simulation) for assertion in test.assertions]

    def _evaluate(self, assertion: WorkflowAssertion, simulation: SimulationResult) -> AssertionResult:
        passed = False
        message = assertion.description or f"{assertion.type} assertion"
        if assertion.type == AssertionType.NODE_EXECUTED:
            passed = assertion.target in simulation.execution_order
            message = _message(passed, f"Expected node {assertion.target} to execute.")
        elif assertion.type == AssertionType.NODE_NOT_EXECUTED:
            passed = assertion.target not in simulation.execution_order
            message = _message(passed, f"Expected node {assertion.target} not to execute.")
        elif assertion.type == AssertionType.EDGE_EXECUTED:
            passed = assertion.target in simulation.executed_edges
            message = _message(passed, f"Expected edge {assertion.target} to execute.")
        elif assertion.type == AssertionType.OUTPUT_EQUALS:
            actual = _lookup(simulation.outputs, assertion.target)
            passed = actual == assertion.expected
            message = _message(passed, f"Expected output {assertion.target} to equal {assertion.expected!r}; found {actual!r}.")
        elif assertion.type == AssertionType.OUTPUT_CONTAINS:
            actual = _lookup(simulation.outputs, assertion.target)
            passed = str(assertion.expected) in str(actual)
            message = _message(passed, f"Expected output {assertion.target} to contain {assertion.expected!r}.")
        elif assertion.type == AssertionType.ERROR_OCCURRED:
            passed = bool(simulation.failures) is bool(assertion.expected if assertion.expected is not None else True)
            message = _message(passed, "Expected error occurrence did not match simulation.")
        elif assertion.type == AssertionType.RETRY_COUNT:
            passed = simulation.retries.get(assertion.target or "", 0) == assertion.expected
            message = _message(passed, f"Expected {assertion.target} retry count to be {assertion.expected}.")
        elif assertion.type == AssertionType.APPROVAL_REQUESTED:
            passed = assertion.target in simulation.approval_requests if assertion.target else bool(simulation.approval_requests)
            message = _message(passed, "Expected approval to be requested.")
        elif assertion.type == AssertionType.EXTERNAL_CALLED:
            passed = any(call.node_id == assertion.target for call in simulation.external_calls)
            message = _message(passed, f"Expected external node {assertion.target} to be called.")
        elif assertion.type == AssertionType.EXTERNAL_NOT_CALLED:
            passed = not any(call.node_id == assertion.target for call in simulation.external_calls)
            message = _message(passed, f"Expected external node {assertion.target} not to be called.")
        elif assertion.type == AssertionType.TERMINATED_SUCCESSFULLY:
            passed = not simulation.failures and simulation.status == "PASSED"
            message = _message(passed, "Expected execution to terminate successfully.")
        return AssertionResult(assertion=assertion, passed=passed, message=message)


def _lookup(outputs: dict[str, Any], path: str | None) -> Any:
    if not path:
        return outputs
    current: Any = outputs
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _message(passed: bool, message: str) -> str:
    return ("Passed: " if passed else "Failed: ") + message
