from __future__ import annotations

import networkx as nx

from workflow_core.canonical.models import Node, Workflow
from workflow_core.evaluation.text import normalize_text
from workflow_core.validation.graph import build_directed_graph


class WorkflowUnderstanding:
    def __init__(self, workflow: Workflow) -> None:
        self.workflow = workflow
        self.graph = build_directed_graph(workflow)

    def node_text(self, node: Node) -> str:
        pieces = [
            node.id,
            node.name,
            str(node.type),
            node.subtype or "",
            node.provider or "",
            node.operation or "",
            " ".join(f"{key} {value}" for key, value in node.configuration.items()),
        ]
        return normalize_text(" ".join(str(piece) for piece in pieces if piece))

    def find_nodes(self, query: str, min_overlap: float = 0.34) -> list[Node]:
        matches: list[tuple[float, Node]] = []
        for node in self.workflow.nodes:
            overlap = _node_overlap(query, self.node_text(node))
            if overlap >= min_overlap:
                matches.append((overlap, node))
        return [node for _score, node in sorted(matches, key=lambda item: item[0], reverse=True)]

    def has_order(self, source_id: str, target_id: str) -> bool:
        return source_id in self.graph and target_id in self.graph and nx.has_path(self.graph, source_id, target_id)

    def paths_between(self, source_id: str, target_id: str, limit: int = 3) -> list[list[str]]:
        if source_id not in self.graph or target_id not in self.graph:
            return []
        try:
            return [path for _, path in zip(range(limit), nx.shortest_simple_paths(self.graph, source_id, target_id))]
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []


def _node_overlap(query: str, node_text: str) -> float:
    query_tokens = set(normalize_text(query).split())
    node_tokens = set(node_text.split())
    if not query_tokens:
        return 0
    overlap = len(query_tokens & node_tokens) / len(query_tokens)
    if any(token in node_tokens for token in query_tokens):
        overlap += 0.12
    return min(overlap, 1.0)
