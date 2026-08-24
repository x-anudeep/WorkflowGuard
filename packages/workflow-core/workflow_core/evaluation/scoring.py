from __future__ import annotations

from collections import Counter

from workflow_core.canonical.models import ValidationFinding, ValidationSeverity, Workflow
from workflow_core.evaluation.models import DimensionScore, EvaluationDimension, EvaluationFinding


PENALTIES = {
    ValidationSeverity.CRITICAL: 35,
    ValidationSeverity.ERROR: 18,
    ValidationSeverity.WARNING: 7,
    ValidationSeverity.INFO: 2,
}
DIMENSION_WEIGHTS = {
    EvaluationDimension.STRUCTURAL: 0.25,
    EvaluationDimension.PROMPT_ALIGNMENT: 0.3,
    EvaluationDimension.RELIABILITY: 0.15,
    EvaluationDimension.SECURITY: 0.2,
    EvaluationDimension.MAINTAINABILITY: 0.1,
}


def dimension_scores(
    workflow: Workflow,
    structural_score: int,
    validation_findings: list[ValidationFinding],
    evaluation_findings: list[EvaluationFinding],
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
        EvaluationDimension.SECURITY,
        EvaluationDimension.MAINTAINABILITY,
    ]:
        related = [finding for finding in evaluation_findings if finding.dimension == dimension]
        penalty = sum(PENALTIES[ValidationSeverity(finding.severity)] for finding in related)
        score = max(0, min(100, 100 - penalty))
        scores.append(
            DimensionScore(
                dimension=dimension,
                score=score,
                explanation=f"Starts at 100 and subtracts transparent penalties for {dimension.value} findings.",
                calculation={"penalty": penalty, "findings": _severity_counts(related)},
            )
        )
    return scores


def overall_score(scores: list[DimensionScore]) -> int:
    by_dimension = {EvaluationDimension(score.dimension): score.score for score in scores}
    weighted = sum(by_dimension.get(dimension, 0) * weight for dimension, weight in DIMENSION_WEIGHTS.items())
    return round(weighted)


def _severity_counts(findings: list[ValidationFinding] | list[EvaluationFinding]) -> dict[str, int]:
    counts = Counter(str(finding.severity) for finding in findings)
    return {severity.value: counts.get(severity.value, 0) for severity in ValidationSeverity}
