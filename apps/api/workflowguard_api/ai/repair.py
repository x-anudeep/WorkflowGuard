from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import ValidationError
from workflow_core.canonical.models import Workflow
from workflow_core.repair import RepairPatch

from workflowguard_api.ai.providers import AIProviderError, AIProviderUnavailable, MalformedAIResponse, _extract_response_text
from workflowguard_api.core.config import Settings


class RepairProvider(ABC):
    provider_name: str
    model_name: str | None

    @abstractmethod
    def generate_patch(self, workflow: Workflow, finding: dict | None = None) -> RepairPatch:
        raise NotImplementedError


class NoopRepairProvider(RepairProvider):
    provider_name = "none"
    model_name = None

    def generate_patch(self, workflow: Workflow, finding: dict | None = None) -> RepairPatch:
        raise AIProviderUnavailable("No AI repair provider is configured.")


class OpenAIRepairProvider(RepairProvider):
    provider_name = "openai"

    def __init__(self, api_key: str, model_name: str, timeout_seconds: float = 20.0) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds

    def generate_patch(self, workflow: Workflow, finding: dict | None = None) -> RepairPatch:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "Generate a safe WorkflowGuard RepairPatch for the canonical workflow. Return only JSON "
                        "matching the schema. Do not remove requirements, approvals, tests, or add new external destinations unless explicitly required."
                    ),
                },
                {"role": "user", "content": json.dumps({"workflow": workflow.model_dump(mode="json"), "finding": finding})},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "workflowguard_repair_patch",
                    "schema": RepairPatch.model_json_schema(),
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
            raise AIProviderError("AI provider timed out during repair generation.") from exc
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
            return RepairPatch.model_validate_json(text)
        except (ValidationError, ValueError):
            try:
                return RepairPatch.model_validate(json.loads(text))
            except Exception as nested:
                raise MalformedAIResponse("AI provider returned malformed repair patch JSON.") from nested


class StaticMockRepairProvider(RepairProvider):
    provider_name = "mock"
    model_name = "mock-repair-generator"

    def __init__(self, patch: RepairPatch) -> None:
        self.patch = patch

    def generate_patch(self, workflow: Workflow, finding: dict | None = None) -> RepairPatch:
        return self.patch


def repair_provider_from_settings(settings: Settings) -> RepairProvider:
    provider = settings.ai_provider.lower()
    if provider in {"", "none", "disabled"}:
        return NoopRepairProvider()
    if provider == "openai":
        if not settings.ai_api_key:
            raise AIProviderUnavailable("WORKFLOWGUARD_AI_API_KEY is not configured.")
        return OpenAIRepairProvider(settings.ai_api_key, settings.ai_model, settings.ai_timeout_seconds)
    raise AIProviderUnavailable(f"Unsupported AI provider '{settings.ai_provider}'.")
