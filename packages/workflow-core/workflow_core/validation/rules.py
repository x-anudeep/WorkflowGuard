from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter

import networkx as nx

from workflow_core.canonical.models import (
    NodeType,
    ValidationFinding,
    ValidationSeverity,
    Workflow,
)
from workflow_core.validation.graph import build_directed_graph


class ValidationRule(ABC):
    rule_id: str
    title: str

    @abstractmethod
    def evaluate(self, workflow: Workflow, graph: nx.DiGraph) -> list[ValidationFinding]:
        raise NotImplementedError


class EmptyWorkflowRule(ValidationRule):
    rule_id = "WG-GRAPH-001"
    title = "Empty workflow"

    def evaluate(self, workflow: Workflow, graph: nx.DiGraph) -> list[ValidationFinding]:
        if workflow.nodes:
            return []
        return [
            ValidationFinding(
                rule_id=self.rule_id,
                severity=ValidationSeverity.CRITICAL,
                title=self.title,
                message="The workflow contains no nodes.",
                remediation="Add at least one trigger/start node and one action or terminal node.",
            )
        ]


class DuplicateNodeIdRule(ValidationRule):
    rule_id = "WG-GRAPH-002"
    title = "Duplicate node ID"

    def evaluate(self, workflow: Workflow, graph: nx.DiGraph) -> list[ValidationFinding]:
        counts = Counter(node.id for node in workflow.nodes)
        return [
            ValidationFinding(
                rule_id=self.rule_id,
                severity=ValidationSeverity.CRITICAL,
                node_id=node_id,
                title=self.title,
                message=f"Node ID '{node_id}' appears {count} times.",
                remediation="Ensure every node has a stable unique ID.",
            )
            for node_id, count in counts.items()
            if count > 1
        ]


class InvalidEdgeReferenceRule(ValidationRule):
    rule_id = "WG-GRAPH-003"
    title = "Invalid edge reference"

    def evaluate(self, workflow: Workflow, graph: nx.DiGraph) -> list[ValidationFinding]:
        node_ids = {node.id for node in workflow.nodes}
        findings: list[ValidationFinding] = []
        for edge in workflow.edges:
            if edge.source not in node_ids:
                findings.append(
                    ValidationFinding(
                        rule_id=self.rule_id,
                        severity=ValidationSeverity.ERROR,
                        edge_id=edge.id,
                        title=self.title,
                        message=f"Edge source '{edge.source}' does not reference an existing node.",
                        remediation="Update the edge source or add the missing node.",
                    )
                )
            if edge.target not in node_ids:
                findings.append(
                    ValidationFinding(
                        rule_id=self.rule_id,
                        severity=ValidationSeverity.ERROR,
                        edge_id=edge.id,
                        title=self.title,
                        message=f"Edge target '{edge.target}' does not reference an existing node.",
                        remediation="Update the edge target or add the missing node.",
                    )
                )
        return findings


class StartAndTerminalRule(ValidationRule):
    rule_id = "WG-GRAPH-004"
    title = "Missing start or terminal node"

    def evaluate(self, workflow: Workflow, graph: nx.DiGraph) -> list[ValidationFinding]:
        if not workflow.nodes:
            return []
        findings: list[ValidationFinding] = []
        if not workflow.start_node_ids:
            findings.append(
                ValidationFinding(
                    rule_id=self.rule_id,
                    severity=ValidationSeverity.ERROR,
                    title="Missing start node",
                    message="The workflow has no trigger/start node and no node without incoming edges.",
                    remediation="Add an explicit trigger/start node or connect the graph from a valid entry point.",
                )
            )
        if not workflow.terminal_node_ids:
            findings.append(
                ValidationFinding(
                    rule_id=self.rule_id,
                    severity=ValidationSeverity.WARNING,
                    title="Missing terminal node",
                    message="The workflow has no end node and no node without outgoing edges.",
                    remediation="Add an explicit end node or a clear terminal action.",
                )
            )
        return findings


class ReachabilityRule(ValidationRule):
    rule_id = "WG-GRAPH-005"
    title = "Unreachable node"

    def evaluate(self, workflow: Workflow, graph: nx.DiGraph) -> list[ValidationFinding]:
        if not workflow.nodes or not workflow.start_node_ids:
            return []
        reachable: set[str] = set()
        for start_id in workflow.start_node_ids:
            if start_id in graph:
                reachable.add(start_id)
                reachable.update(nx.descendants(graph, start_id))
        return [
            ValidationFinding(
                rule_id=self.rule_id,
                severity=ValidationSeverity.ERROR,
                node_id=node.id,
                title=self.title,
                message="This node cannot be reached from any workflow start node.",
                remediation="Connect the node to a path that begins at a trigger/start node or remove it.",
            )
            for node in workflow.nodes
            if node.id not in reachable
        ]


class OrphanNodeRule(ValidationRule):
    rule_id = "WG-GRAPH-006"
    title = "Orphan node"

    def evaluate(self, workflow: Workflow, graph: nx.DiGraph) -> list[ValidationFinding]:
        return [
            ValidationFinding(
                rule_id=self.rule_id,
                severity=ValidationSeverity.ERROR,
                node_id=node.id,
                title=self.title,
                message="This node is disconnected from all workflow paths.",
                remediation="Connect this node or remove it.",
            )
            for node in workflow.nodes
            if len(workflow.nodes) > 1 and graph.in_degree(node.id) == 0 and graph.out_degree(node.id) == 0
        ]


class DeadEndRule(ValidationRule):
    rule_id = "WG-GRAPH-007"
    title = "Dead-end path"

    def evaluate(self, workflow: Workflow, graph: nx.DiGraph) -> list[ValidationFinding]:
        terminal_ids = workflow.terminal_node_ids
        return [
            ValidationFinding(
                rule_id=self.rule_id,
                severity=ValidationSeverity.WARNING,
                node_id=node.id,
                title=self.title,
                message="Execution can stop here without reaching an explicit terminal node.",
                remediation="Connect this node to a terminal node or mark it as an end node.",
            )
            for node in workflow.nodes
            if graph.out_degree(node.id) == 0 and node.id not in terminal_ids and node.type != NodeType.END
        ]


class SuspiciousCycleRule(ValidationRule):
    rule_id = "WG-GRAPH-008"
    title = "Suspicious cycle"

    def evaluate(self, workflow: Workflow, graph: nx.DiGraph) -> list[ValidationFinding]:
        return [
            ValidationFinding(
                rule_id=self.rule_id,
                severity=ValidationSeverity.WARNING,
                title=self.title,
                message=f"Cycle detected: {' -> '.join(cycle)}.",
                remediation="Confirm the loop has a bounded exit condition.",
                metadata={"cycle": cycle},
            )
            for cycle in nx.simple_cycles(graph)
        ]


class DisconnectedComponentsRule(ValidationRule):
    rule_id = "WG-GRAPH-009"
    title = "Disconnected graph components"

    def evaluate(self, workflow: Workflow, graph: nx.DiGraph) -> list[ValidationFinding]:
        if len(workflow.nodes) <= 1:
            return []
        components = list(nx.weakly_connected_components(graph))
        if len(components) <= 1:
            return []
        return [
            ValidationFinding(
                rule_id=self.rule_id,
                severity=ValidationSeverity.ERROR,
                title=self.title,
                message=f"The workflow has {len(components)} disconnected graph components.",
                remediation="Connect isolated components into the main workflow or split them into separate workflows.",
                metadata={"components": [sorted(component) for component in components]},
            )
        ]


class MissingConfigurationRule(ValidationRule):
    rule_id = "WG-CONFIG-001"
    title = "Missing required node configuration"

    def evaluate(self, workflow: Workflow, graph: nx.DiGraph) -> list[ValidationFinding]:
        configurable_types = {
            NodeType.ACTION,
            NodeType.EXTERNAL_API,
            NodeType.DATABASE,
            NodeType.LLM,
            NodeType.TASK,
            NodeType.HUMAN_APPROVAL,
        }
        return [
            ValidationFinding(
                rule_id=self.rule_id,
                severity=ValidationSeverity.WARNING,
                node_id=node.id,
                title=self.title,
                message="This executable node has no detectable configuration.",
                remediation="Add operation parameters, credentials references, schemas, or other required configuration.",
            )
            for node in workflow.nodes
            if node.type in configurable_types and not node.configuration
        ]


class InvalidConditionRule(ValidationRule):
    rule_id = "WG-CONDITION-001"
    title = "Invalid condition"

    def evaluate(self, workflow: Workflow, graph: nx.DiGraph) -> list[ValidationFinding]:
        return [
            ValidationFinding(
                rule_id=self.rule_id,
                severity=ValidationSeverity.WARNING,
                edge_id=edge.id,
                title=self.title,
                message="This edge has an empty condition expression.",
                remediation="Remove the condition or provide a valid expression.",
            )
            for edge in workflow.edges
            if edge.condition is not None and not edge.condition.strip()
        ]


DEFAULT_RULES: list[ValidationRule] = [
    EmptyWorkflowRule(),
    DuplicateNodeIdRule(),
    InvalidEdgeReferenceRule(),
    StartAndTerminalRule(),
    ReachabilityRule(),
    OrphanNodeRule(),
    DeadEndRule(),
    SuspiciousCycleRule(),
    DisconnectedComponentsRule(),
    MissingConfigurationRule(),
    InvalidConditionRule(),
]


def graph_for_workflow(workflow: Workflow) -> nx.DiGraph:
    return build_directed_graph(workflow)
