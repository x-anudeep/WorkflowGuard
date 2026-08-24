from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import ValidationError
from workflow_core.evaluation.models import RequirementSpec

from workflowguard_api.core.config import Settings


class AIProviderError(RuntimeError):
    pass


class AIProviderUnavailable(AIProviderError):
    pass


class MalformedAIResponse(AIProviderError):
    pass


class RequirementExtractionProvider(ABC):
    provider_name: str
    model_name: str | None

    @abstractmethod
    def extract_requirements(self, prompt: str) -> RequirementSpec:
        raise NotImplementedError


class NoopAIProvider(RequirementExtractionProvider):
    provider_name = "none"
    model_name = None

    def extract_requirements(self, prompt: str) -> RequirementSpec:
        raise AIProviderUnavailable("No AI provider is configured.")


class OpenAIResponsesProvider(RequirementExtractionProvider):
    provider_name = "openai"

    def __init__(self, api_key: str, model_name: str, timeout_seconds: float = 20.0) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds

    def extract_requirements(self, prompt: str) -> RequirementSpec:
        schema = RequirementSpec.model_json_schema()
        payload: dict[str, Any] = {
            "model": self.model_name,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "Extract a structured WorkflowGuard RequirementSpec from the user prompt. "
                        "Return only JSON matching the provided schema. Do not invent requirements."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "workflowguard_requirement_spec",
                    "schema": schema,
                    "strict": True,
                }
            },
        }
        try:
            response = httpx.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise AIProviderError("AI provider timed out during requirement extraction.") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                raise AIProviderUnavailable("AI provider credentials were rejected.") from exc
            if exc.response.status_code == 429:
                raise AIProviderError("AI provider rate limit was reached.") from exc
            raise AIProviderError(f"AI provider returned HTTP {exc.response.status_code}.") from exc
        except httpx.HTTPError as exc:
            raise AIProviderError("AI provider request failed.") from exc

        data = response.json()
        text = _extract_response_text(data)
        try:
            return RequirementSpec.model_validate_json(text)
        except (ValidationError, ValueError):
            try:
                return RequirementSpec.model_validate(json.loads(text))
            except Exception as nested:
                raise MalformedAIResponse("AI provider returned malformed requirement JSON.") from nested


class StaticMockAIProvider(RequirementExtractionProvider):
    provider_name = "mock"
    model_name = "mock-requirement-extractor"

    def __init__(self, spec: RequirementSpec) -> None:
        self.spec = spec

    def extract_requirements(self, prompt: str) -> RequirementSpec:
        return self.spec


def provider_from_settings(settings: Settings) -> RequirementExtractionProvider:
    provider = settings.ai_provider.lower()
    if provider in {"", "none", "disabled"}:
        return NoopAIProvider()
    if provider == "openai":
        if not settings.ai_api_key:
            raise AIProviderUnavailable("WORKFLOWGUARD_AI_API_KEY is not configured.")
        return OpenAIResponsesProvider(settings.ai_api_key, settings.ai_model, settings.ai_timeout_seconds)
    raise AIProviderUnavailable(f"Unsupported AI provider '{settings.ai_provider}'.")


def _extract_response_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    output = data.get("output")
    if isinstance(output, list):
        for item in output:
            content = item.get("content") if isinstance(item, dict) else None
            if isinstance(content, list):
                for content_item in content:
                    if isinstance(content_item, dict) and isinstance(content_item.get("text"), str):
                        return content_item["text"]
    raise MalformedAIResponse("AI provider response did not contain output text.")
