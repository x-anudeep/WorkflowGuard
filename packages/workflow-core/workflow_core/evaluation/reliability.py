from __future__ import annotations

import networkx as nx

from workflow_core.analysis.failure_paths import is_failure_edge
from workflow_core.canonical.models import NodeType, ValidationSeverity, Workflow
from workflow_core.evaluation.models import (
    Confidence,
    EvaluationDimension,
    EvaluationFinding,
)
from workflow_core.validation.graph import build_directed_graph


class ReliabilityAnalyzer:
    def analyze(self, workflow: Workflow) -> list[EvaluationFinding]:
        graph = build_directed_graph(workflow)
        findings: list[EvaluationFinding] = []
        for node in workflow.nodes:
            config = {key.lower(): value for key, value in node.configuration.items()}
            if node.type == NodeType.EXTERNAL_API:
                if not any("timeout" in key for key in config):
                    findings.append(
                        _finding(
                            "WG-REL-001",
                            ValidationSeverity.WARNING,
                            "External API call without timeout",
                            f"External API node '{node.name}' has no detectable timeout.",
                            "API calls should declare request timeouts.",
                            "No timeout field detected.",
                            node.id,
                            "Add a timeout appropriate for the integration.",
                            Confidence.MEDIUM,
                        )
                    )
                if not any("retry" in key or "retries" in key for key in config):
                    findings.append(
                        _finding(
                            "WG-REL-002",
                            ValidationSeverity.WARNING,
                            "External operation without retry policy",
                            f"External API node '{node.name}' has no detectable retry policy.",
                            "Transient external failures should have bounded retries.",
                            "No retry field detected.",
                            node.id,
                            "Add bounded retries with backoff and idempotency controls.",
                            Confidence.MEDIUM,
                        )
                    )
            if node.type == NodeType.LLM and not _has_failure_handling(workflow, node.id):
                findings.append(
                    _finding(
                        "WG-REL-003",
                        ValidationSeverity.WARNING,
                        "LLM call without failure path",
                        f"LLM node '{node.name}' has no obvious failure or fallback branch.",
                        "LLM calls should handle provider failure, malformed output, and timeout.",
                        "No failure/fallback path detected around the node.",
                        node.id,
                        "Add error handling, fallback, or human review for failed model calls.",
                        Confidence.LOW,
                    )
                )
            if graph.out_degree(node.id) == 1 and node.type in {NodeType.EXTERNAL_API, NodeType.DATABASE, NodeType.LLM}:
                findings.append(
                    _finding(
                        "WG-REL-004",
                        ValidationSeverity.INFO,
                        "Potential single point of failure",
                        f"Node '{node.name}' is a critical external/dependent operation with only one outgoing path.",
                        "Critical dependencies should have failure alternatives where appropriate.",
                        "Only one continuation path detected.",
                        node.id,
                        "Consider adding explicit failure handling or compensation.",
                        Confidence.LOW,
                    )
                )
        for cycle in list(nx.simple_cycles(graph)):
            has_condition = any(edge.condition for edge in workflow.edges if edge.source in cycle and edge.target in cycle)
            if not has_condition:
                findings.append(
                    EvaluationFinding(
                        rule_id="WG-REL-005",
                        dimension=EvaluationDimension.RELIABILITY,
                        severity=ValidationSeverity.WARNING,
                        title="Potentially unbounded loop",
                        message=f"Cycle {' -> '.join(cycle)} has no detectable exit condition.",
                        expected="Loops should have bounded exit conditions.",
                        found="Cycle without condition metadata.",
                        why_it_matters="Unbounded loops can cause repeated side effects, runaway cost, or stuck executions.",
                        path=cycle,
                        remediation="Add a bounded loop condition or maximum iteration guard.",
                        confidence=Confidence.MEDIUM,
                    )
                )
        return findings


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
        dimension=EvaluationDimension.RELIABILITY,
        severity=severity,
        title=title,
        message=message,
        expected=expected,
        found=found,
        why_it_matters="Reliability gaps can cause failed runs, duplicates, or silent data loss.",
        node_id=node_id,
        remediation=remediation,
        confidence=confidence,
    )


def _has_failure_handling(workflow: Workflow, node_id: str) -> bool:
    related_edges = [edge for edge in workflow.edges if edge.source == node_id or edge.target == node_id]
    return any(is_failure_edge(edge) for edge in related_edges)
