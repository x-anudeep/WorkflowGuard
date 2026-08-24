from __future__ import annotations

from workflow_core.canonical.models import Workflow
from workflow_core.evaluation.models import RequirementSpec
from workflow_core.testing.models import CoverageResult, WorkflowTest, WorkflowTestRun


class CoverageCalculator:
    def calculate(
        self,
        workflow: Workflow,
        runs: list[WorkflowTestRun],
        tests: list[WorkflowTest],
        requirement_spec: RequirementSpec | None = None,
    ) -> CoverageResult:
        covered_nodes = sorted({node_id for run in runs for node_id in run.simulation.execution_order})
        covered_edges = sorted({edge_id for run in runs for edge_id in run.simulation.executed_edges})
        branch_edges = [edge for edge in workflow.edges if edge.condition or edge.label]
        covered_branch_edges = [edge_id for edge_id in covered_edges if any(edge.id == edge_id for edge in branch_edges)]
        covered_requirements = sorted({test.linked_requirement_id for test in tests if test.linked_requirement_id})
        requirement_total = len(requirement_spec.requirements) if requirement_spec else 0

        node_coverage = _pct(len(covered_nodes), len(workflow.nodes))
        edge_coverage = _pct(len(covered_edges), len(workflow.edges))
        branch_coverage = _pct(len(covered_branch_edges), len(branch_edges))
        requirement_coverage = _pct(len(covered_requirements), requirement_total) if requirement_total else 100.0
        overall = round((node_coverage + edge_coverage + branch_coverage + requirement_coverage) / 4, 2)
        return CoverageResult(
            node_coverage=node_coverage,
            edge_coverage=edge_coverage,
            branch_coverage=branch_coverage,
            requirement_coverage=requirement_coverage,
            overall_coverage=overall,
            covered_nodes=covered_nodes,
            covered_edges=covered_edges,
            covered_requirements=covered_requirements,
            calculation={
                "nodes": {"covered": len(covered_nodes), "total": len(workflow.nodes)},
                "edges": {"covered": len(covered_edges), "total": len(workflow.edges)},
                "branches": {"covered": len(covered_branch_edges), "total": len(branch_edges)},
                "requirements": {"covered": len(covered_requirements), "total": requirement_total},
            },
        )


def _pct(covered: int, total: int) -> float:
    if total == 0:
        return 100.0
    return round((covered / total) * 100, 2)
