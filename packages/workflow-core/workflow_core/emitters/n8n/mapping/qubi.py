"""Mapping qubi nodes onto n8n nodes.

Grounded in 30 real qubi exports (311 nodes). The distribution matters, because it says where
fidelity is worth the effort:

===============  =====  ==========================================================
subtype          count  what it needs
===============  =====  ==========================================================
Http               130  method, url, headers, body - the bulk of all fidelity
Branch              46  handled by the emitter's router, not here
Code                35  **not executed** - see the note below
Start / End         60  structural
Agent               26  an LLM call; mocked, never sent to a real provider
HitlTask            25  the emitter's approval shim
DocumentAI           6  an LLM call
JsonParser           5  deterministic reshaping
Assign               4  variable assignment
TextParser           3  regex extraction
RPA                  1  an external automation; mocked
===============  =====  ==========================================================

**Code nodes are deliberately not executed.** Compiling them to n8n's Code node would mean
running uploaded code, which is a change to what WorkflowGuard is - it has never executed the
contents of an uploaded file, only modelled it - rather than a fidelity improvement. It also
depends on n8n's own sandbox being enabled, which is not a safe assumption. They compile to a
pass-through that says what it skipped.
"""

from __future__ import annotations

import json
from typing import Any

from workflow_core.canonical.models import Node
from workflow_core.emitters.n8n.mapping.models import MappedNode, request_timeout_ms

__all__ = ["map_qubi_node"]


def map_qubi_node(node: Node, mock_url: str) -> MappedNode | None:
    subtype = str(node.subtype or "").lower()
    handler = _HANDLERS.get(subtype)
    return handler(node, mock_url) if handler else None


def _http(node: Node, mock_url: str) -> MappedNode:
    """A real HTTP call, faithful in everything but where it goes.

    Method, headers and body are reproduced so the recorded request shows what the workflow
    would actually have sent; the URL is the mock, so it cannot reach a real service. The
    original is kept in the body under `__wg_intended_url` for the same reason - the report
    should be able to say what the workflow meant to call.
    """
    config = node.configuration
    body = config.get("body")
    parameters: dict[str, Any] = {
        "method": str(config.get("method") or "POST").upper(),
        "url": mock_url,
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": _json_body(body, intended_url=str(config.get("url") or "")),
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
        type="n8n-nodes-base.httpRequest",
        type_version=4.2,
        parameters=parameters,
        mocked=True,
    )


def _assign(node: Node, _mock_url: str) -> MappedNode:
    """`assignments: [{variable, value}]` -> a Set node writing those fields."""
    assignments = node.configuration.get("assignments")
    entries = []
    for index, item in enumerate(assignments or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("variable") or item.get("name") or "").strip()
        if not name:
            continue
        entries.append(
            {
                "id": f"a{index}",
                "name": name,
                "type": "string",
                "value": _as_expression(item.get("value")),
            }
        )
    if not entries:
        return MappedNode(
            type="n8n-nodes-base.noOp",
            type_version=1,
            warning=f"Node {node.id!r} assigns nothing that could be mapped.",
        )
    return MappedNode(
        type="n8n-nodes-base.set",
        type_version=3.4,
        parameters={
            "assignments": {"assignments": entries},
            "includeOtherFields": True,
            "options": {},
        },
    )


def _llm(node: Node, mock_url: str) -> MappedNode:
    """Agent and DocumentAI nodes call a model provider; the call is mocked.

    Sending a test run's prompts to a real provider would cost money and leak whatever the
    uploaded workflow carries, so these go to the mock like any other outbound call.
    """
    config = node.configuration
    payload = {
        "prompt": config.get("userMessage") or config.get("operation") or "",
        "system": config.get("systemPrompt") or "",
        "agent": config.get("agentId") or "",
    }
    return MappedNode(
        type="n8n-nodes-base.httpRequest",
        type_version=4.2,
        parameters={
            "method": "POST",
            "url": mock_url,
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": _json_body(payload, intended_url=""),
            "options": {
            "response": {"response": {"neverError": False}},
            "timeout": request_timeout_ms(node),
        },
        },
        mocked=True,
        warning=(
            f"Node {node.id!r} calls a model provider; the call was mocked, so the run "
            f"exercises the workflow around it rather than the model's output."
        ),
    )


def _rpa(node: Node, mock_url: str) -> MappedNode:
    return MappedNode(
        type="n8n-nodes-base.httpRequest",
        type_version=4.2,
        parameters={
            "method": "POST",
            "url": mock_url,
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": _json_body(
                {"automationId": node.configuration.get("automationId")}, intended_url=""
            ),
            "options": {
            "response": {"response": {"neverError": False}},
            "timeout": request_timeout_ms(node),
        },
        },
        mocked=True,
    )


def _code(node: Node, _mock_url: str) -> MappedNode:
    """Not executed. See the module docstring."""
    language = str(node.configuration.get("language") or "code")
    return MappedNode(
        type="n8n-nodes-base.noOp",
        type_version=1,
        warning=(
            f"Node {node.id!r} runs {language}; it was not executed. WorkflowGuard does not run "
            f"code from an uploaded file, so the run exercises the path through this node but "
            f"not what it computes."
        ),
    )


def _parser(node: Node, _mock_url: str) -> MappedNode:
    """JsonParser and TextParser reshape data deterministically.

    Reproducing the reshaping means running the mapping or the regex, which is the same
    execute-uploaded-logic question as Code. They pass data through and say so.
    """
    return MappedNode(
        type="n8n-nodes-base.noOp",
        type_version=1,
        warning=(
            f"Node {node.id!r} parses its input; the parsing was not reproduced, so any "
            f"downstream condition reading its output sees the unparsed data."
        ),
    )


_HANDLERS = {
    "http": _http,
    "assign": _assign,
    "agent": _llm,
    "documentai": _llm,
    "rpa": _rpa,
    "code": _code,
    "jsonparser": _parser,
    "textparser": _parser,
}


def _json_body(body: Any, *, intended_url: str) -> str:
    """An n8n expression producing the request body, merged with the current item.

    The item is merged in so a downstream condition still sees the state that reached this node,
    which is how the canonical flat-state model behaves.
    """
    payload: dict[str, Any] = {}
    if isinstance(body, dict):
        payload.update(body)
    elif body not in (None, ""):
        payload["body"] = body
    if intended_url:
        payload["__wg_intended_url"] = intended_url
    return "={{ JSON.stringify(Object.assign({}, $json, " + json.dumps(payload) + ")) }}"


def _as_expression(value: Any) -> Any:
    """Qubi templates use `{{ var }}`; n8n needs a leading `=` to evaluate one."""
    if isinstance(value, str) and "{{" in value:
        return "=" + value
    return value
