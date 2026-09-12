"""Turning source-format values into n8n expressions safely.

An emitted node often has to carry a value taken from the uploaded workflow - a URL, a request
body, a prompt - inside an n8n expression such as::

    ={{ JSON.stringify(Object.assign({}, $json, { ... })) }}

Embedding those values as JSON string literals is the obvious approach and it is wrong, because
source formats use ``{{ name }}`` templates of their own. A qubi URL like
``https://api.example.com/w?appid={{apiKey}}`` then lands *inside* an ``={{ ... }}`` expression,
n8n sees nested braces, and the whole node fails to parse - taking every test of that workflow
with it, with nothing but "invalid syntax" to go on.

Escaping the braces would fix the parse and lose the meaning. A template refers to a workflow
variable, so the faithful rendering resolves it: the URL becomes
``"https://api.example.com/w?appid=" + $json["apiKey"]``, and a report then shows the value the
workflow would really have used rather than the placeholder.

The invariant this module exists to hold: **nothing this returns may contain ``{{``.**
"""

from __future__ import annotations

import json
import re
from typing import Any

from workflow_core.conditions import field_name

__all__ = ["TEMPLATE", "js_object", "js_value"]

#: `{{ apiKey }}` - a reference to a workflow variable, in every source format that has them.
TEMPLATE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


def js_value(value: Any) -> str:
    """A JavaScript expression producing ``value``, with templates resolved against the item.

    Containers are walked, because a template can sit anywhere inside a request body, and one
    unresolved `{{` deep in a nested object breaks the expression exactly as surely as one at
    the top level.
    """
    if isinstance(value, str):
        return _js_string(value)
    if isinstance(value, dict):
        return js_object({str(key): item for key, item in value.items()})
    if isinstance(value, list):
        return "[" + ", ".join(js_value(item) for item in value) + "]"
    return json.dumps(value)


def js_object(fields: dict[str, Any]) -> str:
    """A JavaScript object literal, every value rendered by :func:`js_value`."""
    entries = [f"{json.dumps(str(key))}: {js_value(value)}" for key, value in fields.items()]
    return "{" + ", ".join(entries) + "}"


def _js_string(value: str) -> str:
    """A string, as a JS expression, resolving any templates it contains.

    ``"a{{x}}b"`` becomes ``("a" + ($json["x"] ?? "") + "b")``. The ``?? ""`` matters: an
    unresolved variable would otherwise interpolate the text "undefined" into a URL, which is
    both wrong and hard to spot afterwards.
    """
    if "{{" not in value:
        return json.dumps(value)

    parts: list[str] = []
    position = 0
    for match in TEMPLATE.finditer(value):
        if match.start() > position:
            parts.append(json.dumps(value[position : match.start()]))
        # Flat state, matching how conditions resolve a dotted reference everywhere else.
        parts.append(f'($json[{json.dumps(field_name(match.group(1)))}] ?? "")')
        position = match.end()
    if position < len(value):
        parts.append(json.dumps(value[position:]))

    if not parts:
        return '""'
    return "(" + " + ".join(parts) + ")"
