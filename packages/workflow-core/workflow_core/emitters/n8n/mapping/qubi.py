"""Mapping qubi nodes onto n8n nodes.

Grounded in 30 real qubi exports (311 nodes). The distribution matters, because it says where
fidelity is worth the effort:

===============  =====  ==========================================================
subtype          count  what it needs
===============  =====  ==========================================================
Http               130  method, url, headers, body - the bulk of all fidelity
Branch              46  handled by the emitter's router, not here
Code                35  executed, with its declared `input` mapping bound
Start / End         60  structural
Agent               26  an LLM call; mocked, never sent to a real provider
HitlTask            25  the emitter's approval shim
DocumentAI           6  an LLM call
JsonParser           5  deterministic reshaping
Assign               4  variable assignment
TextParser           3  regex extraction
RPA                  1  an external automation; mocked
===============  =====  ==========================================================

**Code nodes are executed.** Skipping them did not make a run incomplete so much as unreliable:
if a Code node computes a total and the next Branch tests it, not running the code means the
branch takes an arbitrary path, and the run then reports a confident pass or fail about
something it never evaluated. Across the 30 real exports these bodies are pure computation over
their input - no `require`, `fetch`, `process` or `eval` anywhere - so running them buys real
fidelity in the tests that matter most.

Containment does not depend on that staying true. n8n executes the code in an external task
runner, on a network that cannot reach anything but the mock endpoints, under a task timeout and
container resource limits. See the Security Posture section of `docs/architecture.md`.
"""

from __future__ import annotations

import json
import re
from typing import Any

from workflow_core.canonical.models import Node
from workflow_core.emitters.n8n.mapping.expressions import js_object
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
            "parameters": [
                {"name": str(key), "value": _header_value(value)}
                for key, value in headers.items()
            ]
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
    """Run the node's code, with the workflow's flat state bound as local variables.

    Qubi snippets read workflow variables by bare name (`poRecord.amount`, `totalAmount`) and
    return an object of new ones, while n8n's Code node exposes the item as `$json`. The body is
    therefore wrapped: each key of the current item is bound as a local, and whatever the body
    returns is merged back *over* the item rather than replacing it - canonical state accumulates
    down the graph, so a node returning one field must not erase the rest.
    """
    config = node.configuration
    code = str(config.get("code") or "").strip()
    language = str(config.get("language") or "javascript").lower()

    if not code:
        return MappedNode(
            type="n8n-nodes-base.noOp",
            type_version=1,
            warning=f"Node {node.id!r} is a code node with no code to run.",
        )

    if language.startswith("py"):
        # n8n runs Python through Pyodide, which does not expose the same wrapping hooks.
        # Emitting it unwrapped would leave the snippet's variables unbound and throw, which
        # would read as a defect in the workflow rather than a limitation here.
        return MappedNode(
            type="n8n-nodes-base.noOp",
            type_version=1,
            warning=(
                f"Node {node.id!r} runs Python; only JavaScript code nodes are executed, so the "
                f"run covers the path through this node but not what it computes."
            ),
        )

    return MappedNode(
        type="n8n-nodes-base.code",
        type_version=2,
        parameters={
            "mode": "runOnceForEachItem",
            "jsCode": _wrap_js(
                code, str(config.get("saveOutputAs") or "").strip(), config.get("input")
            ),
        },
    )


#: The wrapper around an uploaded snippet. `$wgBody` is the node's own code; it is invoked with
#: the item's fields bound as named parameters so bare references resolve, and its result is
#: merged back over the item. Errors are re-raised with the node's name attached so a failure
#: reads as this node failing rather than as a fault in the wrapper.
_JS_WRAPPER = """// WorkflowGuard: runs this node's code with the workflow's variables bound as locals.
const $wgItem = $json ?? {};
// The node's declared `input` mapping: qubi snippets read these both as `input.x` and as a
// bare `x`, so both are provided.
// A node that declares no mapping still reads `input.something`; there, `input` means the
// state that reached the node. Binding an empty object instead made every such read undefined,
// which is worse than useless: the code still runs, silently computes a wrong answer, and the
// branch that tests it takes the wrong path with nothing reported.
const $wgHasMapping = Object.keys(__WG_INPUT_VARS__).length > 0
  || Object.keys(__WG_INPUT_LITERALS__).length > 0;
const $wgInput = $wgHasMapping ? {} : Object.assign({}, $wgItem);
for (const [$wgKey, $wgVar] of Object.entries(__WG_INPUT_VARS__)) $wgInput[$wgKey] = $wgItem[$wgVar];
Object.assign($wgInput, __WG_INPUT_LITERALS__);
const $wgScope = Object.assign({}, $wgItem, $wgInput, { input: $wgInput });
// Only names that are valid identifiers can be function parameters; a state key like
// "content-type" would otherwise make the whole wrapper a syntax error.
const $wgNames = Object.keys($wgScope).filter((name) => /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(name));
const $wgBody = __WG_BODY__;
let $wgOut;
try {
  const $wgFn = new Function(...$wgNames, '"use strict";\\n' + $wgBody);
  $wgOut = $wgFn(...$wgNames.map((name) => $wgScope[name]));
} catch (error) {
  throw new Error('Code node failed: ' + ((error && error.message) || error));
}
const $wgMerged = Object.assign(
  {},
  $wgItem,
  $wgOut && typeof $wgOut === 'object' ? $wgOut : ($wgOut === undefined ? {} : { result: $wgOut })
);
__WG_SAVE__return { json: $wgMerged };
"""

#: `{{ someVariable }}` - the whole value is one template referencing a workflow variable.
_TEMPLATE_ONLY = re.compile(r"^\s*\{\{\s*([A-Za-z_$][\w$.]*)\s*\}\}\s*$")


def _input_bindings(raw: Any) -> tuple[dict[str, str], dict[str, Any]]:
    """Split a node's `input` mapping into variable references and plain literals.

    Qubi declares `{"poRecord": "{{poRecord}}"}`, meaning "expose the workflow variable
    `poRecord` under the name `poRecord`". Anything that is not a bare template is passed
    through as a constant.
    """
    variables: dict[str, str] = {}
    literals: dict[str, Any] = {}
    if not isinstance(raw, dict):
        return variables, literals
    for key, value in raw.items():
        match = _TEMPLATE_ONLY.match(value) if isinstance(value, str) else None
        if match:
            # Flat state: a dotted reference resolves by its last segment, as everywhere else.
            variables[str(key)] = match.group(1).rsplit(".", 1)[-1]
        else:
            literals[str(key)] = value
    return variables, literals


def _wrap_js(code: str, save_as: str, raw_input: Any = None) -> str:
    """Substitution rather than `format`, because the wrapper is full of JavaScript braces."""
    variables, literals = _input_bindings(raw_input)
    save = (
        f"if ($wgOut && typeof $wgOut === 'object') $wgMerged[{json.dumps(save_as)}] = $wgOut;\n"
        if save_as
        else ""
    )
    return (
        _JS_WRAPPER.replace("__WG_INPUT_VARS__", json.dumps(variables))
        .replace("__WG_INPUT_LITERALS__", json.dumps(literals))
        .replace("__WG_BODY__", json.dumps(code))
        .replace("__WG_SAVE__", save)
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
    which is how the canonical flat-state model behaves. Values go through `js_value` rather
    than `json.dumps`, because a qubi value may itself contain `{{ }}` - embedding one raw
    nests braces inside the expression and the node fails to parse.
    """
    payload: dict[str, Any] = {}
    if isinstance(body, dict):
        payload.update(body)
    elif body not in (None, ""):
        payload["body"] = body
    if intended_url:
        payload["__wg_intended_url"] = intended_url
    return "={{ JSON.stringify(Object.assign({}, $json, " + js_object(payload) + ")) }}"


def _header_value(value: Any) -> str:
    """A header value. n8n evaluates a `=`-prefixed field, so a template is safe here."""
    text = str(value)
    return "=" + text if "{{" in text else text


def _as_expression(value: Any) -> Any:
    """Qubi templates use `{{ var }}`; n8n needs a leading `=` to evaluate one.

    Safe only in a field n8n evaluates directly. A template nested inside another expression
    breaks the parse - see `expressions.js_value` for that case.
    """
    if isinstance(value, str) and "{{" in value:
        return "=" + value
    return value
