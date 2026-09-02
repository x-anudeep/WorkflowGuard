from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import ValidationError
from workflow_core.canonical.models import Workflow
from workflow_core.evaluation.models import RequirementSpec
from workflow_core.testing.generator import default_mocks
from workflow_core.testing.models import (
    AssertionType,
    TestGeneratedBy,
    TestGenerationResult,
    WorkflowAssertion,
    WorkflowTest,
)

from workflowguard_api.ai.groq_client import groq_json_completion, response_json
from workflowguard_api.ai.providers import (
    AIProviderError,
    AIProviderUnavailable,
    MalformedAIResponse,
    _extract_response_text,
)
from workflowguard_api.core.config import Settings

#: Flat and $ref-free. `TestGenerationResult.model_json_schema()` is ~4.5 KB of $defs, which
#: Groq's strict mode rejects outright ("additionalProperties:false must be set on every
#: object") and which then gets inlined into the system prompt on the fallback - roughly 1.1K
#: tokens spent describing a schema the model never validates against. This asks for the few
#: fields a generated test actually needs and maps them onto WorkflowTest in Python.
TEST_SUGGESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tests": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    # A free-form object cannot satisfy strict mode's `additionalProperties:
                    # false`, so the input travels as a JSON string and is parsed here - the
                    # same shape `ai/fuzzing.py` uses for its case inputs.
                    "input_json": {
                        "type": "string",
                        "description": "A JSON object of workflow input values, encoded as a string.",
                    },
                    "expected_path": {"type": "array", "items": {"type": "string"}},
                    "expected_side_effects": {"type": "array", "items": {"type": "string"}},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "rationale": {"type": "string"},
                },
                # Strict mode wants every property in `required`; optional ones are nullable.
                "required": [
                    "name",
                    "description",
                    "input_json",
                    "expected_path",
                    "expected_side_effects",
                    "tags",
                    "rationale",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["tests"],
    "additionalProperties": False,
}


def compact_workflow(workflow: Workflow, requirement_spec: RequirementSpec | None) -> dict[str, Any]:
    """A node inventory instead of the full canonical dump.

    The full workflow JSON is ~17 KB for a 20-node graph, which on its own exceeds Groq's
    8000 tokens-per-minute allowance and makes every request fail with a 413 no matter how
    long you wait. Almost none of that detail matters for proposing a test: what is needed is
    the shape of the graph, the branch conditions, and what the workflow is supposed to do.
    """
    return {
        "name": workflow.name,
        "nodes": [
            {"id": node.id, "name": node.name, "type": str(node.type), "subtype": node.subtype}
            for node in workflow.nodes
        ],
        "edges": [
            {"from": edge.source, "to": edge.target, "condition": edge.condition, "label": edge.label}
            for edge in workflow.edges
        ],
        "requirements": [item.text for item in requirement_spec.requirements][:40]
        if requirement_spec
        else [],
    }


def _parse_input(raw: Any) -> dict[str, Any]:
    """Decode the model's input JSON string, tolerating anything that is not an object."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def suggestions_to_tests(payload: str, workflow: Workflow) -> TestGenerationResult:
    """Validate and clamp model output, then map it onto WorkflowTest.

    Raw model output is never trusted: unknown node ids are dropped from expected_path, and a
    suggestion without a usable name is discarded rather than persisted.
    """
    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise MalformedAIResponse("AI provider returned malformed workflow test JSON.") from exc

    node_ids = {node.id for node in workflow.nodes}
    tests: list[WorkflowTest] = []
    for raw in (data or {}).get("tests", []) or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        expected_path = [node for node in raw.get("expected_path") or [] if node in node_ids]
        tests.append(
            WorkflowTest(
                workflow_id=workflow.id,
                name=name[:200],
                description=str(raw.get("description") or "")[:500],
                generated_by=TestGeneratedBy.AI,
                input_data=_parse_input(raw.get("input_json")),
                mocked_integrations=default_mocks(workflow),
                expected_path=expected_path,
                expected_side_effects=[str(item)[:200] for item in raw.get("expected_side_effects") or []],
                assertions=[
                    WorkflowAssertion(type=AssertionType.NODE_EXECUTED, target=node)
                    for node in expected_path
                ],
                tags=[str(tag)[:40] for tag in raw.get("tags") or []] or ["ai_generated"],
                rationale=str(raw.get("rationale") or "")[:500] or None,
            )
        )
    return TestGenerationResult(
        tests=tests,
        generated_by=TestGeneratedBy.AI,
        rationale="AI-proposed tests, validated and clamped to the canonical graph.",
    )


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

        text = _extract_response_text(response_json(response))
        try:
            return TestGenerationResult.model_validate_json(text)
        except (ValidationError, ValueError):
            try:
                return TestGenerationResult.model_validate(json.loads(text))
            except Exception as nested:
                raise MalformedAIResponse("AI provider returned malformed workflow test JSON.") from nested


class GroqTestGenerationProvider(TestGenerationProvider):
    provider_name = "groq"

    def __init__(self, api_key: str, model_name: str, timeout_seconds: float = 20.0) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds

    def generate_tests(self, workflow: Workflow, requirement_spec: RequirementSpec | None) -> TestGenerationResult:
        text = groq_json_completion(
            api_key=self.api_key,
            model=self.model_name,
            system=(
                "Propose WorkflowGuard tests for this workflow graph. Return only json matching "
                "the given schema. Use only node ids from the inventory in expected_path. "
                "input_data keys are read by their last path segment, so use plain field names. "
                "External systems are mocked; never propose real calls."
            ),
            user=json.dumps(compact_workflow(workflow, requirement_spec)),
            schema=TEST_SUGGESTION_SCHEMA,
            schema_name="workflowguard_test_generation",
            timeout_seconds=self.timeout_seconds,
        )
        return suggestions_to_tests(text, workflow)


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
    if provider == "groq":
        if not settings.ai_api_key:
            raise AIProviderUnavailable("WORKFLOWGUARD_AI_API_KEY is not configured.")
        return GroqTestGenerationProvider(settings.ai_api_key, settings.ai_model, settings.ai_timeout_seconds)
    raise AIProviderUnavailable(f"Unsupported AI provider '{settings.ai_provider}'.")
