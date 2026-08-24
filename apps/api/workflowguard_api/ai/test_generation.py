from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import ValidationError
from workflow_core.canonical.models import Workflow
from workflow_core.evaluation.models import RequirementSpec
from workflow_core.testing.models import TestGenerationResult

from workflowguard_api.ai.providers import (
    AIProviderError,
    AIProviderUnavailable,
    MalformedAIResponse,
    _extract_response_text,
)
from workflowguard_api.core.config import Settings


class TestGenerationProvider(ABC):
    provider_name: str
    model_name: str | None

    @abstractmethod
    def generate_tests(self, workflow: Workflow, requirement_spec: RequirementSpec | None) -> TestGenerationResult:
        raise NotImplementedError


class NoopTestGenerationProvider(TestGenerationProvider):
    provider_name = "none"
    model_name = None

    def generate_tests(self, workflow: Workflow, requirement_spec: RequirementSpec | None) -> TestGenerationResult:
        raise AIProviderUnavailable("No AI test-generation provider is configured.")


class OpenAITestGenerationProvider(TestGenerationProvider):
    provider_name = "openai"

    def __init__(self, api_key: str, model_name: str, timeout_seconds: float = 20.0) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds

    def generate_tests(self, workflow: Workflow, requirement_spec: RequirementSpec | None) -> TestGenerationResult:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "Generate WorkflowGuard tests for this canonical workflow. Return only JSON matching "
                        "the provided TestGenerationResult schema. External systems must remain mocked."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "workflow": workflow.model_dump(mode="json"),
                            "requirement_spec": requirement_spec.model_dump(mode="json") if requirement_spec else None,
                        }
                    ),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "workflowguard_test_generation",
                    "schema": TestGenerationResult.model_json_schema(),
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
            raise AIProviderError("AI provider timed out during test generation.") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                raise AIProviderUnavailable("AI provider credentials were rejected.") from exc
            if exc.response.status_code == 429:
                raise AIProviderError("AI provider rate limit was reached.") from exc
            raise AIProviderError(f"AI provider returned HTTP {exc.response.status_code}.") from exc
        except httpx.HTTPError as exc:
            raise AIProviderError("AI provider request failed.") from exc

        text = _extract_response_text(response.json())
        try:
            return TestGenerationResult.model_validate_json(text)
        except (ValidationError, ValueError):
            try:
                return TestGenerationResult.model_validate(json.loads(text))
            except Exception as nested:
                raise MalformedAIResponse("AI provider returned malformed workflow test JSON.") from nested


class StaticMockTestGenerationProvider(TestGenerationProvider):
    provider_name = "mock"
    model_name = "mock-test-generator"

    def __init__(self, result: TestGenerationResult) -> None:
        self.result = result

    def generate_tests(self, workflow: Workflow, requirement_spec: RequirementSpec | None) -> TestGenerationResult:
        return self.result


def test_generation_provider_from_settings(settings: Settings) -> TestGenerationProvider:
    provider = settings.ai_provider.lower()
    if provider in {"", "none", "disabled"}:
        return NoopTestGenerationProvider()
    if provider == "openai":
        if not settings.ai_api_key:
            raise AIProviderUnavailable("WORKFLOWGUARD_AI_API_KEY is not configured.")
        return OpenAITestGenerationProvider(settings.ai_api_key, settings.ai_model, settings.ai_timeout_seconds)
    raise AIProviderUnavailable(f"Unsupported AI provider '{settings.ai_provider}'.")
