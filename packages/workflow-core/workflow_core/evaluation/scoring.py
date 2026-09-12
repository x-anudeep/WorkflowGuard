from __future__ import annotations

from collections import Counter

from workflow_core.canonical.models import (
    ValidationFinding,
    ValidationSeverity,
    Workflow,
)
from workflow_core.evaluation.models import (
    DimensionScore,
    EvaluationDimension,
    EvaluationFinding,
)
from workflow_core.fuzzing.models import FuzzReport

PENALTIES = {
    ValidationSeverity.CRITICAL: 35,
    ValidationSeverity.ERROR: 18,
    ValidationSeverity.WARNING: 7,
    ValidationSeverity.INFO: 2,
}
#: The most any single rule may subtract from its dimension.
#:
#: Penalties used to be an uncapped linear sum, which made the score track workflow *size*
#: rather than quality: the per-node rules fire once per node, so a 17-external-call workflow
#: took 119 points from `WG-REL-001` alone against a budget of 100. Measured across the 30
#: reference workflows, corr(node_count, reliability) was -0.93 and corr(node_count, security)
#: -0.98, and all ten complex workflows scored exactly 0 on reliability.
#:
#: A rule now costs `budget x (findings / applicable population)`, so failing every applicable
#: node still costs the full budget while failing one of twelve costs a twelfth of it.
RULE_BUDGETS: dict[str, int] = {
    "WG-ALIGN-001": 45,
    "WG-ALIGN-002": 20,
    "WG-ALIGN-003": 20,
    "WG-ALIGN-004": 20,
    "WG-ALIGN-005": 15,
    "WG-ALIGN-006": 15,
    "WG-REL-001": 20,
    "WG-REL-002": 20,
    "WG-REL-003": 15,
    "WG-REL-004": 10,
    "WG-REL-005": 25,
    "WG-SEC-001": 60,
    "WG-SEC-002": 60,
    "WG-SEC-003": 35,
    "WG-SEC-004": 25,
    "WG-SEC-005": 20,
    "WG-MAINT-001": 25,
    "WG-MAINT-002": 15,
    "WG-FUZZ-001": 30,
    "WG-FUZZ-002": 30,
    "WG-FUZZ-003": 20,
    "WG-FUZZ-004": 20,
    "WG-FUZZ-005": 10,
}
#: Rules with no explicit budget keep the raw severity sum, capped so that one unknown rule
#: still cannot zero a dimension by itself.
DEFAULT_RULE_BUDGET = 25

#: How much of the reliability score comes from measured fuzz survival rather than
#: from statically declared error handling. Only applied when a fuzz report exists.
FUZZ_BLEND_WEIGHT = 0.40

DIMENSION_WEIGHTS = {
    EvaluationDimension.STRUCTURAL: 0.20,
    EvaluationDimension.PROMPT_ALIGNMENT: 0.25,
    EvaluationDimension.RELIABILITY: 0.15,
    EvaluationDimension.SECURITY: 0.15,
    EvaluationDimension.MAINTAINABILITY: 0.10,
    # Only scored once a test run exists for this version (see dimension_scores' test_coverage
    # argument) -- overall_score renormalises over whichever dimensions are actually present, so
    # an untested workflow is scored purely on the other five rather than being marked down for a
    # measurement that was never taken.
    EvaluationDimension.TEST_COVERAGE: 0.15,
}


def dimension_scores(
    workflow: Workflow,
    structural_score: int,
    validation_findings: list[ValidationFinding],
    evaluation_findings: list[EvaluationFinding],
    fuzz_report: FuzzReport | None = None,
    test_coverage: float | None = None,
) -> list[DimensionScore]:
    scores = [
        DimensionScore(
            dimension=EvaluationDimension.STRUCTURAL,
            score=structural_score,
            explanation="Deterministic structural validation score from Part 1 rules.",
            calculation={"validation_findings": _severity_counts(validation_findings)},
        )
    ]
    if test_coverage is not None:
        scores.append(
            DimensionScore(
                dimension=EvaluationDimension.TEST_COVERAGE,
                score=round(max(0.0, min(100.0, test_coverage))),
                explanation=(
                    "Measured from the latest test run for this version: the average of node, "
                    "edge, branch, and requirement coverage actually exercised."
                ),
                calculation={"overall_coverage": test_coverage},
            )
        )
    for dimension in [
        EvaluationDimension.PROMPT_ALIGNMENT,
        EvaluationDimension.RELIABILITY,
        EvaluationDimension.SECURITY,
        EvaluationDimension.MAINTAINABILITY,
    ]:
        related = [finding for finding in evaluation_findings if finding.dimension == dimension]
        penalty, breakdown = _dimension_penalty(related)
        score = max(0, min(100, 100 - penalty))
        explanation = (
            f"Starts at 100 and subtracts a budgeted penalty per {dimension.value} rule, scaled by "
            "the share of applicable nodes that failed it."
        )
        calculation: dict[str, object] = {
            "penalty": penalty,
            "findings": _severity_counts(related),
            "rule_breakdown": breakdown,
        }

        if dimension == EvaluationDimension.RELIABILITY and _has_fuzz_evidence(fuzz_report):
            score, explanation, calculation = _blend_reliability(score, penalty, related, fuzz_report)

        scores.append(
            DimensionScore(
                dimension=dimension,
                score=score,
                explanation=explanation,
                calculation=calculation,
            )
        )
    return scores


def _dimension_penalty(related: list[EvaluationFinding]) -> tuple[int, dict[str, object]]:
    """Sum each rule's budgeted contribution instead of every finding's raw penalty.

    Per-node rules fire once per node, so the raw sum grew with the graph and saturated the
    dimension at 0 for any workflow of real size. Scaling each rule by the fraction of
    applicable nodes that failed makes the score independent of how big the workflow is.
    """
    grouped: dict[str, list[EvaluationFinding]] = {}
    for finding in related:
        grouped.setdefault(finding.rule_id, []).append(finding)

    breakdown: dict[str, object] = {}
    total = 0.0
    for rule_id, findings in grouped.items():
        budget = RULE_BUDGETS.get(rule_id, DEFAULT_RULE_BUDGET)
        raw = sum(PENALTIES[ValidationSeverity(finding.severity)] for finding in findings)
        population = max((finding.rule_population or 0) for finding in findings)
        if population > 0:
            contribution = min(budget * len(findings) / population, float(budget))
        else:
            # No denominator reported, so fall back to the raw sum - capped, so an
            # unannotated rule still cannot zero the dimension on its own.
            contribution = float(min(raw, budget))
        breakdown[rule_id] = {
            "findings": len(findings),
            "population": population or None,
            "raw_penalty": raw,
            "budget": budget,
            "applied": round(contribution, 1),
        }
        total += contribution
    return round(total), breakdown


def _has_fuzz_evidence(fuzz_report: FuzzReport | None) -> bool:
    """Only blend when the campaign actually exercised the workflow.

    A campaign where every case was NOT_TRIGGERED reports a robustness of 100 by
    construction. Blending that in would hand out credit for a test that proved
    nothing, so an unexercised report is treated as no report at all.
    """
    return fuzz_report is not None and fuzz_report.exercised_cases > 0


def _blend_reliability(
    penalty_score: int,
    penalty: int,
    related: list[EvaluationFinding],
    fuzz_report: FuzzReport,
) -> tuple[int, str, dict[str, object]]:
    """Weight declared error handling against what fuzzing actually observed.

    ``penalty_score`` is the findings-based score. Once a campaign has run it already
    includes penalties for the WG-FUZZ findings, so a fragile workflow is marked down on
    both terms. That is deliberate - an unhandled failure is both a defect to report and
    a measured loss of robustness - but it means this is not a fuzz-free baseline, and
    the field is named accordingly.
    """
    fuzz_score = fuzz_report.robustness_score
    blended = round((1 - FUZZ_BLEND_WEIGHT) * penalty_score + FUZZ_BLEND_WEIGHT * fuzz_score)
    explanation = (
        f"{round((1 - FUZZ_BLEND_WEIGHT) * 100)}% findings-based score ({penalty_score}, including "
        f"fuzz findings) and {round(FUZZ_BLEND_WEIGHT * 100)}% measured survival across "
        f"{fuzz_report.exercised_cases} executed fuzz case(s) ({fuzz_score})."
    )
    calculation: dict[str, object] = {
        "penalty": penalty,
        "findings": _severity_counts(related),
        "penalty_score": penalty_score,
        "fuzz_robustness": fuzz_score,
        "fuzz_cases": len(fuzz_report.results),
        "fuzz_cases_exercised": fuzz_report.exercised_cases,
        "fuzz_counts": fuzz_report.counts,
        "fuzz_seed": fuzz_report.seed,
        "blend_weight": FUZZ_BLEND_WEIGHT,
    }
    return blended, explanation, calculation


def overall_score(scores: list[DimensionScore]) -> int:
    """Weighted average over whichever dimensions actually have a score.

    Renormalises rather than treating a missing dimension as a 0: TEST_COVERAGE is only present
    once a test run exists for this version, and an untested workflow should be scored on the
    other dimensions, not marked down for a measurement that was never taken. This is the same
    reasoning that restored the other weights to sum to 1.0 when hallucination was removed --
    a dimension silently defaulting to 0 quietly cuts every score by its weight's share.
    """
    by_dimension = {EvaluationDimension(score.dimension): score.score for score in scores}
    applicable = {dimension: weight for dimension, weight in DIMENSION_WEIGHTS.items() if dimension in by_dimension}
    if not applicable:
        return 0
    total_weight = sum(applicable.values())
    weighted = sum(by_dimension[dimension] * weight for dimension, weight in applicable.items())
    return round(weighted / total_weight)


def _severity_counts(findings: list[ValidationFinding] | list[EvaluationFinding]) -> dict[str, int]:
    counts = Counter(str(finding.severity) for finding in findings)
    return {severity.value: counts.get(severity.value, 0) for severity in ValidationSeverity}
