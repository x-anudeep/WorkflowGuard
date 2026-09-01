from __future__ import annotations

from collections import Counter

from workflow_core.analysis.failure_paths import is_failure_edge
from workflow_core.canonical.models import Node, NodeType, Workflow
from workflow_core.evaluation.models import RequirementSpec
from workflow_core.fuzzing.generator import (
    DEFAULT_MAX_CASES,
    DEFAULT_SEED,
    DeterministicFuzzGenerator,
)
from workflow_core.fuzzing.models import (
    ErrorHandlingVerdict,
    FuzzCase,
    FuzzCaseResult,
    FuzzReport,
    FuzzStrategy,
)
from workflow_core.fuzzing.scoring import fuzz_findings, robustness_score
from workflow_core.testing.generator import default_mocks
from workflow_core.testing.models import (
    SimulationResult,
    TestGeneratedBy,
    TestRunStatus,
    WorkflowTest,
)
from workflow_core.testing.simulator import WorkflowSimulator

STEP_LIMIT_MARKER = "maximum step limit"

LIMITATIONS = [
    "Fuzz robustness is measured against the simulated canonical graph, not a production runtime.",
    "External systems are mocked; results describe declared error handling, not real dependency behaviour.",
    "A HANDLED verdict means the run reached a declared error path, not that the recovery is correct.",
]


class FuzzEngine:
    """Executes fuzz cases through the sandboxed simulator and classifies error handling.

    This never touches the network and never executes uploaded code - it reuses
    :class:`~workflow_core.testing.simulator.WorkflowSimulator`, the same sandbox the
    deterministic test suite runs in.
    """

    def __init__(self) -> None:
        self.simulator = WorkflowSimulator()
        self.generator = DeterministicFuzzGenerator()

    def run(
        self,
        workflow: Workflow,
        cases: list[FuzzCase] | None = None,
        *,
        requirement_spec: RequirementSpec | None = None,
        seed: int = DEFAULT_SEED,
        max_cases: int = DEFAULT_MAX_CASES,
        generated_by: TestGeneratedBy = TestGeneratedBy.SYSTEM,
        ai_provider: str | None = None,
        ai_model: str | None = None,
        ai_metadata: dict[str, str] | None = None,
    ) -> FuzzReport:
        if cases is None:
            cases = self.generator.generate(
                workflow, requirement_spec, seed=seed, max_cases=max_cases
            )

        failure_edge_ids = {edge.id for edge in workflow.edges if is_failure_edge(edge)}
        baseline = self._baseline(workflow)

        nodes_by_id = {node.id: node for node in workflow.nodes}
        results = [
            self._run_case(workflow, case, baseline, failure_edge_ids, nodes_by_id) for case in cases
        ]
        counts = Counter(str(result.verdict) for result in results)

        report = FuzzReport(
            workflow_id=workflow.id,
            seed=seed,
            results=results,
            counts={verdict.value: counts.get(verdict.value, 0) for verdict in ErrorHandlingVerdict},
            robustness_score=robustness_score(results),
            findings=fuzz_findings(workflow, results),
            generated_by=generated_by,
            ai_provider=ai_provider,
            ai_model=ai_model,
            ai_metadata=dict(ai_metadata or {}),
            limitations=list(LIMITATIONS),
        )
        return report

    def _baseline(self, workflow: Workflow) -> SimulationResult:
        """Unperturbed run, so NOT_TRIGGERED is a real comparison rather than a guess."""
        baseline_case = FuzzCase(
            name="Baseline",
            description="Unperturbed run used as the comparison for mutated cases.",
            strategy=FuzzStrategy.BASELINE,
            input_data={"amount": 100, "approved": True},
        )
        return self.simulator.simulate(workflow, _as_test(workflow, baseline_case))

    def _run_case(
        self,
        workflow: Workflow,
        case: FuzzCase,
        baseline: SimulationResult,
        failure_edge_ids: set[str],
        nodes_by_id: dict[str, Node],
    ) -> FuzzCaseResult:
        simulation = self.simulator.simulate(workflow, _as_test(workflow, case))
        verdict, observed, evidence = _classify(case, simulation, baseline, failure_edge_ids, nodes_by_id)
        return FuzzCaseResult(
            case=case,
            verdict=verdict,
            simulation=simulation,
            observed=observed,
            evidence=evidence,
        )


def _as_test(workflow: Workflow, case: FuzzCase) -> WorkflowTest:
    return WorkflowTest(
        workflow_id=workflow.id,
        name=case.name,
        description=case.description,
        generated_by=case.generated_by,
        input_data=dict(case.input_data),
        mocked_integrations=default_mocks(workflow),
        failure_injections=list(case.failure_injections),
        tags=list(case.tags),
        rationale=case.rationale,
    )


#: Node categories that count as telling someone or compensating after a failure.
RECOVERY_TYPES = frozenset(
    {
        NodeType.HUMAN_APPROVAL,
        NodeType.EMAIL,
        NodeType.EXTERNAL_API,
        NodeType.DATABASE,
        NodeType.ACTION,
        NodeType.TASK,
    }
)


def _classify(
    case: FuzzCase,
    simulation: SimulationResult,
    baseline: SimulationResult,
    failure_edge_ids: set[str],
    nodes_by_id: dict[str, Node],
) -> tuple[ErrorHandlingVerdict, str, list[str]]:
    """Decide what the workflow actually did with the perturbation.

    The ordering matters. A fault that was injected but never reached (the node sits on
    an untaken branch) is NOT_TRIGGERED, not a pass - counting it as HANDLED would
    inflate the robustness score with cases that never tested anything.
    """
    evidence: list[str] = []
    if simulation.failures:
        evidence.extend(simulation.failures[:5])

    injected_node_ids = {injection.node_id for injection in case.failure_injections}
    fault_fired = any(
        execution.error and execution.node_id in injected_node_ids
        for execution in simulation.node_executions
    )
    took_failure_edge = any(edge_id in failure_edge_ids for edge_id in simulation.executed_edges)
    if took_failure_edge:
        evidence.append("Execution reached a declared error/compensation edge.")

    if TestRunStatus(simulation.status) == TestRunStatus.ERROR:
        if any(STEP_LIMIT_MARKER in failure for failure in simulation.failures):
            return (
                ErrorHandlingVerdict.HUNG,
                "The run never terminated and hit the simulator step limit.",
                evidence,
            )
        return (
            ErrorHandlingVerdict.UNHANDLED_CRASH,
            "The run aborted because the failing node had no error path to continue on.",
            evidence,
        )

    if case.failure_injections and not fault_fired:
        return (
            ErrorHandlingVerdict.NOT_TRIGGERED,
            "The targeted node was never reached, so the injected failure never fired.",
            evidence,
        )

    if fault_fired:
        recovery = _recovery_after_failure(simulation, injected_node_ids, nodes_by_id)
        if recovery:
            evidence.append(f"Recovery work ran after the failure: {', '.join(recovery)}.")
            return (
                ErrorHandlingVerdict.HANDLED,
                "The failure was routed down an error path that notified or compensated.",
                evidence,
            )
        return (
            ErrorHandlingVerdict.SILENT_SUCCESS,
            "The failure was swallowed - the run reported success with nothing notified or compensated.",
            evidence,
        )

    if simulation.execution_order == baseline.execution_order and not simulation.failures:
        return (
            ErrorHandlingVerdict.NOT_TRIGGERED,
            "The mutation did not change execution compared with the baseline run.",
            evidence,
        )

    return (
        ErrorHandlingVerdict.HANDLED,
        "The workflow absorbed the mutated input and still terminated cleanly.",
        evidence,
    )


def _recovery_after_failure(
    simulation: SimulationResult,
    injected_node_ids: set[str],
    nodes_by_id: dict[str, Node],
) -> list[str]:
    """Names of nodes that did real recovery work after the first injected failure.

    Reaching an error edge is not enough on its own: an error branch that runs straight
    to END has handled nothing, it has only hidden the failure.
    """
    first_failure = next(
        (
            index
            for index, execution in enumerate(simulation.node_executions)
            if execution.error and execution.node_id in injected_node_ids
        ),
        None,
    )
    if first_failure is None:
        return []
    return [
        execution.node_name
        for execution in simulation.node_executions[first_failure + 1 :]
        if execution.node_id in nodes_by_id
        and nodes_by_id[execution.node_id].type in RECOVERY_TYPES
        and not execution.error
    ]
