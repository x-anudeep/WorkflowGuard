"""Deciding whether an edge is an error/exception path or an ordinary business branch.

Every reliability judgement in WorkflowGuard depends on this question, so it is worth
doing properly. Two different sources of evidence exist and they need different handling:

* **Labels** ("on error", "failure", "catch") are human annotations. Matching whole
  words is enough - but it must be whole words. Substring matching reads ``retry`` out
  of ``retryAllocationResult`` and ``error`` out of ``errorField``, which is how a
  *success* branch ends up classified as an error branch.
* **Conditions** are expressions like ``{{allocationResult.success}} == false``. The
  meaningful signal is the combination of field name and polarity: the same field with
  the opposite comparison is the success path. Word matching cannot see this at all.

Anything without positive evidence is treated as a normal branch. Over-claiming here
inflates reliability scores by crediting error handling that does not exist.
"""

from __future__ import annotations

import re

from workflow_core.canonical.models import Edge

#: Whole words in a human-written edge label that mark an error path.
FAILURE_LABEL_TERMS = frozenset(
    {
        "catch",
        "compensate",
        "compensation",
        "denied",
        "error",
        "errors",
        "exception",
        "fail",
        "failed",
        "failure",
        "fallback",
        "reject",
        "rejected",
        "retry",
        "rollback",
        "timeout",
    }
)

#: Field names whose truth means the step worked. ``== false`` on one is a failure path.
SUCCESS_FIELDS = (
    "success",
    "succeeded",
    "ok",
    "valid",
    "verified",
    "passed",
    "approved",
    "matched",
    "match",
    "available",
    "found",
    "complete",
    "completed",
)

#: Field names whose truth means something went wrong. ``== true`` is a failure path.
FAILURE_FIELDS = (
    "breached",
    "cancelled",
    "canceled",
    "declined",
    "duplicate",
    "error",
    "exceeded",
    "expired",
    "failed",
    "failure",
    "invalid",
    "missing",
    "overdue",
    "rejected",
    "timeout",
    "unavailable",
)

#: String values that indicate a failed outcome.
FAILURE_LITERALS = frozenset(
    {
        "cancelled",
        "canceled",
        "declined",
        "denied",
        "error",
        "expired",
        "fail",
        "failed",
        "failure",
        "invalid",
        "none",
        "rejected",
        "timeout",
        "unavailable",
        "unpaid",
    }
)

#: String values that indicate a successful outcome. ``!=`` one of these is a failure path.
SUCCESS_LITERALS = frozenset(
    {
        "approved",
        "complete",
        "completed",
        "ok",
        "paid",
        "success",
        "succeeded",
        "valid",
        "verified",
    }
)

#: Fields carrying an HTTP-style status code.
_STATUS_CODE_FIELDS = ("statuscode", "status_code", "httpstatus", "http_status", "responsecode")

_WORD = re.compile(r"[a-z]+")
_CLAUSE_SPLIT = re.compile(r"\|\||&&|\bor\b|\band\b")
_TEMPLATE = re.compile(r"\{\{|\}\}")

_BOOL_COMPARISON = re.compile(r"([\w.\[\]]+)\s*(==|!=|===|!==)\s*(true|false)\b")
_LITERAL_COMPARISON = re.compile(r"""([\w.\[\]]+)\s*(==|!=|===|!==)\s*['"]?([a-z_]+)['"]?""")
_NUMERIC_COMPARISON = re.compile(r"([\w.\[\]]+)\s*(==|!=|>=|<=|>|<)\s*(\d{3})\b")
_NULL_COMPARISON = re.compile(r"([\w.\[\]]+)\s*(==|!=|===|!==)\s*(null|nil|none|undefined)\b")


def is_failure_edge(edge: Edge) -> bool:
    """Whether this edge carries the workflow down an error/exception path."""
    return label_signals_failure(edge.label) or condition_signals_failure(edge.condition)


def label_signals_failure(label: str | None) -> bool:
    """True when a human-written label names an error path, matched on whole words."""
    if not label:
        return False
    return bool(FAILURE_LABEL_TERMS.intersection(_WORD.findall(label.lower())))


def condition_signals_failure(condition: str | None) -> bool:
    """True when a branch expression asserts that something went wrong.

    A disjunction is a failure path if any of its clauses is: ``A == "rejected" ||
    B == "rejected"`` is a rejection branch.
    """
    if not condition:
        return False
    normalized = _TEMPLATE.sub(" ", condition).lower()
    return any(_clause_signals_failure(clause) for clause in _CLAUSE_SPLIT.split(normalized))


def _clause_signals_failure(clause: str) -> bool:
    clause = clause.strip()
    if not clause:
        return False
    return (
        _boolean_failure(clause)
        or _null_failure(clause)
        or _status_code_failure(clause)
        or _literal_failure(clause)
    )


def _boolean_failure(clause: str) -> bool:
    """``result.success == false`` fails; ``result.success == true`` does not."""
    match = _BOOL_COMPARISON.search(clause)
    if not match:
        return False
    field, operator, value = match.group(1), match.group(2), match.group(3)
    asserts_true = (value == "true") == operator.startswith("==")
    if _field_matches(field, SUCCESS_FIELDS):
        return not asserts_true
    if _field_matches(field, FAILURE_FIELDS):
        return asserts_true
    return False


def _null_failure(clause: str) -> bool:
    """``error != null`` is the error path; ``error == null`` is the happy path."""
    match = _NULL_COMPARISON.search(clause)
    if not match:
        return False
    field, operator = match.group(1), match.group(2)
    if not _field_matches(field, FAILURE_FIELDS):
        return False
    return operator.startswith("!")


def _status_code_failure(clause: str) -> bool:
    """Any comparison selecting a non-2xx HTTP status."""
    match = _NUMERIC_COMPARISON.search(clause)
    if not match:
        return False
    field, operator, code = match.group(1), match.group(2), int(match.group(3))
    if not any(name in field.replace(".", "") for name in _STATUS_CODE_FIELDS):
        return False
    if operator in {">=", ">"}:
        return code >= 299
    if operator == "==":
        return code >= 400
    if operator == "!=":
        return 200 <= code < 300
    return False


def _literal_failure(clause: str) -> bool:
    """``status == "failed"`` and ``paymentStatus != "paid"`` are both failure paths."""
    for match in _LITERAL_COMPARISON.finditer(clause):
        operator, value = match.group(2), match.group(3)
        if value in {"true", "false", "null", "nil", "none", "undefined"}:
            continue
        equality = operator.startswith("==")
        if value in FAILURE_LITERALS and equality:
            return True
        if value in SUCCESS_LITERALS and not equality:
            return True
    return False


def _field_matches(field: str, terms: tuple[str, ...]) -> bool:
    """Match on the final path segment of a field reference.

    Using the last segment is what keeps ``retryAllocationResult.success`` on the success
    side: the qualifier names a variable, the segment names the property being tested.
    Prefix and suffix both count, since real field names run either way (``errorMessage``,
    ``isValid``).
    """
    segment = field.rsplit(".", maxsplit=1)[-1].strip("[]_ ")
    return any(
        segment == term or segment.startswith(term) or segment.endswith(term) for term in terms
    )
