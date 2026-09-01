from __future__ import annotations

import json
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
        return _post(api_key, model, messages, response_format, timeout_seconds)
    except _SchemaRejected:
        return _post(
            api_key,
            model,
            _messages(system, user, schema, inline_schema=True),
            {"type": "json_object"},
            timeout_seconds,
        )


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
            raise AIProviderError("Groq rate limit was reached.") from exc
        if status == 400 and _mentions_response_format(exc.response):
            raise _SchemaRejected from exc
        raise AIProviderError(f"Groq returned HTTP {status}.") from exc
    except httpx.HTTPError as exc:
        raise AIProviderError("Groq request failed.") from exc

    return extract_groq_text(response.json())


def _mentions_response_format(response: httpx.Response) -> bool:
    try:
        body = response.text.lower()
    except (UnicodeDecodeError, ValueError):
        return False
    return "response_format" in body or "json_schema" in body


def extract_groq_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
    raise MalformedAIResponse("Groq response did not contain message content.")
