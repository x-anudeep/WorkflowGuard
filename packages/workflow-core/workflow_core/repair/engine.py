from __future__ import annotations

from workflow_core.canonical.models import Node, NodeType, Workflow
from workflow_core.repair.models import PatchOperation, RepairPatch, RepairPatchOperation


class DeterministicRepairEngine:
    def propose(self, workflow: Workflow, finding: dict | None = None) -> RepairPatch:
        finding_text = " ".join(str(value) for value in (finding or {}).values()).lower()
        target = _target_node(workflow, finding_text)
        if target and ("retry" in finding_text or target.type in {NodeType.EXTERNAL_API, NodeType.DATABASE, NodeType.LLM}):
            return RepairPatch(
                finding_id=str((finding or {}).get("id") or (finding or {}).get("rule_id") or ""),
                title=f"Add timeout and retry handling to {target.name}",
                summary="Adds bounded timeout/retry configuration and preserves existing workflow behavior.",
                operations=[
                    RepairPatchOperation(
                        op=PatchOperation.UPDATE_NODE_CONFIGURATION,
                        node_id=target.id,
                        configuration_patch={"timeout_seconds": target.configuration.get("timeout_seconds", 30), "retries": max(int(target.configuration.get("retries") or 0), 2)},
                        rationale="External and AI operations should have bounded retry and timeout behavior.",
                    )
                ],
                safety_notes=["Patch updates configuration only; it does not remove nodes, edges, tests, or requirements."],
            )
        return RepairPatch(
            finding_id=str((finding or {}).get("id") or (finding or {}).get("rule_id") or ""),
            title="Add generic resilience configuration",
            summary="Adds timeout and retry defaults to the first external dependency node.",
            operations=[
                RepairPatchOperation(
                    op=PatchOperation.UPDATE_NODE_CONFIGURATION,
                    node_id=target.id if target else workflow.nodes[0].id,
                    configuration_patch={"timeout_seconds": 30, "retries": 2},
                    rationale="Bounded dependency behavior improves reliability without changing destinations.",
                )
            ],
            safety_notes=["Patch updates configuration only; review before accepting."],
        )


class RepairPatchApplier:
    def apply(self, workflow: Workflow, patch: RepairPatch) -> Workflow:
        candidate = workflow.model_copy(deep=True)
        nodes = {node.id: node for node in candidate.nodes}
        edges = {edge.id: edge for edge in candidate.edges}
        for operation in patch.operations:
            if operation.op == PatchOperation.UPDATE_NODE_CONFIGURATION:
                if not operation.node_id or operation.node_id not in nodes:
                    raise ValueError(f"Unknown node for configuration patch: {operation.node_id}")
                node = nodes[operation.node_id]
                node.configuration.update(operation.configuration_patch)
            elif operation.op == PatchOperation.ADD_NODE:
                if operation.node is None:
                    raise ValueError("add_node operation requires node")
                if operation.node.id in nodes:
                    raise ValueError(f"Node already exists: {operation.node.id}")
                candidate.nodes.append(operation.node)
                nodes[operation.node.id] = operation.node
            elif operation.op == PatchOperation.ADD_EDGE:
                if operation.edge is None:
                    raise ValueError("add_edge operation requires edge")
                if operation.edge.id in edges:
                    raise ValueError(f"Edge already exists: {operation.edge.id}")
                candidate.edges.append(operation.edge)
                edges[operation.edge.id] = operation.edge
            elif operation.op == PatchOperation.REMOVE_EDGE:
                if not operation.edge_id or operation.edge_id not in edges:
                    raise ValueError(f"Unknown edge for remove_edge: {operation.edge_id}")
                candidate.edges = [edge for edge in candidate.edges if edge.id != operation.edge_id]
                edges.pop(operation.edge_id, None)
        patch.behavior_changes = safety_flags(workflow, candidate)
        return candidate


def safety_flags(before: Workflow, after: Workflow) -> list[str]:
    flags: list[str] = []
    before_destinations = _destinations(before)
    after_destinations = _destinations(after)
    new_destinations = sorted(after_destinations - before_destinations)
    if new_destinations:
        flags.append(f"Introduces new external destinations: {', '.join(new_destinations)}")
    before_approvals = {node.id for node in before.nodes if node.type == NodeType.HUMAN_APPROVAL}
    after_approvals = {node.id for node in after.nodes if node.type == NodeType.HUMAN_APPROVAL}
    if not before_approvals <= after_approvals:
        flags.append("Removes or weakens human approval requirements.")
    if len(after.nodes) < len(before.nodes):
        flags.append("Removes workflow nodes.")
    return flags


def _target_node(workflow: Workflow, finding_text: str) -> Node | None:
    for node in workflow.nodes:
        if node.id.lower() in finding_text or node.name.lower() in finding_text:
            return node
    return next((node for node in workflow.nodes if node.type in {NodeType.EXTERNAL_API, NodeType.DATABASE, NodeType.LLM}), None)


def _destinations(workflow: Workflow) -> set[str]:
    return {
        f"{node.provider}:{node.configuration.get('url') or node.operation}"
        for node in workflow.nodes
        if node.type in {NodeType.EXTERNAL_API, NodeType.DATABASE, NodeType.EMAIL}
    }
