from __future__ import annotations

import re
from collections import Counter

from workflow_core.analysis.entrypoints import diagnose_entrypoints
from workflow_core.analysis.failure_paths import is_failure_edge
from workflow_core.canonical.models import Edge, Node, NodeType, Workflow
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
from workflow_core.fuzzing.reachability import reaching_input
from workflow_core.fuzzing.scoring import fuzz_findings, robustness_score
from workflow_core.testing.generator import default_mocks
from workflow_core.testing.models import (
    SimulationResult,
    TestGeneratedBy,
    TestRunStatus,
    WorkflowTest,
)

STEP_LIMIT_MARKER = "maximum step limit"

LIMITATIONS = [
    "Fuzz robustness is measured by executing the workflow in n8n with its integrations "
    "redirected to a mock server, not against production dependencies.",
    "External systems are mocked; results describe how the workflow handles injected failures, "
    "not real dependency behaviour.",
    "A HANDLED verdict means the run reached a declared error path, not that the recovery is correct.",
]


class FuzzEngine:
    """Executes fuzz cases through the execution engine and classifies error handling.

    The engine must be built with ``propagate_failures=True``: fuzzing measures how a workflow
    behaves *past* the point of failure, so a run that halts at the first throw says nothing.
    Stored test runs use the strict engine instead.
    """

    def __init__(self, engine) -> None:
        self.engine = engine
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

        edges_by_id = {edge.id: edge for edge in workflow.edges}
        baseline = self._baseline(workflow)

        nodes_by_id = {node.id: node for node in workflow.nodes}
        results = [
            self._run_case(workflow, case, baseline, edges_by_id, nodes_by_id) for case in cases
        ]
        counts = Counter(str(result.verdict) for result in results)
        exercised = sum(
            1
            for result in results
            if ErrorHandlingVerdict(result.verdict) != ErrorHandlingVerdict.NOT_TRIGGERED
        )

        report = FuzzReport(
            workflow_id=workflow.id,
            seed=seed,
            results=results,
            counts={verdict.value: counts.get(verdict.value, 0) for verdict in ErrorHandlingVerdict},
            exercised_cases=exercised,
            robustness_score=robustness_score(results),
            findings=fuzz_findings(workflow, results),
            generated_by=generated_by,
            ai_provider=ai_provider,
            ai_model=ai_model,
            ai_metadata=dict(ai_metadata or {}),
            limitations=list(LIMITATIONS),
        )
        if report.exercised_cases == 0:
            # Say so out loud. A robustness of 100 that nothing exercised means "not
            # measured", not "robust", and the two must never be read as the same thing.
            report.limitations.insert(
                0,
                "No fuzz case perturbed this workflow, so its robustness is unmeasured "
                "rather than proven.",
            )
        # Advice, not a finding: a mis-wired entry point explains an unmeasurable result
        # without silently changing what the score means.
        diagnosis = diagnose_entrypoints(workflow)
        if diagnosis is not None:
            report.suggestions.append(diagnosis.suggestion)
        return report

    def _baseline(self, workflow: Workflow) -> SimulationResult:
        """Unperturbed run, so NOT_TRIGGERED is a real comparison rather than a guess."""
        baseline_case = FuzzCase(
            name="Baseline",
            description="Unperturbed run used as the comparison for mutated cases.",
            strategy=FuzzStrategy.BASELINE,
            input_data={"amount": 100, "approved": True},
        )
        return self.engine.simulate(workflow, _as_test(workflow, baseline_case))

    def _run_case(
        self,
        workflow: Workflow,
        case: FuzzCase,
        baseline: SimulationResult,
        edges_by_id: dict[str, Edge],
        nodes_by_id: dict[str, Node],
    ) -> FuzzCaseResult:
        simulation = self.engine.simulate(workflow, _as_test(workflow, case))
        verdict, observed, evidence = _classify(case, simulation, baseline, edges_by_id, nodes_by_id)

        if verdict == ErrorHandlingVerdict.NOT_TRIGGERED and case.failure_injections:
            # The targeted node sits behind a branch the default input does not satisfy.
            # Solve the path conditions and try once more, so a case that describes a real
            # attack is not discarded merely because we could not steer the run to it.
            retried = self._retry_with_reaching_input(
                workflow, case, baseline, edges_by_id, nodes_by_id
            )
            if retried is not None:
                return retried

        return FuzzCaseResult(
            case=case,
            verdict=verdict,
            simulation=simulation,
            observed=observed,
            evidence=evidence,
        )

    def _retry_with_reaching_input(
        self,
        workflow: Workflow,
        case: FuzzCase,
        baseline: SimulationResult,
        edges_by_id: dict[str, Edge],
        nodes_by_id: dict[str, Node],
    ) -> FuzzCaseResult | None:
        """Re-run the case with inputs solved to reach its target, if that changes anything.

        Returns None when the retry still does not fire, so the original NOT_TRIGGERED
        result stands rather than being replaced by an equally empty one.
        """
        targets = [injection.node_id for injection in case.failure_injections]
        steered = dict(case.input_data)
        for node_id in targets:
            steered.update(reaching_input(workflow, node_id, steered))
        if steered == case.input_data:
            return None

        steered_case = case.model_copy(update={"input_data": steered})
        simulation = self.engine.simulate(workflow, _as_test(workflow, steered_case))
        verdict, observed, evidence = _classify(
            steered_case, simulation, baseline, edges_by_id, nodes_by_id
        )
        if verdict == ErrorHandlingVerdict.NOT_TRIGGERED:
            return None

        evidence.append(
            "Inputs were derived from the branch conditions on the path to the targeted node."
        )
        return FuzzCaseResult(
            case=steered_case,
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
    edges_by_id: dict[str, Edge],
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
    handling_edge = _handling_edge(simulation, injected_node_ids, edges_by_id, nodes_by_id)
    if handling_edge is not None:
        evidence.append(
            f"A branch inspecting the failed step was taken: {handling_edge.condition or handling_edge.label}."
        )

    if TestRunStatus(simulation.status) == TestRunStatus.ERROR:
        if any(STEP_LIMIT_MARKER in failure for failure in simulation.failures):
            return (
                ErrorHandlingVerdict.HUNG,
                "The run never terminated within the engine's time limit.",
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
        if handling_edge is not None and recovery:
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


#: Generic state keys written when a step fails. A branch testing one of
#: these unqualified is reading the failure, whatever the failing step was called.
_GENERIC_FAILURE_FIELDS = frozenset({"success", "ok", "error", "status", "statuscode", "status_code"})


def _handling_edge(
    simulation: SimulationResult,
    injected_node_ids: set[str],
    edges_by_id: dict[str, Edge],
    nodes_by_id: dict[str, Node],
) -> Edge | None:
    """The edge, if any, on which the workflow reacted to *this* failure.

    Reaching any error branch is not evidence of handling. A workflow whose OCR step
    failed and which later takes an unrelated "vendor not found" branch has not handled
    the OCR failure at all - crediting that would score a broken workflow as perfect.
    An edge counts only when it is an error edge leaving the failed node itself, or a
    branch whose condition actually reads the failed step's result.
    """
    failed = [
        execution.node_id
        for execution in simulation.node_executions
        if execution.error and execution.node_id in injected_node_ids
    ]
    if not failed:
        return None
    output_variables = {
        variable.lower()
        for node_id in failed
        if (variable := _output_variable(nodes_by_id.get(node_id))) is not None
    }

    for edge_id in simulation.executed_edges:
        edge = edges_by_id.get(edge_id)
        if edge is None or not is_failure_edge(edge):
            continue
        if edge.source in failed:
            return edge
        if _reads_failure(edge.condition, output_variables):
            return edge
    return None


def _output_variable(node: Node | None) -> str | None:
    if node is None:
        return None
    for key in ("saveOutputAs", "save_output_as", "outputVariable"):
        value = node.configuration.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _reads_failure(condition: str | None, output_variables: set[str]) -> bool:
    """Whether a branch condition inspects the failed step's result."""
    if not condition:
        return False
    lowered = condition.lower()
    if any(variable in lowered for variable in output_variables):
        return True
    # An unqualified `success == false` reads the generic failure marker.
    bare = re.findall(r"\b([a-z_][a-z0-9_]*)\s*(?:==|!=|<|>|<=|>=)", lowered)
    return any(field in _GENERIC_FAILURE_FIELDS for field in bare)
