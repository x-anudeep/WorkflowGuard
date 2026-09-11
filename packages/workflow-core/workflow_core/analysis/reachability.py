"""Deriving inputs that actually reach the node a fuzz case targets.

A fuzz case that injects a failure into a node behind a conditional branch proves
nothing if the run takes the other branch: the fault never fires and the case is
discarded as NOT_TRIGGERED. That is the honest verdict, but it wastes the case - and it
disproportionately wastes AI-proposed cases, which tend to target the interesting
downstream nodes (approval paths, rejection paths, retry paths) precisely because those
are where error handling is most likely to be wrong.

This module walks a path from a start node to the target and solves the edge conditions
along it for input state that satisfies them. The condition language is the canonical one
defined in :mod:`workflow_core.conditions` - ``field OP literal`` - and the solved state is
keyed with that module's :func:`~workflow_core.conditions.field_name`, so whatever evaluates
the condition later reads back exactly the value solved for here.
"""

from __future__ import annotations

import re
from collections import deque
from typing import Any

from workflow_core.canonical.models import Edge, Workflow
from workflow_core.conditions import field_name

_CLAUSE_SPLIT = re.compile(r"\|\||&&")
_COMPARISON = re.compile(r"^\s*(.+?)\s*(>=|<=|==|!=|>|<)\s*(.+?)\s*$")
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")

#: Value used when a condition only requires "not this string".
_DIFFERENT_STRING = "workflowguard_other"


def reaching_input(workflow: Workflow, target_node_id: str, base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Input state that routes execution to ``target_node_id``.

    Returns the base input unchanged when no path exists or no condition needs solving.
    Solved values take precedence over the base: reaching the node is the whole point of
    the case, and a base value that blocks the path defeats it.
    """
    state = dict(base or {})
    path = path_to(workflow, target_node_id)
    if not path:
        return state
    for edge in path:
        state.update(satisfying_state(edge.condition))
    return state


def path_to(workflow: Workflow, target_node_id: str) -> list[Edge] | None:
    """Shortest edge path from any start node to the target, or None if unreachable.

    Shortest is deliberate: fewer edges means fewer conditions to satisfy at once, so
    the solved input is less likely to contradict itself.
    """
    if target_node_id in workflow.start_node_ids:
        return []
    outgoing: dict[str, list[Edge]] = {}
    for edge in workflow.edges:
        outgoing.setdefault(edge.source, []).append(edge)

    queue: deque[tuple[str, list[Edge]]] = deque((start, []) for start in sorted(workflow.start_node_ids))
    seen: set[str] = set(workflow.start_node_ids)
    while queue:
        node_id, trail = queue.popleft()
        for edge in outgoing.get(node_id, []):
            if edge.target in seen:
                continue
            extended = [*trail, edge]
            if edge.target == target_node_id:
                return extended
            seen.add(edge.target)
            queue.append((edge.target, extended))
    return None


def satisfying_state(condition: str | None) -> dict[str, Any]:
    """State that makes ``condition`` true, as far as it can be solved.

    Unsolvable clauses yield nothing rather than a guess - a wrong guess would send the
    run down a different branch and produce a confusing result rather than no result.
    """
    if not condition or not condition.strip():
        return {}
    clauses = _CLAUSE_SPLIT.split(condition)
    # A disjunction only needs one true clause; solving the first is enough and avoids
    # writing contradictory values for the rest.
    if "||" in condition:
        clauses = clauses[:1]

    state: dict[str, Any] = {}
    for clause in clauses:
        state.update(_solve_clause(clause))
    return state


def _solve_clause(clause: str) -> dict[str, Any]:
    match = _COMPARISON.match(clause.strip())
    if not match:
        return {}
    left, operator, right = match.group(1), match.group(2), match.group(3)

    field, literal = left, right
    if _is_literal(left) and not _is_literal(right):
        # Written backwards, e.g. `500 < order.total`; flip so the field is on the left.
        field, literal = right, left
        operator = _mirror(operator)
    if _is_literal(field):
        return {}

    key = _state_key(field)
    value = _parse_literal(literal)
    solved = _value_for(operator, value)
    return {} if solved is _UNSOLVED else {key: solved}


class _Unsolved:
    pass


_UNSOLVED = _Unsolved()


def _value_for(operator: str, value: Any) -> Any:
    if isinstance(value, bool):
        # Booleans only support equality meaningfully.
        if operator in {"==", ">=", "<="}:
            return value
        if operator == "!=":
            return not value
        return _UNSOLVED
    if isinstance(value, (int, float)):
        if operator == "==":
            return value
        if operator == "!=":
            return value + 1
        if operator == ">":
            return value + 1
        if operator == ">=":
            return value
        if operator == "<":
            return value - 1
        if operator == "<=":
            return value
        return _UNSOLVED
    if operator == "==":
        return value
    if operator == "!=":
        return _DIFFERENT_STRING if value != _DIFFERENT_STRING else "workflowguard_alt"
    return _UNSOLVED


def _state_key(field: str) -> str:
    """The key the evaluator will look up.

    Delegates to :func:`workflow_core.conditions.field_name` rather than re-deriving it: this
    solver and that evaluator have to agree on where a value lands, and two copies of the rule
    would drift silently.
    """
    return field_name(field.strip().strip("\"'"))


def _is_literal(token: str) -> bool:
    stripped = token.strip().strip("\"'")
    return bool(_NUMBER.match(stripped)) or stripped.lower() in {"true", "false", "null", "none"}


def _parse_literal(token: str) -> Any:
    stripped = token.strip().strip("\"'")
    lowered = stripped.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if _NUMBER.match(stripped):
        return float(stripped) if "." in stripped else int(stripped)
    return stripped


def _mirror(operator: str) -> str:
    return {">": "<", "<": ">", ">=": "<=", "<=": ">="}.get(operator, operator)
