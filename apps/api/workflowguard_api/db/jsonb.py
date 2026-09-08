"""Making values safe to store in a JSONB column.

PostgreSQL's JSON types cannot represent U+0000. The character is legal in a JSON
document by the spec, and SQLite stores it without complaint, so a value carrying one
round-trips fine in tests and then fails only against a real Postgres:

    psycopg.errors.UntranslatableCharacter: unsupported Unicode escape sequence
    DETAIL: \\u0000 cannot be converted to text.

That is not a corner case here: the fuzzer deliberately feeds a null byte into workflows
as one of its input mutations, so persisting the result of a campaign hits it every time.
"""

from __future__ import annotations

from typing import Any

#: What a stripped NUL is replaced with. The six-character literal is deliberate -- it
#: keeps the record readable and says plainly that a null byte was there, which a
#: replacement character or a silent deletion would not.
NULL_BYTE_PLACEHOLDER = "\\u0000"


def scrub_null_bytes(value: Any) -> Any:
    """Return `value` with every U+0000 inside it replaced, recursing through containers.

    Only strings are rewritten; numbers, booleans and None pass through untouched, and
    dict keys are scrubbed as well as their values because a key can carry one too.
    """
    if isinstance(value, str):
        return value.replace("\x00", NULL_BYTE_PLACEHOLDER)
    if isinstance(value, dict):
        return {scrub_null_bytes(key): scrub_null_bytes(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub_null_bytes(item) for item in value]
    return value
