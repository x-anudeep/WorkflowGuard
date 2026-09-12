"""Per-format mappings from a canonical node to a real n8n node.

The emitter knows how to build a *graph*; these know what each node in it should actually be.
They are kept per source format because the same canonical `NodeType` carries entirely
different configuration depending on where it came from - a qubi `Http` node names its method,
url, headers and body, while a BPMN `serviceTask` carries nothing at all.

A mapping returns None when it has nothing better to offer, and the emitter falls back to a
pass-through that warns. Silence is never the answer: a node compiled as something other than
what it is must say so, or a run implies it exercised work it did not.
"""

from __future__ import annotations

from collections.abc import Callable

from workflow_core.canonical.models import Node, SourceFormat
from workflow_core.emitters.n8n.mapping.bpmn import map_bpmn_node
from workflow_core.emitters.n8n.mapping.generic import map_generic_node
from workflow_core.emitters.n8n.mapping.models import MappedNode
from workflow_core.emitters.n8n.mapping.qubi import map_qubi_node

__all__ = ["MappedNode", "map_node"]

_BY_FORMAT: dict[str, Callable[[Node, str], MappedNode | None]] = {
    SourceFormat.QUBI.value: map_qubi_node,
    SourceFormat.BPMN.value: map_bpmn_node,
    SourceFormat.GENERIC_JSON.value: map_generic_node,
}


def map_node(node: Node, source_format: str, mock_url: str) -> MappedNode | None:
    """The n8n node for ``node``, or None to let the emitter fall back.

    ``mock_url`` is where any outbound call must be sent. Mappings reproduce a request's method,
    headers and body faithfully but never its destination: an emitted workflow must not be able
    to reach a real service, whatever the uploaded file asked for.
    """
    mapper = _BY_FORMAT.get(str(source_format))
    return mapper(node, mock_url) if mapper else None
