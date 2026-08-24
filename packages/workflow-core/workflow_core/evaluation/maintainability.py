from __future__ import annotations

from collections import Counter

from workflow_core.canonical.models import ValidationSeverity, Workflow
from workflow_core.evaluation.models import (
    Confidence,
    EvaluationDimension,
    EvaluationFinding,
)


class MaintainabilityAnalyzer:
    def analyze(self, workflow: Workflow) -> list[EvaluationFinding]:
        findings: list[EvaluationFinding] = []
        unnamed = [node for node in workflow.nodes if node.name == node.id or len(node.name.strip()) < 3]
        if unnamed:
            findings.append(
                EvaluationFinding(
                    rule_id="WG-MAINT-001",
                    dimension=EvaluationDimension.MAINTAINABILITY,
                    severity=ValidationSeverity.WARNING,
                    title="Poorly named nodes",
                    message=f"{len(unnamed)} node(s) have missing or low-context names.",
                    expected="Readable node names that explain business intent.",
                    found=", ".join(node.id for node in unnamed[:5]),
                    why_it_matters="Opaque workflow names make review, repair, and audit harder.",
                    remediation="Rename nodes to describe intent rather than implementation IDs.",
                    confidence=Confidence.HIGH,
                )
            )
        type_counts = Counter(node.type for node in workflow.nodes)
        if len(workflow.nodes) > 20 and type_counts.get("condition", 0) > 6:
            findings.append(
                EvaluationFinding(
                    rule_id="WG-MAINT-002",
                    dimension=EvaluationDimension.MAINTAINABILITY,
                    severity=ValidationSeverity.INFO,
                    title="Large branch-heavy workflow",
                    message="Workflow has many nodes and conditions.",
                    expected="Complex workflows should be decomposed or documented.",
                    found=f"{len(workflow.nodes)} nodes and {type_counts.get('condition', 0)} condition nodes.",
                    why_it_matters="Large branch-heavy workflows are harder to reason about and test.",
                    remediation="Consider splitting into subflows or adding documentation metadata.",
                    confidence=Confidence.LOW,
                )
            )
        return findings
