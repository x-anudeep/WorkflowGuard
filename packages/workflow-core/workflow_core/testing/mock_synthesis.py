"""Mock responses that the workflow downstream of them can actually compute on.

Every integration node used to be mocked with the same payload::

    {"ok": true, "node": "f6419ed5-..."}

That was harmless while tests were simulated, because nothing consumed it. Now that uploaded
code executes, it is actively misleading. A real workflow shows how::

    Get Stock Price (HTTP) -> Check Price Threshold (Code) -> Branch -> Alert / No alert
                                return { isHigh: input.price > 100 }

The mock has no ``price``, so ``input.price`` is undefined, ``undefined > 100`` is false,
``isHigh`` is always false, and the test written for the alert branch **can never pass** - not
because the workflow is wrong but because the test fed it nothing to compute on. The green those
tests used to show was the bug: nothing was being evaluated.

So a mock has to supply the fields the downstream actually reads, with values chosen for the
branch the test exists to exercise. The interesting part is the indirection: the condition tests
``priceCheck.isHigh``, a Code node computes that from ``price``, and it is ``price`` the mock
must set. Solving the condition itself yields ``{"isHigh": true}``, which the code promptly
overwrites.

Condition parsing goes through :mod:`workflow_core.conditions` and value solving through
:func:`workflow_core.analysis.reachability.satisfying_state`, so this does not become a fourth
place that re-derives the grammar.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from workflow_core.analysis.reachability import satisfying_state
from workflow_core.canonical.models import Edge, Node, NodeType, Workflow
from workflow_core.conditions import (
    ApprovalFlag,
    Comparison,
    Condition,
    Conjunction,
    Disjunction,
    Truthy,
    field_name,
    parse_condition,
)
from workflow_core.testing.models import MockIntegration

__all__ = ["CodeDerivation", "INTEGRATION_TYPES", "required_fields", "synthesise_mocks"]

INTEGRATION_TYPES = frozenset(
    {NodeType.EXTERNAL_API, NodeType.DATABASE, NodeType.LLM, NodeType.EMAIL}
)

#: `input.price`, the way a qubi code node reads what reached it.
_INPUT_READ = re.compile(r"\binput\.([A-Za-z_$][\w$]*)")

#: The body of a `return { ... }`. Deliberately not a JavaScript parse: these bodies are
#: overwhelmingly one-liners, and a regex that is honest about its limits beats a parser that is
#: wrong in ways nobody can see. Anything it cannot read falls back to a typed default.
_RETURN_OBJECT = re.compile(r"return\s*\{(?P<body>[^{}]*)\}")

#: `input.price > 100`, or `price > 100`, inside one returned field's expression.
_COMPARISON = re.compile(
    r"(?:input\.)?(?P<field>[A-Za-z_$][\w$]*)\s*"
    r"(?P<operator>>=|<=|===|!==|==|!=|>|<)\s*"
    r"(?P<literal>\"[^\"]*\"|'[^']*'|-?\d+(?:\.\d+)?|true|false)"
)

#: Negating a comparison, for solving the *other* side of a branch.
_INVERSE = {">": "<=", ">=": "<", "<": ">=", "<=": ">", "==": "!=", "!=": "=="}

_STRICT = {"===": "==", "!==": "!="}


@dataclass(frozen=True)
class CodeDerivation:
    """A field a code node returns, and the input comparison that decides it.

    `return { isHigh: input.price > 100 }` gives
    ``CodeDerivation("isHigh", "price", ">", "100")``.
    """

    produced_field: str
    source_field: str
    operator: str
    literal: str

    def condition_for(self, want_true: bool) -> str:
        """A canonical condition on the *source* field that makes the produced field true/false."""
        operator = self.operator if want_true else _INVERSE.get(self.operator, self.operator)
        return f"{self.source_field} {operator} {self.literal}"


def code_derivations(node: Node) -> list[CodeDerivation]:
    """What this node's code computes, as far as it can be read."""
    code = str(node.configuration.get("code") or "")
    if not code:
        return []
    derivations: list[CodeDerivation] = []
    for match in _RETURN_OBJECT.finditer(code):
        for entry in _split_entries(match.group("body")):
            name, _, expression = entry.partition(":")
            name = name.strip().strip("\"'")
            if not name:
                continue
            comparison = _COMPARISON.search(expression)
            if comparison is None:
                continue
            operator = comparison.group("operator")
            derivations.append(
                CodeDerivation(
                    produced_field=name,
                    source_field=comparison.group("field"),
                    operator=_STRICT.get(operator, operator),
                    literal=comparison.group("literal"),
                )
            )
    return derivations


def produced_fields(node: Node) -> set[str]:
    """Fields this node's code returns, whether or not how it computes them can be read.

    The distinction matters for steering. A field with a readable derivation can be driven by
    choosing the input it compares; a field that is merely *known to be computed* cannot be
    driven at all, because whatever a mock supplies the code will overwrite. Those are the
    branches worth refusing to write a test for.
    """
    code = str(node.configuration.get("code") or "")
    names: set[str] = set()
    for match in _RETURN_OBJECT.finditer(code):
        for entry in _split_entries(match.group("body")):
            name, separator, _ = entry.partition(":")
            if separator:
                names.add(name.strip().strip("\"'"))
    return {name for name in names if name}


def required_fields(workflow: Workflow) -> dict[str, set[str]]:
    """Fields each integration node's mock has to supply, keyed by node id.

    Attribution is deliberately generous: every field anything downstream reads is asked of every
    integration node upstream of it. Working out precisely which node ought to supply which field
    would need data-flow analysis the canonical model does not carry, and an extra field in a
    mocked response costs nothing, while a missing one silently breaks the branch that needed it.
    """
    referenced = _referenced_fields(workflow)
    outgoing: dict[str, list[Edge]] = {}
    for edge in workflow.edges:
        outgoing.setdefault(edge.source, []).append(edge)

    requirements: dict[str, set[str]] = {}
    for node in workflow.nodes:
        if node.type not in INTEGRATION_TYPES:
            continue
        wanted: set[str] = set()
        for reachable in _reachable_from(node.id, outgoing):
            wanted |= referenced.get(reachable, set())
        requirements[node.id] = wanted
    return requirements


def synthesise_mocks(
    workflow: Workflow,
    *,
    target_edge: Edge | None = None,
    target_edges: Sequence[Edge] = (),
) -> tuple[list[MockIntegration], list[str]]:
    """Mocked responses for this workflow, aimed at the given edges.

    A branch test names one edge. The happy path names the whole path it means to walk, because
    its mock has to satisfy *every* condition along the way - solving only the last one leaves
    an earlier branch diverting the run before it gets there.

    Returns the mocks and any warnings about branches that could not be steered. A branch test
    for an unsteerable branch is worse than no test: it fails for a reason that says nothing
    about the workflow, and a red test nobody can make green trains people to ignore the suite.
    """
    requirements = required_fields(workflow)
    derivations = {
        derivation.produced_field: derivation
        for node in workflow.nodes
        for derivation in code_derivations(node)
    }
    computed = {field for node in workflow.nodes for field in produced_fields(node)}
    edges = [*target_edges, *( [target_edge] if target_edge is not None else [] )]
    solved: dict[str, Any] = {}
    warnings: list[str] = []
    for edge in edges:
        edge_solved, edge_warnings = _values_for_target(edge, derivations, computed)
        solved.update(edge_solved)
        warnings.extend(edge_warnings)

    mocks: list[MockIntegration] = []
    for node in workflow.nodes:
        if node.type not in INTEGRATION_TYPES:
            continue
        response: dict[str, Any] = {"ok": True, "node": node.id}
        for field in sorted(requirements.get(node.id, set())):
            if field in solved:
                response[field] = solved[field]
            elif field in computed:
                # The workflow computes this one. Supplying it from a mock would mask whether
                # the computation ran at all - the failure this whole module exists to stop.
                continue
            else:
                default = _typed_default(field, workflow)
                if default is not None:
                    response[field] = default
        mocks.append(MockIntegration(node_id=node.id, response=response, status_code=200))
    return mocks, warnings


def _values_for_target(
    target_edge: Edge | None,
    derivations: dict[str, CodeDerivation],
    computed: set[str],
) -> tuple[dict[str, Any], list[str]]:
    """Values that steer the run down ``target_edge``.

    Three cases, in order of directness:

    1. The condition names a field an integration supplies - solve the condition itself.
    2. The condition names a field a code node *computes* - solve the comparison inside that
       code instead, on the field it reads. This is the case the bland mock could never satisfy.
    3. Neither - the branch cannot be steered, and the caller is told so.
    """
    if target_edge is None or not target_edge.condition:
        return {}, []

    parsed = parse_condition(target_edge.condition)
    solved: dict[str, Any] = dict(satisfying_state(target_edge.condition))
    warnings: list[str] = []

    for field, want_true in _tested_fields(parsed):
        derivation = derivations.get(field)
        if derivation is not None:
            # A computed field with a readable derivation: whatever we solved for it is about to
            # be overwritten, so solve the input it is computed from instead.
            solved.pop(field, None)
            solved.update(satisfying_state(derivation.condition_for(want_true)))
        elif field in computed:
            # Computed, but by something this module cannot read. Nothing a mock supplies
            # survives, so the branch cannot be steered and a test for it would fail for a
            # reason that says nothing about the workflow.
            solved.pop(field, None)
            warnings.append(
                f"Branch {target_edge.id!r} tests {field!r}, which a code node computes in a "
                f"way this generator cannot read; no mocked response can influence it, so the "
                f"test could not be steered down that branch."
            )
    return solved, warnings


def _tested_fields(condition: Condition) -> list[tuple[str, bool]]:
    """Field names a condition tests, with whether the branch wants them truthy."""
    if isinstance(condition, (Conjunction, Disjunction)):
        return [pair for part in condition.parts for pair in _tested_fields(part)]
    if isinstance(condition, Truthy):
        return [(field_name(condition.token), True)]
    if isinstance(condition, ApprovalFlag):
        return [("approved", condition.expected)]
    if isinstance(condition, Comparison):
        want = True
        if condition.operator in {"==", "!="}:
            literal = condition.right.strip().strip("\"'").lower()
            if literal in {"true", "false"}:
                want = (literal == "true") == (condition.operator == "==")
        return [(field_name(condition.left), want)]
    return []


def _referenced_fields(workflow: Workflow) -> dict[str, set[str]]:
    """Every field each node reads, from its conditions, its code and its declared inputs."""
    referenced: dict[str, set[str]] = {}
    for edge in workflow.edges:
        if not edge.condition:
            continue
        fields = {field for field, _ in _tested_fields(parse_condition(edge.condition))}
        referenced.setdefault(edge.source, set()).update(fields)

    for node in workflow.nodes:
        fields: set[str] = set()
        code = str(node.configuration.get("code") or "")
        fields.update(_INPUT_READ.findall(code))
        declared = node.configuration.get("input")
        if isinstance(declared, dict):
            fields.update(str(key) for key in declared)
        for derivation in code_derivations(node):
            fields.add(derivation.source_field)
        if fields:
            referenced.setdefault(node.id, set()).update(fields)
    return referenced


def _reachable_from(node_id: str, outgoing: dict[str, list[Edge]]) -> set[str]:
    """Every node downstream of this one, including itself."""
    seen = {node_id}
    queue = [node_id]
    while queue:
        current = queue.pop()
        for edge in outgoing.get(current, []):
            if edge.target not in seen:
                seen.add(edge.target)
                queue.append(edge.target)
    return seen


def _typed_default(field: str, workflow: Workflow) -> Any:
    """A plausibly-shaped value when nothing needs a specific one.

    Shape matters even when the exact value does not: a field compared against a number and
    mocked as `true` makes the comparison meaningless in a way that is hard to see afterwards.
    """
    for edge in workflow.edges:
        if not edge.condition:
            continue
        parsed = parse_condition(edge.condition)
        for comparison in _comparisons(parsed):
            if field_name(comparison.left) != field and field_name(comparison.right) != field:
                continue
            literal = comparison.right.strip().strip("\"'")
            if literal.lower() in {"true", "false"}:
                return True
            if re.fullmatch(r"-?\d+(\.\d+)?", literal):
                return 1
            return literal
    return 1


def _comparisons(condition: Condition) -> list[Comparison]:
    if isinstance(condition, (Conjunction, Disjunction)):
        return [c for part in condition.parts for c in _comparisons(part)]
    return [condition] if isinstance(condition, Comparison) else []


def _split_entries(body: str) -> list[str]:
    """Split an object literal's entries on top-level commas."""
    entries: list[str] = []
    depth = 0
    current: list[str] = []
    for character in body:
        if character in "([":
            depth += 1
        elif character in ")]":
            depth -= 1
        if character == "," and depth <= 0:
            entries.append("".join(current))
            current = []
            continue
        current.append(character)
    if current:
        entries.append("".join(current))
    return entries
