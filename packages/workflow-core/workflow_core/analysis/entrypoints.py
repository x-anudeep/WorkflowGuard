"""Diagnosing workflows whose declared start node is not where the flow begins.

A generator can emit a `Start` node and then forget to connect it, leaving the real
chain orphaned beside it. `Workflow.start_node_ids` prefers typed trigger nodes
exclusively, so the analysis anchors on the dangling start, reaches almost nothing, and
reports every other node as unreachable.

This module recognises that shape and describes it. It deliberately produces advice
rather than findings: changing which node counts as the start would move structural,
reliability, and coverage scores for every workflow already in the system, and that is
a decision for a human, not a side effect of a diagnostic.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from workflow_core.canonical.models import Workflow


@dataclass(frozen=True)
class EntrypointDiagnosis:
    """A better entry point exists than the one the workflow declares."""

    declared_start_ids: tuple[str, ...]
    declared_start_names: tuple[str, ...]
    declared_reach: int
    candidate_id: str
    candidate_name: str
    candidate_reach: int
    total_nodes: int

    @property
    def suggestion(self) -> str:
        declared = ", ".join(f"'{name}'" for name in self.declared_start_names[:3]) or "none"
        return (
            f"The declared start node ({declared}) reaches only {self.declared_reach} of "
            f"{self.total_nodes} nodes, but '{self.candidate_name}' heads a chain of "
            f"{self.candidate_reach}. It looks like the start node was never connected to the "
            f"flow. Adding that edge would make the rest of the workflow analysable; until "
            f"then, results here describe only the part that is reachable."
        )


def diagnose_entrypoints(workflow: Workflow) -> EntrypointDiagnosis | None:
    """Detect a declared start that reaches far less of the graph than another node would.

    Returns None when the declared start is fine, when no better candidate exists, or
    when the candidate is not a clear improvement - a marginal difference is more likely
    to be a legitimate multi-entry workflow than a wiring mistake.
    """
    if not workflow.nodes:
        return None

    declared = tuple(sorted(workflow.start_node_ids))
    total = len(workflow.nodes)
    declared_reach = len(_reachable(workflow, declared))
    if declared_reach >= total:
        return None

    incoming = {edge.target for edge in workflow.edges}
    candidates = [node for node in workflow.nodes if node.id not in incoming and node.id not in declared]
    if not candidates:
        return None

    best = max(candidates, key=lambda node: len(_reachable(workflow, (node.id,))))
    best_reach = len(_reachable(workflow, (best.id,)))
    # Require a decisive improvement so a genuine second entry point is not reported as a
    # defect. Reaching at least twice as much, and most of the graph, is decisive.
    if best_reach <= declared_reach * 2 or best_reach * 2 < total:
        return None

    names_by_id = {node.id: node.name for node in workflow.nodes}
    return EntrypointDiagnosis(
        declared_start_ids=declared,
        declared_start_names=tuple(names_by_id.get(node_id, node_id) for node_id in declared),
        declared_reach=declared_reach,
        candidate_id=best.id,
        candidate_name=best.name,
        candidate_reach=best_reach,
        total_nodes=total,
    )


def _reachable(workflow: Workflow, roots: tuple[str, ...]) -> set[str]:
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in workflow.edges:
        outgoing[edge.source].append(edge.target)
    seen = set(roots)
    stack = list(roots)
    while stack:
        for target in outgoing[stack.pop()]:
            if target not in seen:
                seen.add(target)
                stack.append(target)
    return seen
