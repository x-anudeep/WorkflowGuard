"""Mapping BPMN elements onto n8n nodes.

There is almost nothing to map, and that is a finding rather than an omission: the BPMN parser
records an element's `subtype` (`serviceTask`, `userTask`, `scriptTask`, ...) but extracts no
parameters, so a `serviceTask` arrives with an empty configuration. No emitter can invent the
endpoint it was meant to call.

So BPMN fidelity is bounded by the parser, not by this module. Until the parser reads the
implementation details BPMN carries - `camunda:`/`zeebe:` extension attributes, `bpmn:script`
bodies - a BPMN workflow executes as a faithful *control-flow* skeleton with mocked work at
every node. The structural mapping still matters, and it is what the emitter already does:
gateways become real IF/Switch nodes, so branching and conditions are genuinely exercised.
"""

from __future__ import annotations

from workflow_core.canonical.models import Node
from workflow_core.emitters.n8n.mapping.models import MappedNode

__all__ = ["map_bpmn_node"]


def map_bpmn_node(node: Node, _mock_url: str) -> MappedNode | None:
    subtype = str(node.subtype or "").lower()
    if subtype == "scripttask":
        # Same decision as qubi's Code: WorkflowGuard does not execute the contents of an
        # uploaded file. The parser does not extract the script body in any case.
        return MappedNode(
            type="n8n-nodes-base.noOp",
            type_version=1,
            warning=(
                f"Node {node.id!r} is a scriptTask; its script was not executed, so the run "
                f"covers the path through it but not what it computes."
            ),
        )
    return None
