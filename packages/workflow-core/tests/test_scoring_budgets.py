"""Scores must reflect defect *rate*, not workflow size.

Before per-rule budgets, penalties were an uncapped linear sum over per-node findings, so
corr(node_count, reliability) was -0.93 across the reference corpus and all ten complex
workflows scored exactly 0. These tests pin the properties that fix.
"""

from workflow_core.canonical.models import (
    Edge,
    Node,
    NodeType,
    SourceFormat,
    SourceType,
    ValidationSeverity,
    Workflow,
)
from workflow_core.evaluation.models import (
    EvaluationDimension,
    EvaluationFinding,
)
from workflow_core.evaluation.scoring import (
    DEFAULT_RULE_BUDGET,
    RULE_BUDGETS,
    dimension_scores,
)


def _workflow(external: int) -> Workflow:
    """Trigger -> N external API calls in a line -> End."""
    nodes = [Node(id="start", name="Start", type=NodeType.TRIGGER)]
    edges = []
    previous = "start"
    for index in range(external):
        node_id = f"api{index}"
        nodes.append(Node(id=node_id, name=f"Call {index}", type=NodeType.EXTERNAL_API))
        edges.append(Edge(id=f"e{index}", source=previous, target=node_id))
        previous = node_id
    nodes.append(Node(id="end", name="End", type=NodeType.END))
    edges.append(Edge(id="e-end", source=previous, target="end"))
    return Workflow(
        name=f"{external} external calls",
        source_format=SourceFormat.GENERIC_JSON,
        source_type=SourceType.HUMAN,
        nodes=nodes,
        edges=edges,
    )


def _finding(rule_id: str, population: int | None, severity=ValidationSeverity.WARNING):
    return EvaluationFinding(
        rule_id=rule_id,
        dimension=EvaluationDimension.RELIABILITY,
        severity=severity,
        title="t",
        message="m",
        expected="e",
        found="f",
        why_it_matters="w",
        rule_population=population,
    )


def _reliability(workflow, findings):
    scores = dimension_scores(workflow, 100, [], findings)
    return next(s for s in scores if s.dimension == EvaluationDimension.RELIABILITY)


def test_a_rule_costs_its_budget_only_when_every_applicable_node_fails() -> None:
    workflow = _workflow(12)
    budget = RULE_BUDGETS["WG-REL-001"]

    all_failing = _reliability(workflow, [_finding("WG-REL-001", 12) for _ in range(12)])
    assert all_failing.score == 100 - budget

    one_failing = _reliability(workflow, [_finding("WG-REL-001", 12)])
    assert one_failing.score == 100 - round(budget / 12)
    assert one_failing.score > all_failing.score


def test_no_single_rule_can_zero_a_dimension() -> None:
    """17 firings of one WARNING rule previously cost 119 points against a budget of 100."""
    workflow = _workflow(17)
    findings = [_finding("WG-REL-001", 17) for _ in range(17)]
    score = _reliability(workflow, findings)

    assert score.calculation["rule_breakdown"]["WG-REL-001"]["raw_penalty"] == 17 * 7
    assert score.calculation["penalty"] == RULE_BUDGETS["WG-REL-001"]
    assert score.score == 100 - RULE_BUDGETS["WG-REL-001"]


def test_score_tracks_defect_rate_not_workflow_size() -> None:
    """The whole point: same defect ratio, wildly different size, same score."""
    small = _workflow(3)
    large = _workflow(30)

    small_score = _reliability(small, [_finding("WG-REL-001", 3) for _ in range(3)])
    large_score = _reliability(large, [_finding("WG-REL-001", 30) for _ in range(30)])
    assert small_score.score == large_score.score

    # And a half-failing large workflow beats a fully-failing small one.
    half_large = _reliability(large, [_finding("WG-REL-001", 30) for _ in range(15)])
    assert half_large.score > small_score.score


def test_a_finding_without_a_population_falls_back_to_a_capped_raw_sum() -> None:
    workflow = _workflow(40)
    findings = [_finding("WG-REL-001", None) for _ in range(40)]
    score = _reliability(workflow, findings)

    entry = score.calculation["rule_breakdown"]["WG-REL-001"]
    assert entry["population"] is None
    assert entry["raw_penalty"] == 40 * 7
    assert entry["applied"] == RULE_BUDGETS["WG-REL-001"]


def test_unbudgeted_rules_are_still_capped() -> None:
    workflow = _workflow(30)
    findings = [_finding("WG-XXX-999", None) for _ in range(30)]
    score = _reliability(workflow, findings)

    assert score.calculation["rule_breakdown"]["WG-XXX-999"]["budget"] == DEFAULT_RULE_BUDGET
    assert score.score == 100 - DEFAULT_RULE_BUDGET


def test_penalty_equals_the_sum_of_the_breakdown() -> None:
    """Explainability contract: the number must be fully accounted for by the breakdown."""
    workflow = _workflow(6)
    findings = [_finding("WG-REL-001", 6) for _ in range(3)] + [
        _finding("WG-REL-004", 6, ValidationSeverity.INFO) for _ in range(6)
    ]
    score = _reliability(workflow, findings)
    breakdown = score.calculation["rule_breakdown"]

    assert score.calculation["penalty"] == round(sum(e["applied"] for e in breakdown.values()))
    assert set(breakdown) == {"WG-REL-001", "WG-REL-004"}


def test_no_findings_still_scores_100() -> None:
    assert _reliability(_workflow(5), []).score == 100
