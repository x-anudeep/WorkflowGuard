from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

import httpx

from workflowguard_api.ai.errors import (
    AIProviderError,
    AIProviderUnavailable,
    MalformedAIResponse,
)

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"

#: Groq only honours ``strict`` JSON-schema mode on a subset of models; every model
#: supports plain JSON-object mode. We ask for the strict schema where we can and fall
#: back rather than pinning every caller to one model.
STRICT_SCHEMA_MODELS = frozenset(
    {
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
        "qwen/qwen3.8-27b",
    }
)

DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"


class AIRateLimited(AIProviderError):
    """The provider refused because of a rate limit rather than anything about the request.

    Groq reports its tokens-per-minute limit as **HTTP 413**, not 429, with
    ``code: rate_limit_exceeded`` in the body. Reading that as a generic "payload too large"
    hides the real cause. ``retry_after`` is the provider's own hint; ``fits_limit`` is False
    when a single request exceeds the whole per-minute allowance, in which case waiting can
    never help and the request itself has to get smaller.
    """

    def __init__(self, message: str, *, retry_after: float | None = None, fits_limit: bool = True) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.fits_limit = fits_limit


class _SchemaRejected(Exception):
    """Internal signal that Groq rejected the json_schema response format."""


def groq_json_completion(
    *,
    api_key: str,
    model: str,
    system: str,
    user: str,
    schema: dict[str, Any],
    schema_name: str,
    timeout_seconds: float = 20.0,
) -> str:
    """Call Groq's OpenAI-compatible chat endpoint and return the raw JSON text.

    Structured output is requested with ``json_schema`` when the model supports strict
    mode, and retried once in ``json_object`` mode if Groq rejects the schema. Callers
    must still validate the result: schema mode is best effort, never a guarantee.
    """
    strict = model in STRICT_SCHEMA_MODELS
    messages = _messages(system, user, schema, inline_schema=not strict)
    response_format: dict[str, Any] = (
        {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}}
        if strict
        else {"type": "json_object"}
    )

    try:
        return _with_rate_limit_retry(
            lambda: _post(api_key, model, messages, response_format, timeout_seconds)
        )
    except _SchemaRejected:
        return _with_rate_limit_retry(
            lambda: _post(
                api_key,
                model,
                _messages(system, user, schema, inline_schema=True),
                {"type": "json_object"},
                timeout_seconds,
            )
        )


#: Longest we will sit waiting out a rate limit before giving up and falling back. A caller is
#: usually an HTTP request someone is watching, so a long sleep is worse than a deterministic
#: answer now.
MAX_RATE_LIMIT_WAIT_SECONDS = 20.0


def _with_rate_limit_retry(call: Callable[[], str]) -> str:
    """Retry once when the provider says the limit will have reset by a known time.

    Only worth doing when the request *can* fit: Groq reports a tokens-per-minute overage as
    413, and if a single request needs more tokens than the whole per-minute allowance, waiting
    changes nothing and the caller should fall back immediately.
    """
    try:
        return call()
    except AIRateLimited as exc:
        wait = exc.retry_after
        if not exc.fits_limit or wait is None or wait > MAX_RATE_LIMIT_WAIT_SECONDS:
            raise
        time.sleep(wait)
        return call()


def _messages(system: str, user: str, schema: dict[str, Any], *, inline_schema: bool) -> list[dict[str, Any]]:
    if inline_schema:
        system = f"{system}\n\nRespond with a single JSON object matching this schema:\n{json.dumps(schema)}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _post(
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    response_format: dict[str, Any],
    timeout_seconds: float,
) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "response_format": response_format,
        "temperature": 0.7,
    }
    try:
        response = httpx.post(
            GROQ_CHAT_COMPLETIONS_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise AIProviderError("Groq timed out.") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in {401, 403}:
            raise AIProviderUnavailable("Groq credentials were rejected.") from exc
        if status == 429:
            raise _rate_limited(exc.response, "Groq rate limit was reached.") from exc
        if status == 400 and _mentions_response_format(exc.response):
            raise _SchemaRejected from exc
        if status == 413:
            # Groq signals its TPM limit with 413, so check the body before calling this a
            # size problem - the two need different responses from the caller.
            if _is_rate_limit(exc.response):
                raise _rate_limited(exc.response, "Groq token-per-minute limit was reached.") from exc
            raise AIProviderError("Groq rejected the request as too large.") from exc
        # Include the provider's own message: a bare status code sent us chasing request size
        # when the body said "rate_limit_exceeded", and again when it named the exact schema
        # property it disliked.
        raise AIProviderError(f"Groq returned HTTP {status}: {_error_detail(exc.response)}") from exc
    except httpx.HTTPError as exc:
        raise AIProviderError("Groq request failed.") from exc

    return extract_groq_text(response_json(response))


def _error_detail(response: httpx.Response, limit: int = 300) -> str:
    try:
        error = response.json().get("error") or {}
        message = error.get("message") or ""
    except ValueError:
        message = response.text
    return (message or "no detail").strip()[:limit]


def _is_rate_limit(response: httpx.Response) -> bool:
    try:
        error = response.json().get("error") or {}
    except ValueError:
        return "rate_limit" in response.text.lower()
    return error.get("code") == "rate_limit_exceeded" or error.get("type") == "tokens"


def _rate_limited(response: httpx.Response, message: str) -> AIRateLimited:
    requested, limit = _token_counts(response)
    retry_after = _retry_after(response)
    detail = message
    fits = True
    if requested and limit and requested > limit:
        # No amount of waiting makes a request larger than the whole per-minute budget fit.
        fits = False
        detail = (
            f"{message} A single request needs {requested} tokens against a per-minute limit of "
            f"{limit}, so it cannot succeed until the request itself is smaller."
        )
    elif retry_after:
        detail = f"{message} Retry after {retry_after:g}s."
    return AIRateLimited(detail, retry_after=retry_after, fits_limit=fits)


def _token_counts(response: httpx.Response) -> tuple[int | None, int | None]:
    match = re.search(r"Limit\s+(\d+),\s*Requested\s+(\d+)", response.text, re.IGNORECASE)
    if match:
        return int(match.group(2)), int(match.group(1))
    return None, None


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    try:
        return float(raw) if raw is not None else None
    except ValueError:
        return None


def _mentions_response_format(response: httpx.Response) -> bool:
    try:
        body = response.text.lower()
    except (UnicodeDecodeError, ValueError):
        return False
    return "response_format" in body or "json_schema" in body


def response_json(response: httpx.Response) -> Any:
    """Parse a provider response body, or fail as a provider error rather than a crash.

    An error response does not have to be JSON - a gateway returning 413 or 502 typically
    sends HTML. Parsing that outside the error handling raised an untyped exception that
    escaped every caller's fallback, so one bad response took down the whole request instead
    of just skipping the AI contribution.
    """
    try:
        return response.json()
    except ValueError as exc:
        raise MalformedAIResponse("AI provider returned a non-JSON response body.") from exc


def extract_groq_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
    raise MalformedAIResponse("Groq response did not contain message content.")
