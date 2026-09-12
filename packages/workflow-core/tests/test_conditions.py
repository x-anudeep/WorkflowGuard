"""The canonical edge-condition grammar, parsed once.

`workflow_core.conditions` exists because three consumers read the same language: the
evaluator, the reachability solver, and (next) the n8n emitter. These tests pin the AST shape
they all depend on, and the round-trip invariant between solving a condition and evaluating
it - the property that silently broke when those two had separate parsers.
"""

import pytest

from workflow_core.analysis.reachability import satisfying_state
from workflow_core.conditions import (
    ApprovalFlag,
    Comparison,
    Conjunction,
    Disjunction,
    Truthy,
    evaluate_condition,
    field_name,
    parse_condition,
    resolve_token,
)


class TestParsing:
    def test_comparison_keeps_both_sides_as_written(self):
        parsed = parse_condition('plan == "starter"')
        assert parsed == Comparison(left="plan", operator="==", right='"starter"')

    @pytest.mark.parametrize(
        ("text", "operator"),
        [
            ("total >= 500", ">="),
            ("total <= 500", "<="),
            ("total > 500", ">"),
            ("total < 500", "<"),
            ("total == 500", "=="),
            ("total != 500", "!="),
        ],
    )
    def test_every_operator_round_trips(self, text, operator):
        parsed = parse_condition(text)
        assert isinstance(parsed, Comparison)
        assert parsed.operator == operator
        assert parsed.left == "total"

    def test_two_character_operators_win_over_their_prefixes(self):
        """`>=` must be matched before `>`, or the literal parses as `= 500`."""
        assert parse_condition("total >= 500") == Comparison("total", ">=", "500")
        assert parse_condition("total <= 500") == Comparison("total", "<=", "500")

    def test_or_binds_looser_than_and(self):
        parsed = parse_condition("a == 1 && b == 2 || c == 3")
        assert isinstance(parsed, Disjunction)
        assert isinstance(parsed.parts[0], Conjunction)
        assert parsed.parts[1] == Comparison("c", "==", "3")

    def test_word_operators_are_recognised(self):
        assert isinstance(parse_condition("a == 1 and b == 2"), Conjunction)
        assert isinstance(parse_condition("a == 1 OR b == 2"), Disjunction)

    @pytest.mark.parametrize("word", ["true", "yes", "approved"])
    def test_bare_approval_words(self, word):
        assert parse_condition(word) == ApprovalFlag(True)

    @pytest.mark.parametrize("word", ["false", "no", "rejected"])
    def test_bare_rejection_words(self, word):
        assert parse_condition(word) == ApprovalFlag(False)

    def test_bare_field_is_truthy_check(self):
        assert parse_condition("vendorRecord.found") == Truthy("vendorRecord.found")

    def test_never_raises_on_junk(self):
        """A malformed condition must degrade, not abort the run it appears in."""
        for junk in ["", "   ", ">>>", "((", '"unclosed', "&&", "||"]:
            parse_condition(junk)  # must not raise
            assert evaluate_condition(junk, {}) in (True, False)


class TestEvaluation:
    def test_or_split_precedes_comparison_split(self):
        """The regression the module comment warns about.

        Without splitting `||` first, `==` splits the whole string and the right-hand side
        reads as the literal `"starter" || plan`, so every OR branch evaluates false and a
        real workflow dead-ends at the gateway.
        """
        condition = 'plan == "starter" || plan == "professional"'
        assert evaluate_condition(condition, {"plan": "starter"}) is True
        assert evaluate_condition(condition, {"plan": "professional"}) is True
        assert evaluate_condition(condition, {"plan": "enterprise"}) is False

    def test_conjunction_requires_every_part(self):
        assert evaluate_condition("amount > 50 && amount < 200", {"amount": 100}) is True
        assert evaluate_condition("amount > 50 && amount < 200", {"amount": 400}) is False

    def test_dotted_reference_resolves_by_last_segment(self):
        assert evaluate_condition('signupPayload.plan == "enterprise"', {"plan": "enterprise"}) is True

    def test_approval_defaults_to_true_when_unstated(self):
        assert evaluate_condition("approved", {}) is True
        assert evaluate_condition("approved", {"approved": False}) is False
        assert evaluate_condition("rejected", {"approved": False}) is True

    def test_unresolved_field_against_number_is_false_not_an_error(self):
        assert evaluate_condition("amount > 50", {}) is False
        assert evaluate_condition("amount > 50", {"amount": "not a number"}) is False

    def test_missing_field_is_falsey(self):
        assert evaluate_condition("wasRefunded", {}) is False
        assert evaluate_condition("wasRefunded", {"wasRefunded": True}) is True


class TestTokens:
    @pytest.mark.parametrize(
        ("token", "expected"),
        [("500", 500), ("1.5", 1.5), ("-3", -3), ("true", True), ("false", False), ('"x"', "x")],
    )
    def test_literals_resolve_without_state(self, token, expected):
        assert resolve_token(token, {}) == expected

    def test_field_falls_back_to_itself_when_absent(self):
        assert resolve_token("plan", {}) == "plan"
        assert resolve_token("plan", {"plan": "starter"}) == "starter"

    def test_field_name_takes_the_last_segment(self):
        assert field_name("vendorRecord.found") == "found"
        assert field_name("found") == "found"


class TestSolverAgreement:
    """The invariant the shared module exists to protect.

    `satisfying_state` solves a condition for state that should make it true; `evaluate_condition`
    reads it back. When those two had separate parsers, a disagreement was invisible - a fuzz case
    would take the wrong branch and be written off as NOT_TRIGGERED rather than reported as a bug.
    """

    @pytest.mark.parametrize(
        "condition",
        [
            "amount > 500",
            "amount >= 500",
            "amount < 500",
            "amount <= 500",
            "amount == 500",
            "amount != 500",
            'plan == "enterprise"',
            "order.total > 1000",
            "vendorRecord.found == true",
            "approved == false",
            "amount > 50 && amount < 2000",
        ],
    )
    def test_solved_state_satisfies_the_condition(self, condition):
        assert evaluate_condition(condition, satisfying_state(condition)) is True
