from __future__ import annotations

from workflow_core.canonical.models import (
    ValidationFinding,
    ValidationSeverity,
    Workflow,
)

PENALTIES = {
    ValidationSeverity.CRITICAL: 35,
    ValidationSeverity.ERROR: 15,
    ValidationSeverity.WARNING: 6,
    ValidationSeverity.INFO: 1,
}


def structural_quality_score(workflow: Workflow, findings: list[ValidationFinding]) -> int:
    if not workflow.nodes:
        return 0
    penalty = sum(PENALTIES[ValidationSeverity(finding.severity)] for finding in findings)
    completeness_bonus = _configuration_completeness_bonus(workflow)
    return max(0, min(100, 100 - penalty + completeness_bonus))


def _configuration_completeness_bonus(workflow: Workflow) -> int:
    executable = [
        node
        for node in workflow.nodes
        if node.type in {"action", "external_api", "database", "llm", "task", "human_approval"}
    ]
    if not executable:
        return 0
    configured = sum(1 for node in executable if node.configuration)
    return round((configured / len(executable)) * 5)
