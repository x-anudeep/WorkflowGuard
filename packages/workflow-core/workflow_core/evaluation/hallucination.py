from __future__ import annotations

from workflow_core.canonical.models import NodeType, ValidationSeverity, Workflow
from workflow_core.evaluation.models import (
    Confidence,
    EvaluationDimension,
    EvaluationFinding,
)
from workflow_core.validation.graph import build_directed_graph

GROUNDING_TERMS = ("context", "retrieval", "knowledge_base", "rag", "source", "document", "citation")
SCHEMA_TERMS = ("schema", "output_schema", "json_schema", "format", "structured_output")
VERIFICATION_TERMS = ("verify", "review", "validate", "confirm", "check", "citation", "grounded", "fact")

SIDE_EFFECTING_TYPES = {NodeType.EXTERNAL_API, NodeType.DATABASE, NodeType.EMAIL, NodeType.ACTION}


class HallucinationAnalyzer:
    """Static, deterministic checks for LLM nodes that can propagate unverified
    or ungrounded model output. Not a semantic fact-check -- it flags structural
    risk factors (no grounding source, no output constraint, no verification gate
    before a side-effecting step), the same way reliability.py flags missing
    timeouts rather than proving a call will fail.
    """

    def analyze(self, workflow: Workflow) -> list[EvaluationFinding]:
        graph = build_directed_graph(workflow)
        findings: list[EvaluationFinding] = []
        for node in workflow.nodes:
            if node.type != NodeType.LLM:
                continue
            config = {key.lower(): value for key, value in node.configuration.items()}

            if not any(term in key for key in config for term in GROUNDING_TERMS):
                findings.append(
                    _finding(
                        "WG-HAL-001",
                        ValidationSeverity.WARNING,
                        "LLM call without a grounding source",
                        f"LLM node '{node.name}' has no detectable retrieval, context, or knowledge-base input.",
                        "Model calls that assert facts should be grounded in retrieved or supplied context.",
                        "No grounding/retrieval field detected.",
                        node.id,
                        "Attach a retrieval/context source, or constrain the node to non-factual generation.",
                        Confidence.LOW,
                    )
                )

            if not any(term in key for key in config for term in SCHEMA_TERMS):
                findings.append(
                    _finding(
                        "WG-HAL-002",
                        ValidationSeverity.INFO,
                        "LLM output has no structural constraint",
                        f"LLM node '{node.name}' has no detectable output schema or format constraint.",
                        "Constraining output shape reduces (but does not eliminate) fabricated or malformed fields reaching downstream steps.",
                        "No schema/format field detected.",
                        node.id,
                        "Add a JSON schema or structured-output constraint to the model call.",
                        Confidence.LOW,
                    )
                )

            if _feeds_side_effect_unverified(workflow, graph, node.id):
                findings.append(
                    _finding(
                        "WG-HAL-003",
                        ValidationSeverity.WARNING,
                        "Unverified LLM output reaches a side-effecting step",
                        f"LLM node '{node.name}' has a path to an external API, database, email, or action node "
                        "with no human approval or verification step in between.",
                        "Output that can trigger real-world side effects should be checked before it does.",
                        "No verification/approval node or edge detected between the LLM call and the side effect.",
                        node.id,
                        "Insert a human approval, validation, or fact-check step before the side-effecting node.",
                        Confidence.MEDIUM,
                    )
                )
        return findings


def _feeds_side_effect_unverified(workflow: Workflow, graph, node_id: str) -> bool:
    """True if some side-effecting node is reachable from `node_id` by a path
    that never crosses a human-approval/verification gate.
    """
    if node_id not in graph:
        return False
    visited: set[str] = set()
    stack = list(graph.successors(node_id))
    while stack:
        current_id = stack.pop()
        if current_id in visited:
            continue
        visited.add(current_id)

        incoming = [edge for edge in workflow.edges if edge.target == current_id]
        gated = any(
            (edge.label and any(term in edge.label.lower() for term in VERIFICATION_TERMS))
            or (edge.condition and any(term in edge.condition.lower() for term in VERIFICATION_TERMS))
            for edge in incoming
        )
        current = next((n for n in workflow.nodes if n.id == current_id), None)
        if current is None:
            continue
        if current.type == NodeType.HUMAN_APPROVAL or _is_verification_gate(current) or gated:
            # This branch is verified before it reaches `current` -- don't
            # expand past it, and don't count `current` itself as an
            # unverified hit even if it happens to be side-effecting.
            continue
        if current.type in SIDE_EFFECTING_TYPES:
            return True
        stack.extend(graph.successors(current_id))
    return False


def _is_verification_gate(node) -> bool:
    config = {key.lower(): value for key, value in node.configuration.items()}
    return any(term in key for key in config for term in VERIFICATION_TERMS) or any(
        term in node.name.lower() for term in VERIFICATION_TERMS
    )


def _finding(
    rule_id: str,
    severity: ValidationSeverity,
    title: str,
    message: str,
    expected: str,
    found: str,
    node_id: str,
    remediation: str,
    confidence: Confidence,
) -> EvaluationFinding:
    return EvaluationFinding(
        rule_id=rule_id,
        dimension=EvaluationDimension.HALLUCINATION,
        severity=severity,
        title=title,
        message=message,
        expected=expected,
        found=found,
        why_it_matters="Ungrounded or unverified model output can introduce fabricated facts, fields, or actions into a workflow.",
        node_id=node_id,
        remediation=remediation,
        confidence=confidence,
    )
