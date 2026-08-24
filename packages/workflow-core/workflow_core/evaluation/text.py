from __future__ import annotations

import re
from collections.abc import Iterable


STOP_WORDS = {
    "a",
    "an",
    "and",
    "from",
    "if",
    "in",
    "into",
    "of",
    "on",
    "or",
    "the",
    "then",
    "to",
    "when",
    "with",
}


def normalize_text(value: str) -> str:
    return " ".join(tokenize(value))


def tokenize(value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9_]+", value.lower()) if token not in STOP_WORDS]


def token_overlap(left: str, right: str) -> float:
    left_tokens = set(tokenize(left))
    right_tokens = set(tokenize(right))
    if not left_tokens or not right_tokens:
        return 0
    return len(left_tokens & right_tokens) / len(left_tokens)


def contains_any(value: str, terms: Iterable[str]) -> bool:
    normalized = value.lower()
    return any(term.lower() in normalized for term in terms)
