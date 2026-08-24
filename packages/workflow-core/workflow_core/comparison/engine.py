from __future__ import annotations

from workflow_core.canonical.models import Workflow
from workflow_core.comparison.models import VersionComparison


class VersionComparisonEngine:
    def compare(
        self,
        before: Workflow,
        after: Workflow,
        *,
        validation_before: float | None = None,
        validation_after: float | None = None,
        prompt_alignment_before: float | None = None,
        prompt_alignment_after: float | None = None,
        security_before: float | None = None,
        security_after: float | None = None,
        reliability_before: float | None = None,
        reliability_after: float | None = None,
        coverage_before: float | None = None,
        coverage_after: float | None = None,
        cost_before: float | None = None,
        cost_after: float | None = None,
    ) -> VersionComparison:
        before_nodes = {node.id: node for node in before.nodes}
        after_nodes = {node.id: node for node in after.nodes}
        before_edges = {edge.id: edge for edge in before.edges}
        after_edges = {edge.id: edge for edge in after.edges}
        changed = [
            node_id
            for node_id in sorted(before_nodes.keys() & after_nodes.keys())
            if before_nodes[node_id].configuration != after_nodes[node_id].configuration
            or before_nodes[node_id].provider != after_nodes[node_id].provider
            or before_nodes[node_id].operation != after_nodes[node_id].operation
        ]
        return VersionComparison(
            workflow_a_id=before.id,
            workflow_b_id=after.id,
            nodes_added=sorted(after_nodes.keys() - before_nodes.keys()),
            nodes_removed=sorted(before_nodes.keys() - after_nodes.keys()),
            edges_added=sorted(after_edges.keys() - before_edges.keys()),
            edges_removed=sorted(before_edges.keys() - after_edges.keys()),
            configuration_changed=changed,
            validation_score_delta=_delta(validation_before, validation_after),
            prompt_alignment_delta=_delta(prompt_alignment_before, prompt_alignment_after),
            security_delta=_delta(security_before, security_after),
            reliability_delta=_delta(reliability_before, reliability_after),
            test_coverage_delta=_delta(coverage_before, coverage_after),
            estimated_cost_delta=_delta(cost_before, cost_after),
        )


def _delta(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    return round(after - before, 4)
