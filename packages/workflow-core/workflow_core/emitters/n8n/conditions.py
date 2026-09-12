"""Rendering a canonical condition AST into n8n IF/Switch parameters.

n8n's filter format (``typeVersion`` 2.2 of the IF node, verified against 2.38.7) is a *flat*
list of conditions joined by a single combinator. It has no nesting. Our grammar does nest -
``a && b || c`` parses to a Disjunction of a Conjunction and a Comparison - so there are two
rendering strategies:

* **Flat** conditions render as a structured filter, which is preferable because n8n then does
  its own type coercion and reports a readable condition in the UI. Boolean comparisons are the
  exception: loose coercion would let the string "yes" satisfy ``approved == true``, which the
  canonical grammar does not, so those take the expression path below.
* **Nested** conditions render as a single boolean JavaScript expression. One structured
  condition whose left value is ``={{ ... }}`` and whose operator is "is true".

Both are correct; the structured form is just friendlier, so it is used whenever it fits.
"""

from __future__ import annotations

import json
import re
from typing import Any

from workflow_core.conditions import (
    ApprovalFlag,
    Comparison,
    Condition,
    Conjunction,
    Disjunction,
    Truthy,
    field_name,
)

__all__ = ["render_if_parameters", "to_expression"]

_NUMBER = re.compile(r"-?\d+(\.\d+)?")

#: canonical operator -> n8n filter operation, per value type.
_OPERATIONS = {
    "==": "equals",
    "!=": "notEquals",
    ">": "gt",
    ">=": "gte",
    "<": "lt",
    "<=": "lte",
}

#: The JS form of each operator. `==`/`!=` become strict, matching our evaluator, which
#: compares resolved Python values without coercion.
_JS_OPERATORS = {"==": "===", "!=": "!==", ">": ">", ">=": ">=", "<": "<", "<=": "<="}

_MIRRORED = {">": "<", "<": ">", ">=": "<=", "<=": ">="}


def render_if_parameters(condition: Condition) -> dict[str, Any]:
    """Parameters for an `n8n-nodes-base.if` node (typeVersion 2.2)."""
    flat = _flatten(condition)
    if flat is not None:
        combinator, comparisons = flat
        rendered = [_render_comparison(c, i) for i, c in enumerate(comparisons)]
        if all(r is not None for r in rendered):
            return _filter(rendered, combinator)

    # Nested, or a shape the structured filter cannot express: fall back to one expression.
    return _filter(
        [
            {
                "id": "expr",
                "leftValue": to_expression(condition),
                "rightValue": "",
                "operator": {"type": "boolean", "operation": "true", "singleValue": True},
            }
        ],
        "and",
    )


def to_expression(condition: Condition) -> str:
    """The condition as an n8n expression string, e.g. ``={{ $json.amount > 10000 }}``."""
    return "={{ " + _js(condition) + " }}"


def _filter(conditions: list[dict[str, Any]], combinator: str) -> dict[str, Any]:
    return {
        "conditions": {
            "options": {
                "caseSensitive": True,
                "leftValue": "",
                # "loose" lets n8n coerce "10000" to 10000. The canonical grammar is written by
                # humans and by other parsers, so the literal's type is not dependable.
                "typeValidation": "loose",
                "version": 2,
            },
            "conditions": conditions,
            "combinator": combinator,
        },
        "options": {},
    }


def _flatten(condition: Condition) -> tuple[str, list[Comparison]] | None:
    """A single combinator over plain comparisons, or None when the AST nests."""
    if isinstance(condition, Comparison):
        return "and", [condition]
    if isinstance(condition, (Conjunction, Disjunction)):
        combinator = "and" if isinstance(condition, Conjunction) else "or"
        if not condition.parts:
            return None
        if all(isinstance(part, Comparison) for part in condition.parts):
            return combinator, list(condition.parts)
    return None


def _render_comparison(comparison: Comparison, index: int) -> dict[str, Any] | None:
    """One structured filter condition, or None if the sides cannot be told apart."""
    sides = _orient(comparison)
    if sides is None:
        return None
    field, operator, literal = sides
    value_type = _value_type(literal)
    operation = _OPERATIONS.get(operator)
    if operation is None:
        return None
    if value_type == "boolean":
        # Render booleans as a strict expression instead. The structured filter runs with
        # `typeValidation: "loose"`, which coerces - so `approved == true` would be satisfied by
        # the string "yes", where the canonical grammar compares resolved values and says it is
        # not. A test that supplies a deliberately wrong type has to see the branch not taken.
        return None
    return {
        "id": f"c{index}",
        "leftValue": _reference(field),
        "rightValue": literal,
        "operator": {"type": value_type, "operation": operation},
    }


def _orient(comparison: Comparison) -> tuple[str, str, Any] | None:
    """Decide which side is the field, returning (field, operator, literal value).

    Mirrors the operator when the condition is written backwards (``500 < order.total``), the
    same flip `analysis.reachability` makes when solving.
    """
    left_literal = _as_literal(comparison.left)
    right_literal = _as_literal(comparison.right)
    if right_literal is not _NOT_A_LITERAL and left_literal is _NOT_A_LITERAL:
        return comparison.left, comparison.operator, right_literal
    if left_literal is not _NOT_A_LITERAL and right_literal is _NOT_A_LITERAL:
        return comparison.right, _MIRRORED.get(comparison.operator, comparison.operator), left_literal
    # Two literals, or two fields: the structured filter has no way to express it.
    return None


class _NotALiteral:
    pass


_NOT_A_LITERAL = _NotALiteral()


def _as_literal(token: str) -> Any:
    """The literal value of a token, or the sentinel when it is a field reference.

    A quoted token is always a literal even when it looks like a field - that is the only
    signal the grammar gives us.
    """
    raw = token.strip()
    quoted = len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'"
    stripped = raw.strip("\"'")
    if quoted:
        return stripped
    if _NUMBER.fullmatch(stripped):
        return float(stripped) if "." in stripped else int(stripped)
    if stripped.lower() in {"true", "false"}:
        return stripped.lower() == "true"
    return _NOT_A_LITERAL


def _value_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def _reference(field: str) -> str:
    """An n8n expression reading the field from the current item."""
    return "={{ " + _json_path(field) + " }}"


def _json_path(field: str) -> str:
    """``$json.found`` for ``vendorRecord.found``.

    The last segment only, matching `conditions.field_name`: emitted workflows carry flat
    state, exactly as the simulator's state dict did, so a dotted canonical reference and a
    bare one must land on the same key.
    """
    return f"$json[{json.dumps(field_name(field))}]"


def _js(condition: Condition) -> str:
    """The condition as a JavaScript boolean expression."""
    if isinstance(condition, Disjunction):
        return "(" + " || ".join(_js(part) for part in condition.parts) + ")" if condition.parts else "false"
    if isinstance(condition, Conjunction):
        return "(" + " && ".join(_js(part) for part in condition.parts) + ")" if condition.parts else "true"
    if isinstance(condition, Comparison):
        return f"{_operand(condition.left)} {_JS_OPERATORS[condition.operator]} {_operand(condition.right)}"
    if isinstance(condition, ApprovalFlag):
        # `approved` defaults to true when absent, matching ApprovalFlag.evaluate.
        approved = f"({_json_path('approved')} === undefined ? true : Boolean({_json_path('approved')}))"
        return approved if condition.expected else f"!{approved}"
    if isinstance(condition, Truthy):
        return f"Boolean({_json_path(condition.token)})"
    return "false"


def _operand(token: str) -> str:
    literal = _as_literal(token)
    if literal is _NOT_A_LITERAL:
        return _json_path(token)
    return json.dumps(literal)
