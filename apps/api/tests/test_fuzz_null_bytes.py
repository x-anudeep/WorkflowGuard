"""Persisting a fuzz campaign that fed a null byte into the workflow.

`null_byte` is one of the deterministic input mutations (workflow_core/fuzzing/generator.py),
so every campaign carries a U+0000 through to the database. PostgreSQL's JSON types cannot
represent that character, while SQLite stores it happily -- which is why this failed only
once deployed, with:

    psycopg.errors.UntranslatableCharacter: unsupported Unicode escape sequence
    DETAIL:  \\u0000 cannot be converted to text.

The suite runs on SQLite, so a test that merely persisted a campaign would pass either way.
These assert on the scrubbing itself instead.

Note the source below builds the null byte with chr(0) rather than writing the escape
inline: a literal NUL in a .py file makes it unparseable.
"""

import json

from workflow_core.fuzzing.generator import INPUT_MUTATIONS

from workflowguard_api.db.jsonb import NULL_BYTE_PLACEHOLDER, scrub_null_bytes

NUL = chr(0)


def test_a_plain_string_is_scrubbed() -> None:
    assert scrub_null_bytes(f"acme{NUL}corp") == f"acme{NULL_BYTE_PLACEHOLDER}corp"


def test_nested_containers_are_scrubbed() -> None:
    value = {"vendor": f"acme{NUL}corp", "tags": [f"a{NUL}b", {"deep": f"c{NUL}d"}]}
    assert scrub_null_bytes(value) == {
        "vendor": f"acme{NULL_BYTE_PLACEHOLDER}corp",
        "tags": [f"a{NULL_BYTE_PLACEHOLDER}b", {"deep": f"c{NULL_BYTE_PLACEHOLDER}d"}],
    }


def test_dict_keys_are_scrubbed_too() -> None:
    assert scrub_null_bytes({f"k{NUL}ey": 1}) == {f"k{NULL_BYTE_PLACEHOLDER}ey": 1}


def test_non_strings_pass_through_unchanged() -> None:
    value = {"amount": 100, "approved": True, "missing": None, "ratio": 1.5}
    assert scrub_null_bytes(value) == value


def test_tuples_become_lists_because_json_has_no_tuple() -> None:
    assert scrub_null_bytes((f"a{NUL}", "b")) == [f"a{NULL_BYTE_PLACEHOLDER}", "b"]


def test_the_placeholder_says_what_was_removed() -> None:
    """A replacement character or a silent deletion would hide the mutation entirely."""
    assert NULL_BYTE_PLACEHOLDER == "\\u0000"
    assert NUL not in NULL_BYTE_PLACEHOLDER


def test_the_generator_really_does_emit_a_null_byte() -> None:
    """If this stops being true the scrubbing is still correct, but its reason is gone."""
    names = [name for name, _payload in INPUT_MUTATIONS]
    assert "null_byte" in names
    payloads = json.dumps([payload for _name, payload in INPUT_MUTATIONS])
    assert "\\u0000" in payloads


def test_a_scrubbed_payload_survives_a_json_round_trip() -> None:
    """What the driver ultimately does: serialise, then hand the text to Postgres."""
    payload = {"amount": 100, "approved": True, "vendor": f"acme{NUL}corp"}
    scrubbed = scrub_null_bytes(payload)
    assert NUL not in json.dumps(scrubbed)
    assert json.loads(json.dumps(scrubbed))["vendor"] == f"acme{NULL_BYTE_PLACEHOLDER}corp"
