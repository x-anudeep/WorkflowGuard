from workflow_core.canonical.models import (
    Edge,
    Node,
    NodeType,
    SourceFormat,
    SourceType,
    ValidationSeverity,
    Workflow,
)
from workflow_core.evaluation.models import EvaluationDimension
from workflow_core.evaluation.scoring import FUZZ_BLEND_WEIGHT, dimension_scores
from workflow_core.fuzzing import (
    DeterministicFuzzGenerator,
    ErrorHandlingVerdict,
    FuzzEngine,
    robustness_score,
)
from workflow_core.fuzzing.models import FuzzCase, FuzzCaseResult
from workflow_core.testing.models import SimulationResult, TestRunStatus


def _unguarded_workflow() -> Workflow:
    """Trigger -> API -> End, with no error path anywhere."""
    return Workflow(
        name="Unguarded payment",
        source_format=SourceFormat.GENERIC_JSON,
        source_type=SourceType.AI_GENERATED,
        nodes=[
            Node(id="start", name="Start", type=NodeType.TRIGGER),
            Node(id="pay", name="Charge Card", type=NodeType.EXTERNAL_API),
            Node(id="end", name="End", type=NodeType.END),
        ],
        edges=[
            Edge(id="e1", source="start", target="pay"),
            Edge(id="e2", source="pay", target="end"),
        ],
    )


def _guarded_workflow() -> Workflow:
    """Same shape, but the API has an error branch that notifies a human."""
    workflow = _unguarded_workflow()
    workflow.nodes.append(Node(id="alert", name="Notify Finance", type=NodeType.EMAIL))
    workflow.edges.append(Edge(id="e3", source="pay", target="alert", label="on error"))
    workflow.edges.append(Edge(id="e4", source="alert", target="end"))
    return workflow


def test_unhandled_dependency_failure_is_detected_and_scored() -> None:
    report = FuzzEngine().run(_unguarded_workflow(), max_cases=200)

    assert report.counts[ErrorHandlingVerdict.UNHANDLED_CRASH.value] > 0
    assert report.robustness_score < 100
    crash = next(finding for finding in report.findings if finding.rule_id == "WG-FUZZ-001")
    assert crash.dimension == EvaluationDimension.RELIABILITY
    assert crash.severity == ValidationSeverity.ERROR
    assert crash.node_id == "pay"
    # The finding must carry enough to reproduce the exact case.
    assert crash.metadata["fuzz_seed"] == report.seed
    assert crash.metadata["fuzz_case_names"]


def test_declared_error_path_that_notifies_counts_as_handled() -> None:
    report = FuzzEngine().run(_guarded_workflow(), max_cases=200)

    assert report.counts[ErrorHandlingVerdict.UNHANDLED_CRASH.value] == 0
    assert report.counts[ErrorHandlingVerdict.HANDLED.value] > 0
    assert report.robustness_score > FuzzEngine().run(_unguarded_workflow(), max_cases=200).robustness_score
    assert not [finding for finding in report.findings if finding.rule_id == "WG-FUZZ-001"]


def test_error_branch_that_only_ends_is_reported_as_silent() -> None:
    """An error edge straight to END hides the failure rather than handling it."""
    workflow = _unguarded_workflow()
    workflow.edges.append(Edge(id="e3", source="pay", target="end", label="on error"))

    report = FuzzEngine().run(workflow, max_cases=200)

    assert report.counts[ErrorHandlingVerdict.SILENT_SUCCESS.value] > 0
    silent = next(finding for finding in report.findings if finding.rule_id == "WG-FUZZ-002")
    assert silent.severity == ValidationSeverity.ERROR
    assert "swallow" in silent.title.lower() or "silent" in silent.title.lower()


def test_generation_is_reproducible_for_a_seed() -> None:
    workflow = _unguarded_workflow()
    generator = DeterministicFuzzGenerator()

    first = generator.generate(workflow, seed=99, max_cases=25)
    second = generator.generate(workflow, seed=99, max_cases=25)
    different = generator.generate(workflow, seed=100, max_cases=25)

    assert [case.name for case in first] == [case.name for case in second]
    assert [case.name for case in first] != [case.name for case in different]


def test_injected_failure_on_an_unreached_node_is_not_counted_as_a_pass() -> None:
    """A case that never fired proved nothing and must stay out of the denominator."""
    workflow = _unguarded_workflow()
    workflow.nodes.append(Node(id="orphan", name="Unreachable API", type=NodeType.EXTERNAL_API))

    report = FuzzEngine().run(workflow, max_cases=200)
    orphan_results = [
        result
        for result in report.results
        if result.case.failure_injections
        and {injection.node_id for injection in result.case.failure_injections} == {"orphan"}
    ]

    assert orphan_results
    assert all(
        ErrorHandlingVerdict(result.verdict) == ErrorHandlingVerdict.NOT_TRIGGERED
        for result in orphan_results
    )


def test_robustness_score_ignores_untriggered_cases() -> None:
    def result(verdict: ErrorHandlingVerdict) -> FuzzCaseResult:
        return FuzzCaseResult(
            case=FuzzCase(name="c", description="d"),
            verdict=verdict,
            simulation=SimulationResult(workflow_id="w", test_id="t", status=TestRunStatus.PASSED),
            observed="",
        )

    assert robustness_score([]) == 100
    assert robustness_score([result(ErrorHandlingVerdict.NOT_TRIGGERED)] * 5) == 100
    assert robustness_score([result(ErrorHandlingVerdict.HANDLED), result(ErrorHandlingVerdict.HUNG)]) == 50
    assert (
        robustness_score(
            [
                result(ErrorHandlingVerdict.HANDLED),
                result(ErrorHandlingVerdict.UNHANDLED_CRASH),
                result(ErrorHandlingVerdict.NOT_TRIGGERED),
            ]
        )
        == 50
    )


def _reliability(scores) -> object:
    return next(
        score for score in scores if score.dimension == EvaluationDimension.RELIABILITY
    )


def test_reliability_score_is_unchanged_when_no_fuzz_report_exists() -> None:
    """Regression guard: every workflow scored before fuzzing existed must score the same."""
    workflow = _unguarded_workflow()
    findings = FuzzEngine().run(workflow, max_cases=200).findings

    without = _reliability(dimension_scores(workflow, 90, [], findings))
    explicit_none = _reliability(dimension_scores(workflow, 90, [], findings, None))

    assert without.score == explicit_none.score
    assert "fuzz_robustness" not in without.calculation
    assert without.calculation["penalty"] == sum(
        {"ERROR": 18, "WARNING": 7, "INFO": 2, "CRITICAL": 35}[str(finding.severity)]
        for finding in findings
        if finding.dimension == EvaluationDimension.RELIABILITY
    )


def test_reliability_blends_static_and_measured_robustness() -> None:
    workflow = _unguarded_workflow()
    report = FuzzEngine().run(workflow, max_cases=200)

    score = _reliability(dimension_scores(workflow, 90, [], report.findings, report))
    static_score = score.calculation["static_score"]

    expected = round((1 - FUZZ_BLEND_WEIGHT) * static_score + FUZZ_BLEND_WEIGHT * report.robustness_score)
    assert score.score == expected
    assert score.calculation["fuzz_robustness"] == report.robustness_score
    assert score.calculation["fuzz_seed"] == report.seed
    assert score.calculation["fuzz_cases_exercised"] > 0
    # Measured fragility must actually pull the score below the static-only view.
    assert score.score < static_score


def test_unexercised_fuzz_report_does_not_inflate_reliability() -> None:
    """A campaign where nothing fired proves nothing and must not earn credit."""
    workflow = Workflow(
        name="No dependencies",
        source_format=SourceFormat.GENERIC_JSON,
        nodes=[
            Node(id="start", name="Start", type=NodeType.TRIGGER),
            Node(id="end", name="End", type=NodeType.END),
        ],
        edges=[Edge(id="e1", source="start", target="end")],
    )
    report = FuzzEngine().run(workflow, max_cases=200)
    for result in report.results:
        result.verdict = ErrorHandlingVerdict.NOT_TRIGGERED

    assert report.exercised_cases == 0
    blended = _reliability(dimension_scores(workflow, 90, [], [], report))
    plain = _reliability(dimension_scores(workflow, 90, [], []))
    assert blended.score == plain.score
    assert "fuzz_robustness" not in blended.calculation
