from __future__ import annotations

from dataclasses import dataclass

from workflow_core.canonical.models import ValidationFinding, Workflow
from workflow_core.validation.graph import build_directed_graph
from workflow_core.validation.rules import DEFAULT_RULES, ValidationRule
from workflow_core.validation.scoring import structural_quality_score


@dataclass(frozen=True)
class ValidationResult:
    findings: list[ValidationFinding]
    structural_quality_score: int


class ValidationEngine:
    def __init__(self, rules: list[ValidationRule] | None = None) -> None:
        self.rules = rules or DEFAULT_RULES

    def validate(self, workflow: Workflow) -> ValidationResult:
        graph = build_directed_graph(workflow)
        findings: list[ValidationFinding] = []
        for rule in self.rules:
            findings.extend(rule.evaluate(workflow, graph))
        return ValidationResult(
            findings=findings,
            structural_quality_score=structural_quality_score(workflow, findings),
        )
