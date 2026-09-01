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
#: How much of the reliability score comes from measured fuzz survival rather than
#: from statically declared error handling. Only applied when a fuzz report exists.
FUZZ_BLEND_WEIGHT = 0.40

DIMENSION_WEIGHTS = {
    EvaluationDimension.STRUCTURAL: 0.20,
    EvaluationDimension.PROMPT_ALIGNMENT: 0.25,
    EvaluationDimension.RELIABILITY: 0.15,
    EvaluationDimension.HALLUCINATION: 0.15,
    EvaluationDimension.SECURITY: 0.15,
    EvaluationDimension.MAINTAINABILITY: 0.10,
}


def dimension_scores(
    workflow: Workflow,
    structural_score: int,
    validation_findings: list[ValidationFinding],
    evaluation_findings: list[EvaluationFinding],
    fuzz_report: FuzzReport | None = None,
) -> list[DimensionScore]:
    scores = [
        DimensionScore(
            dimension=EvaluationDimension.STRUCTURAL,
            score=structural_score,
            explanation="Deterministic structural validation score from Part 1 rules.",
            calculation={"validation_findings": _severity_counts(validation_findings)},
        )
    ]
    for dimension in [
        EvaluationDimension.PROMPT_ALIGNMENT,
        EvaluationDimension.RELIABILITY,
        EvaluationDimension.HALLUCINATION,
        EvaluationDimension.SECURITY,
        EvaluationDimension.MAINTAINABILITY,
    ]:
        related = [finding for finding in evaluation_findings if finding.dimension == dimension]
        penalty = sum(PENALTIES[ValidationSeverity(finding.severity)] for finding in related)
        score = max(0, min(100, 100 - penalty))
        explanation = f"Starts at 100 and subtracts transparent penalties for {dimension.value} findings."
        calculation: dict[str, object] = {"penalty": penalty, "findings": _severity_counts(related)}

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


def _has_fuzz_evidence(fuzz_report: FuzzReport | None) -> bool:
    """Only blend when the campaign actually exercised the workflow.

    A campaign where every case was NOT_TRIGGERED reports a robustness of 100 by
    construction. Blending that in would hand out credit for a test that proved
    nothing, so an unexercised report is treated as no report at all.
    """
    return fuzz_report is not None and fuzz_report.exercised_cases > 0


def _blend_reliability(
    static_score: int,
    penalty: int,
    related: list[EvaluationFinding],
    fuzz_report: FuzzReport,
) -> tuple[int, str, dict[str, object]]:
    """Weight statically declared error handling against what fuzzing actually observed."""
    fuzz_score = fuzz_report.robustness_score
    blended = round((1 - FUZZ_BLEND_WEIGHT) * static_score + FUZZ_BLEND_WEIGHT * fuzz_score)
    explanation = (
        f"{round((1 - FUZZ_BLEND_WEIGHT) * 100)}% static analysis of declared error handling "
        f"({static_score}) and {round(FUZZ_BLEND_WEIGHT * 100)}% measured survival across "
        f"{fuzz_report.exercised_cases} executed fuzz case(s) ({fuzz_score})."
    )
    calculation: dict[str, object] = {
        "penalty": penalty,
        "findings": _severity_counts(related),
        "static_score": static_score,
        "fuzz_robustness": fuzz_score,
        "fuzz_cases": len(fuzz_report.results),
        "fuzz_cases_exercised": fuzz_report.exercised_cases,
        "fuzz_counts": fuzz_report.counts,
        "fuzz_seed": fuzz_report.seed,
        "blend_weight": FUZZ_BLEND_WEIGHT,
    }
    return blended, explanation, calculation


def overall_score(scores: list[DimensionScore]) -> int:
    by_dimension = {EvaluationDimension(score.dimension): score.score for score in scores}
    weighted = sum(by_dimension.get(dimension, 0) * weight for dimension, weight in DIMENSION_WEIGHTS.items())
    return round(weighted)


def _severity_counts(findings: list[ValidationFinding] | list[EvaluationFinding]) -> dict[str, int]:
    counts = Counter(str(finding.severity) for finding in findings)
    return {severity.value: counts.get(severity.value, 0) for severity in ValidationSeverity}
