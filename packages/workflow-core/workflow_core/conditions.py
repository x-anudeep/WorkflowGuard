"""The canonical edge-condition language: one parser, several consumers.

Canonical ``Edge.condition`` strings use a deliberately small grammar - ``field OP literal``
joined by ``&&``/``||``, plus the bare approval words - because it has to be expressible by
every parser we accept, from BPMN sequence-flow expressions to qubi branch conditions.

Until now that grammar had no single definition. :mod:`workflow_core.testing.simulator`
evaluated it, and :mod:`workflow_core.analysis.reachability` separately re-derived it with its
own regexes in order to *solve* it. Two hand-rolled readers of one language drift, and the
drift is silent: a condition the solver satisfies but the evaluator reads differently sends a
fuzz case down the wrong branch and reports NOT_TRIGGERED instead of a real verdict.

So the grammar is parsed once, here, into a small AST. Evaluation walks it. The n8n emitter
renders it into IF/Switch filter parameters. Reachability solves it. Adding a third reader
never means writing a fourth parser.

The AST is deliberately lossless about *how the condition was written*: :class:`Comparison`
keeps the raw left and right tokens rather than pre-resolving them, because whether a token is
a field reference or a string literal is only decidable against a particular state, and the
emitter needs the original text to build an n8n expression.
"""

from __future__ import annotations

import operator as _operator
import re
from dataclasses import dataclass
from typing import Any, Callable, Union

__all__ = [
    "COMPARISON_OPERATORS",
    "ApprovalFlag",
    "Comparison",
    "Condition",
    "Conjunction",
    "Disjunction",
    "Truthy",
    "evaluate_condition",
    "field_name",
    "parse_condition",
    "resolve_token",
]

#: ``a || b`` and ``a && b``. Splitting these before comparing is not optional: without it the
#: ``==`` split below reads ``"starter" || plan == "professional"`` as the right-hand literal, so
#: every OR branch in a real workflow evaluates false and the run dead-ends at that gateway.
_OR = re.compile(r"\|\||\bor\b", re.IGNORECASE)
_AND = re.compile(r"&&|\band\b", re.IGNORECASE)

_NUMBER = re.compile(r"-?\d+(\.\d+)?")

_TRUE_WORDS = frozenset({"true", "yes", "approved"})
_FALSE_WORDS = frozenset({"false", "no", "rejected"})

#: Longest-first: ``>=`` must be tested before ``>``, or ``total >= 500`` parses as
#: ``total > (= 500)``. Order is load-bearing, not cosmetic.
COMPARISON_OPERATORS: tuple[tuple[str, Callable[[Any, Any], bool]], ...] = (
    (">=", _operator.ge),
    ("<=", _operator.le),
    ("==", _operator.eq),
    ("!=", _operator.ne),
    (">", _operator.gt),
    ("<", _operator.lt),
)

_OPERATOR_FUNCS = dict(COMPARISON_OPERATORS)


@dataclass(frozen=True)
class Disjunction:
    """``a || b``. True when any part is true."""

    parts: tuple["Condition", ...]

    def evaluate(self, state: dict[str, Any]) -> bool:
        return any(part.evaluate(state) for part in self.parts)


@dataclass(frozen=True)
class Conjunction:
    """``a && b``. True when every part is true - vacuously true when there are no parts."""

    parts: tuple["Condition", ...]

    def evaluate(self, state: dict[str, Any]) -> bool:
        return all(part.evaluate(state) for part in self.parts)


@dataclass(frozen=True)
class Comparison:
    """``left OP right``, with both sides kept as written.

    Either side may turn out to be a field reference or a literal; :func:`resolve_token`
    decides that against the state at evaluation time.
    """

    left: str
    operator: str
    right: str

    def evaluate(self, state: dict[str, Any]) -> bool:
        try:
            return _OPERATOR_FUNCS[self.operator](
                resolve_token(self.left, state), resolve_token(self.right, state)
            )
        except TypeError:
            # An unresolved field compared against a number. The branch is simply not
            # satisfied - it is not a failure of the workflow under test.
            return False


@dataclass(frozen=True)
class ApprovalFlag:
    """The bare words ``approved``/``yes``/``true`` and their negations.

    Human-approval gateways are overwhelmingly written this way, so they read the ``approved``
    key rather than a field of their own name.
    """

    expected: bool

    def evaluate(self, state: dict[str, Any]) -> bool:
        approved = bool(state.get("approved", True))
        return approved if self.expected else not approved


@dataclass(frozen=True)
class Truthy:
    """A bare field reference: true when the state holds a truthy value for it."""

    token: str

    def evaluate(self, state: dict[str, Any]) -> bool:
        return bool(state.get(field_name(self.token), False))


Condition = Union[Disjunction, Conjunction, Comparison, ApprovalFlag, Truthy]


def parse_condition(condition: str | None) -> Condition:
    """Parse a canonical edge condition into its AST.

    Never raises: an unparseable condition degrades to :class:`Truthy`, which evaluates false
    against a state that does not mention it. A parse error here would abort a whole test run
    over one malformed expression in one edge, which is a far worse outcome than that edge
    simply not being taken.
    """
    text = (condition or "").strip()

    # OR binds loosest, so it splits first and AND is resolved inside each part.
    if _OR.search(text):
        return Disjunction(tuple(parse_condition(part) for part in _OR.split(text) if part.strip()))
    if _AND.search(text):
        return Conjunction(tuple(parse_condition(part) for part in _AND.split(text) if part.strip()))

    lowered = text.lower()
    if lowered in _TRUE_WORDS:
        return ApprovalFlag(True)
    if lowered in _FALSE_WORDS:
        return ApprovalFlag(False)

    for op_text, _func in COMPARISON_OPERATORS:
        if op_text in text:
            left, right = (part.strip() for part in text.split(op_text, 1))
            return Comparison(left, op_text, right)

    return Truthy(text)


def evaluate_condition(condition: str, state: dict[str, Any]) -> bool:
    """Whether ``condition`` holds for ``state``."""
    return parse_condition(condition).evaluate(state)


def resolve_token(token: str, state: dict[str, Any]) -> Any:
    """Resolve one side of a comparison to a value.

    Numbers and booleans are literals; everything else is looked up in the state and falls
    back to itself, which is what makes ``plan == "starter"`` work without the parser having
    to know which side is the field.
    """
    token = token.strip().strip("\"'")
    if _NUMBER.fullmatch(token):
        return float(token) if "." in token else int(token)
    lowered = token.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    return state.get(field_name(token), token)


def field_name(token: str) -> str:
    """The state key a dotted reference resolves to.

    ``vendorRecord.found`` is read as ``found``: simulated state is flat, and conditions
    reference results either fully qualified or bare depending on the source format.
    """
    return token.rsplit(".", maxsplit=1)[-1].strip()
