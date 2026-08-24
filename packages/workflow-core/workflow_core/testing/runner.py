from __future__ import annotations

from workflow_core.canonical.models import Workflow
from workflow_core.evaluation.models import RequirementSpec
from workflow_core.testing.assertions import AssertionEngine
from workflow_core.testing.coverage import CoverageCalculator
from workflow_core.testing.models import TestRunStatus, WorkflowTest, WorkflowTestRun
from workflow_core.testing.simulator import WorkflowSimulator


class WorkflowTestRunner:
    def __init__(self) -> None:
        self.simulator = WorkflowSimulator()
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
            simulation = self.simulator.simulate(workflow, test)
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
        simulation = self.simulator.simulate(workflow, test)
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
