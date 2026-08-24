from __future__ import annotations

from workflow_core.canonical.models import NodeType, ValidationSeverity, Workflow
from workflow_core.evaluation.models import (
    Confidence,
    EvaluationDimension,
    EvaluationFinding,
    RequirementKind,
    RequirementMatch,
    RequirementSpec,
)
from workflow_core.evaluation.understanding import WorkflowUnderstanding


class AlignmentAnalyzer:
    def analyze(self, spec: RequirementSpec, workflow: Workflow) -> tuple[list[RequirementMatch], list[EvaluationFinding]]:
        understanding = WorkflowUnderstanding(workflow)
        matches: list[RequirementMatch] = []
        findings: list[EvaluationFinding] = []

        for requirement in spec.requirements:
            candidates = _candidates_for_requirement(requirement.kind, requirement.normalized, understanding)
            if candidates:
                matches.append(
                    RequirementMatch(
                        requirement_id=requirement.id,
                        requirement_text=requirement.text,
                        status="matched",
                        matched_node_ids=[node.id for node in candidates[:3]],
                        evidence=f"Matched workflow node(s): {', '.join(node.name for node in candidates[:3])}.",
                        confidence=Confidence.MEDIUM,
                    )
                )
            else:
                matches.append(
                    RequirementMatch(
                        requirement_id=requirement.id,
                        requirement_text=requirement.text,
                        status="missing",
                        evidence="No canonical workflow node or configuration matched this requirement.",
                        confidence=Confidence.MEDIUM,
                    )
                )
                findings.append(
                    EvaluationFinding(
                        rule_id="WG-ALIGN-001",
                        dimension=EvaluationDimension.PROMPT_ALIGNMENT,
                        severity=ValidationSeverity.ERROR,
                        title="Missing required behavior",
                        message=f"Required workflow behavior is absent: {requirement.text}",
                        expected=requirement.text,
                        found="No matching workflow node or path.",
                        why_it_matters="The workflow may not satisfy the original user requirement.",
                        remediation="Add a workflow step that explicitly implements this requirement.",
                        confidence=Confidence.MEDIUM,
                        metadata={"requirement_id": requirement.id, "requirement_kind": requirement.kind},
                    )
                )

        findings.extend(_ordering_findings(spec, matches, understanding))
        findings.extend(_constraint_findings(spec, workflow, understanding))
        findings.extend(_extra_behavior_findings(spec, workflow, understanding))
        return matches, findings


def _candidates_for_requirement(kind: str, normalized: str, understanding: WorkflowUnderstanding):
    requirement_systems = set(normalized.split()) & {"gmail", "sap", "slack", "salesforce", "stripe", "postgres", "mysql", "s3", "openai"}
    if requirement_systems:
        system_matches = [
            node
            for node in understanding.workflow.nodes
            if any(system in " ".join([node.provider or "", node.subtype or "", node.name, str(node.configuration)]).lower() for system in requirement_systems)
        ]
        return system_matches
    if kind == RequirementKind.APPROVAL:
        return [node for node in understanding.workflow.nodes if node.type == NodeType.HUMAN_APPROVAL]
    if kind == RequirementKind.TRIGGER:
        typed = [node for node in understanding.workflow.nodes if node.type == NodeType.TRIGGER]
        return typed or understanding.find_nodes(normalized, min_overlap=0.25)
    if kind == RequirementKind.CONDITION:
        typed = [node for node in understanding.workflow.nodes if node.type in {NodeType.CONDITION, NodeType.GATEWAY}]
        condition_edges = [
            node
            for node in understanding.workflow.nodes
            if any(edge.condition and node.id in {edge.source, edge.target} for edge in understanding.workflow.edges)
        ]
        return typed or condition_edges or understanding.find_nodes(normalized, min_overlap=0.3)
    return understanding.find_nodes(normalized, min_overlap=0.34)


def _ordering_findings(
    spec: RequirementSpec, matches: list[RequirementMatch], understanding: WorkflowUnderstanding
) -> list[EvaluationFinding]:
    match_by_id = {match.requirement_id: match for match in matches if match.status == "matched" and match.matched_node_ids}
    findings: list[EvaluationFinding] = []
    for left_id, right_id in zip(spec.required_order, spec.required_order[1:]):
        left = match_by_id.get(left_id)
        right = match_by_id.get(right_id)
        if not left or not right:
            continue
        left_node = left.matched_node_ids[0]
        right_node = right.matched_node_ids[0]
        if not understanding.has_order(left_node, right_node):
            findings.append(
                EvaluationFinding(
                    rule_id="WG-ALIGN-002",
                    dimension=EvaluationDimension.PROMPT_ALIGNMENT,
                    severity=ValidationSeverity.ERROR,
                    title="Incorrect requirement ordering",
                    message=f"Expected '{left.requirement_text}' before '{right.requirement_text}'.",
                    expected=f"{left.requirement_text} -> {right.requirement_text}",
                    found=f"No path from {left_node} to {right_node}.",
                    why_it_matters="Workflow execution order contradicts the requested business process.",
                    node_id=left_node,
                    remediation="Reconnect the workflow so the required steps execute in prompt order.",
                    confidence=Confidence.MEDIUM,
                )
            )
    return findings


def _constraint_findings(
    spec: RequirementSpec, workflow: Workflow, understanding: WorkflowUnderstanding
) -> list[EvaluationFinding]:
    findings: list[EvaluationFinding] = []
    for constraint in spec.constraints:
        if "human_approval" not in constraint.must.lower():
            continue
        approval_nodes = [node for node in workflow.nodes if node.type == NodeType.HUMAN_APPROVAL]
        condition_nodes = [node for node in workflow.nodes if node.type in {NodeType.CONDITION, NodeType.GATEWAY}]
        condition_edges = [edge for edge in workflow.edges if edge.condition]
        if not approval_nodes:
            findings.append(
                EvaluationFinding(
                    rule_id="WG-ALIGN-003",
                    dimension=EvaluationDimension.PROMPT_ALIGNMENT,
                    severity=ValidationSeverity.CRITICAL,
                    title="Missing required approval branch",
                    message=f"Required approval for condition '{constraint.when}' is absent.",
                    expected=f"{constraint.when} -> {constraint.must}",
                    found="No human approval node exists in the workflow.",
                    why_it_matters="High-risk business rules can be bypassed.",
                    remediation="Add a human approval node on the matching conditional path before the destination action.",
                    confidence=Confidence.HIGH,
                    metadata={"constraint_id": constraint.id},
                )
            )
        elif not condition_nodes and not condition_edges:
            findings.append(
                EvaluationFinding(
                    rule_id="WG-ALIGN-004",
                    dimension=EvaluationDimension.PROMPT_ALIGNMENT,
                    severity=ValidationSeverity.ERROR,
                    title="Approval is not conditional",
                    message=f"Workflow includes approval but no detectable condition for '{constraint.when}'.",
                    expected=f"Conditional branch for {constraint.when}.",
                    found=f"Approval node(s): {', '.join(node.id for node in approval_nodes)} without a condition.",
                    why_it_matters="The workflow may approve too often or fail to enforce the intended threshold.",
                    node_id=approval_nodes[0].id,
                    remediation="Add an explicit condition/gateway before the approval node.",
                    confidence=Confidence.MEDIUM,
                    metadata={"constraint_id": constraint.id},
                )
            )
        elif condition_nodes and approval_nodes:
            if not any(understanding.has_order(condition.id, approval.id) for condition in condition_nodes for approval in approval_nodes):
                findings.append(
                    EvaluationFinding(
                        rule_id="WG-ALIGN-005",
                        dimension=EvaluationDimension.PROMPT_ALIGNMENT,
                        severity=ValidationSeverity.ERROR,
                        title="Approval is not on the conditional path",
                        message=f"Condition '{constraint.when}' does not lead to a human approval step.",
                        expected=f"condition -> {constraint.must}",
                        found="Detected condition and approval nodes are not connected in the expected order.",
                        why_it_matters="The guarded branch may bypass required review.",
                        remediation="Route the matching condition branch through human approval before continuing.",
                        confidence=Confidence.MEDIUM,
                        metadata={"constraint_id": constraint.id},
                    )
                )
    return findings


def _extra_behavior_findings(
    spec: RequirementSpec, workflow: Workflow, understanding: WorkflowUnderstanding
) -> list[EvaluationFinding]:
    findings: list[EvaluationFinding] = []
    matched_nodes = {
        node_id
        for requirement in spec.requirements
        for node in understanding.find_nodes(requirement.normalized, min_overlap=0.34)
        for node_id in [node.id]
    }
    for node in workflow.nodes:
        if node.type in {NodeType.TRIGGER, NodeType.END, NodeType.CONDITION, NodeType.GATEWAY}:
            continue
        if node.id not in matched_nodes and len(workflow.nodes) > 2:
            findings.append(
                EvaluationFinding(
                    rule_id="WG-ALIGN-006",
                    dimension=EvaluationDimension.PROMPT_ALIGNMENT,
                    severity=ValidationSeverity.INFO,
                    title="Potential extra workflow behavior",
                    message=f"Workflow node '{node.name}' was not clearly requested by the prompt.",
                    expected="Only behavior requested or implied by the prompt.",
                    found=f"Extra node: {node.name} ({node.type}).",
                    why_it_matters="Unrequested side effects can create compliance, cost, or reliability risk.",
                    node_id=node.id,
                    remediation="Confirm this step is intended or remove it.",
                    confidence=Confidence.LOW,
                )
            )
    return findings
