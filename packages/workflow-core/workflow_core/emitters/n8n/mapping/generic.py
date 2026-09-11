"""Mapping generic-JSON nodes onto n8n nodes.

The generic format has no fixed schema, so the mapping keys off whatever the node happens to
carry. `endpoint`/`method`/`headers`/`body` on an integration node are common enough - and
precise enough - to be worth reproducing; anything else falls through to the emitter's
pass-through, which warns.
"""

from __future__ import annotations

import json
from typing import Any

from workflow_core.canonical.models import Node, NodeType
from workflow_core.emitters.n8n.mapping.models import MappedNode, request_timeout_ms

__all__ = ["map_generic_node"]

_INTEGRATION = frozenset({NodeType.EXTERNAL_API, NodeType.DATABASE, NodeType.EMAIL, NodeType.LLM})


def map_generic_node(node: Node, mock_url: str) -> MappedNode | None:
    if node.type in _INTEGRATION:
        return _integration(node, mock_url)
    if node.type == NodeType.ACTION and node.configuration.get("fields"):
        return _select_fields(node)
    return None


def _integration(node: Node, mock_url: str) -> MappedNode:
    """Reproduce the request, not its destination.

    The declared endpoint is recorded in the body rather than used, so a report can say what the
    workflow intended to call while the call itself cannot leave the machine.
    """
    config = node.configuration
    payload: dict[str, Any] = {}
    body = config.get("body") or config.get("payload")
    if isinstance(body, dict):
        payload.update(body)
    endpoint = config.get("endpoint") or config.get("url")
    if endpoint:
        payload["__wg_intended_url"] = str(endpoint)

    parameters: dict[str, Any] = {
        "method": str(config.get("method") or "POST").upper(),
        "url": mock_url,
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify(Object.assign({}, $json, " + json.dumps(payload) + ")) }}",
        "options": {
            "response": {"response": {"neverError": False}},
            "timeout": request_timeout_ms(node),
        },
    }
    headers = config.get("headers")
    if isinstance(headers, dict) and headers:
        parameters["sendHeaders"] = True
        parameters["specifyHeaders"] = "keypair"
        parameters["headerParameters"] = {
            "parameters": [{"name": str(k), "value": str(v)} for k, v in headers.items()]
        }
    return MappedNode(
        type="n8n-nodes-base.httpRequest", type_version=4.2, parameters=parameters, mocked=True
    )


def _select_fields(node: Node) -> MappedNode:
    """A transform declaring `fields` -> a Set node that names them.

    The values are not computed - nothing in the canonical model says how - but naming the
    fields means a downstream condition referencing one resolves rather than reading undefined.
    """
    fields = node.configuration.get("fields")
    names = [str(f) for f in fields if isinstance(f, (str, int))] if isinstance(fields, list) else []
    if not names:
        return MappedNode(type="n8n-nodes-base.noOp", type_version=1)
    return MappedNode(
        type="n8n-nodes-base.set",
        type_version=3.4,
        parameters={
            "assignments": {
                "assignments": [
                    {
                        "id": f"f{index}",
                        "name": name,
                        "type": "string",
                        "value": "={{ $json[" + json.dumps(name) + "] ?? null }}",
                    }
                    for index, name in enumerate(names)
                ]
            },
            "includeOtherFields": True,
            "options": {},
        },
        warning=(
            f"Node {node.id!r} declares the fields it produces but not how; they are carried "
            f"through rather than computed."
        ),
    )
