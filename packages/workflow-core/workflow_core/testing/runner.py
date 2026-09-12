from __future__ import annotations

from workflow_core.canonical.models import Workflow
from workflow_core.evaluation.models import RequirementSpec
from workflow_core.execution.engine import engine_unavailable_result
from workflow_core.execution.n8n_client import N8nError
from workflow_core.testing.assertions import AssertionEngine
from workflow_core.testing.coverage import CoverageCalculator
from workflow_core.testing.models import (
    SimulationResult,
    TestRunStatus,
    WorkflowTest,
    WorkflowTestRun,
)


class WorkflowTestRunner:
    """Runs a test and turns the execution into a `WorkflowTestRun`.

    The engine is injected. It is the n8n-backed one in production; anything exposing
    ``simulate(workflow, test) -> SimulationResult`` works, which is what keeps the assertion
    and coverage logic here independent of how a workflow actually gets executed.
    """

    def __init__(self, engine) -> None:
        self.engine = engine
        self.assertions = AssertionEngine()
        self.coverage = CoverageCalculator()

    def run(
        self,
        workflow: Workflow,
        test: WorkflowTest,
        *,
        all_tests: list[WorkflowTest] | None = None,
        prior_runs: list[WorkflowTestRun] | None = None,
        requirement_spec: RequirementSpec | None = None,
    ) -> WorkflowTestRun:
        if not test.enabled:
            simulation = SimulationResult(
                workflow_id=workflow.id, test_id=test.id, status=TestRunStatus.SKIPPED
            )
            return WorkflowTestRun(
                workflow_id=workflow.id,
                workflow_version_id=test.workflow_version_id,
                test_id=test.id,
                status=TestRunStatus.SKIPPED,
                simulation=simulation,
                assertion_results=[],
                failures=["Test is disabled."],
                duration_ms=0,
            )
        try:
            simulation = self.engine.simulate(workflow, test)
        except N8nError as exc:
            # The engine failed, not the workflow. Record a run that says so rather than
            # letting an infrastructure problem be read as a workflow defect - or vanish.
            run = WorkflowTestRun(
                workflow_id=workflow.id,
                workflow_version_id=test.workflow_version_id,
                test_id=test.id,
                status=TestRunStatus.ERROR,
                simulation=engine_unavailable_result(workflow, test, exc),
                assertion_results=[],
                failures=[f"Execution engine unavailable: {exc}"],
                duration_ms=0,
            )
            # Deliberately no coverage. Nothing was executed, so any number here would be a
            # measurement of a run that did not happen - and coverage feeds both the quality
            # gate and the TEST_COVERAGE evaluation dimension, so a workflow would be scored
            # and gated on a fiction because the engine happened to be down.
            return run

        assertion_results = self.assertions.evaluate(test, simulation)
        assertion_failures = [result.message for result in assertion_results if not result.passed]
        failures = [*simulation.failures, *assertion_failures]
        status = TestRunStatus.PASSED
        if simulation.status == TestRunStatus.ERROR:
            status = TestRunStatus.ERROR
        elif failures:
            status = TestRunStatus.FAILED
        run = WorkflowTestRun(
            workflow_id=workflow.id,
            workflow_version_id=test.workflow_version_id,
            test_id=test.id,
            status=status,
            simulation=simulation,
            assertion_results=assertion_results,
            failures=failures,
            duration_ms=simulation.duration_ms,
        )
        all_runs = [*(prior_runs or []), run]
        run.coverage = self.coverage.calculate(workflow, all_runs, all_tests or [test], requirement_spec)
        return run
