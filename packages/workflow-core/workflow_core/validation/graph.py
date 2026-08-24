from __future__ import annotations

import networkx as nx

from workflow_core.canonical.models import Workflow


def build_directed_graph(workflow: Workflow) -> nx.DiGraph:
    graph = nx.DiGraph()
    for node in workflow.nodes:
        graph.add_node(node.id, node=node)
    for edge in workflow.edges:
        graph.add_edge(edge.source, edge.target, edge=edge)
    return graph
