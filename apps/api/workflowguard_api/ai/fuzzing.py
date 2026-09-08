from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ValidationError
from workflow_core.canonical.models import NodeType, Workflow
from workflow_core.evaluation.models import RequirementSpec
from workflow_core.fuzzing.generator import INJECTABLE_TYPES
from workflow_core.fuzzing.models import FuzzCase, FuzzStrategy
from workflow_core.testing.models import FailureInjection, FailureType, TestGeneratedBy

from workflowguard_api.ai.groq_client import groq_json_completion
from workflowguard_api.ai.providers import AIProviderUnavailable, MalformedAIResponse
from workflowguard_api.core.config import Settings

MAX_OCCURRENCE = 5

SYSTEM_PROMPT = (
    "You are a reliability engineer fuzzing an automation workflow. Propose adversarial test "
    "cases that attack the workflow's ERROR HANDLING specifically: inputs and dependency "
    "failures that a naive implementation would mishandle. Prefer cases grounded in what this "
    "workflow actually does - if it moves money, target double-payment on retry; if it needs "
    "approval, target paths that skip it. Never propose calling real systems. Return only JSON."
)

#: Hand-written and deliberately flat: Groq's strict schema mode rejects the ``$ref``/
#: ``$defs`` output of ``model_json_schema()`` on nested models.
FUZZ_CASE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["cases"],
    "properties": {
        "cases": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                # Groq's strict mode requires *every* property to be listed in `required`;
                # omitting the optional ones is a 400, which then falls back to inlining the
                # whole schema into the prompt. Optional fields are expressed as nullable
                # instead, which the clamping below already tolerates.
                "required": [
                    "name",
                    "description",
                    "input_json",
                    "target_node_ids",
                    "failure_types",
                    "occurrence",
                    "expected_handling",
                    "rationale",
                ],
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "input_json": {
                        "type": "string",
                        "description": "A JSON object of workflow input values, encoded as a string.",
                    },
                    "target_node_ids": {"type": "array", "items": {"type": "string"}},
                    "failure_types": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [item.value for item in FailureType],
                        },
                    },
                    "occurrence": {"type": ["integer", "null"]},
                    "expected_handling": {"type": ["string", "null"]},
                    "rationale": {"type": ["string", "null"]},
                },
            },
        }
    },
}


class _SuggestedCase(BaseModel):
    name: str
    description: str
    input_json: str = "{}"
    target_node_ids: list[str] = []
    failure_types: list[str] = []
    occurrence: int = 1
    expected_handling: str | None = None
    rationale: str | None = None


class _SuggestedCases(BaseModel):
    cases: list[_SuggestedCase] = []


class FuzzGenerationProvider(ABC):
    provider_name: str
    model_name: str | None

    @abstractmethod
    def generate_cases(
        self,
        workflow: Workflow,
        requirement_spec: RequirementSpec | None,
        *,
        max_cases: int,
    ) -> list[FuzzCase]:
        raise NotImplementedError


class NoopFuzzGenerationProvider(FuzzGenerationProvider):
    provider_name = "none"
    model_name = None

    def generate_cases(
        self,
        workflow: Workflow,
        requirement_spec: RequirementSpec | None,
        *,
        max_cases: int,
    ) -> list[FuzzCase]:
        raise AIProviderUnavailable("No AI fuzz-generation provider is configured.")


class GroqFuzzGenerationProvider(FuzzGenerationProvider):
    provider_name = "groq"

    def __init__(self, api_key: str, model_name: str, timeout_seconds: float = 20.0) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds

    def generate_cases(
        self,
        workflow: Workflow,
        requirement_spec: RequirementSpec | None,
        *,
        max_cases: int,
    ) -> list[FuzzCase]:
        injectable = [node for node in workflow.nodes if node.type in INJECTABLE_TYPES]
        user_payload = {
            "max_cases": max_cases,
            "workflow": _workflow_digest(workflow),
            "injectable_nodes": [
                {"id": node.id, "name": node.name, "type": str(node.type), "provider": node.provider}
                for node in injectable
            ],
            "available_failure_types": [item.value for item in FailureType],
            "requirement_summary": requirement_spec.summary if requirement_spec else None,
            "stated_requirements": (
                [item.text for item in requirement_spec.requirements[:20]] if requirement_spec else []
            ),
        }
        text = groq_json_completion(
            api_key=self.api_key,
            model=self.model_name,
            system=SYSTEM_PROMPT,
            user=json.dumps(user_payload),
            schema=FUZZ_CASE_SCHEMA,
            schema_name="workflowguard_fuzz_cases",
            timeout_seconds=self.timeout_seconds,
        )
        try:
            suggested = _SuggestedCases.model_validate_json(text)
        except (ValidationError, ValueError):
            try:
                suggested = _SuggestedCases.model_validate(json.loads(text))
            except Exception as nested:
                raise MalformedAIResponse("Groq returned malformed fuzz case JSON.") from nested
        return _to_fuzz_cases(suggested, workflow, max_cases)


class StaticMockFuzzGenerationProvider(FuzzGenerationProvider):
    provider_name = "mock"
    model_name = "mock-fuzz-generator"

    def __init__(self, cases: list[FuzzCase]) -> None:
        self.cases = cases

    def generate_cases(
        self,
        workflow: Workflow,
        requirement_spec: RequirementSpec | None,
        *,
        max_cases: int,
    ) -> list[FuzzCase]:
        return self.cases[:max_cases]


def fuzz_provider_from_settings(settings: Settings) -> FuzzGenerationProvider:
    provider = settings.ai_provider.lower()
    if provider in {"", "none", "disabled"}:
        return NoopFuzzGenerationProvider()
    if provider in {"groq", "openai"}:
        # Both speak the same chat-completions shape; Groq is the supported endpoint here.
        if not settings.ai_api_key:
            raise AIProviderUnavailable("WORKFLOWGUARD_AI_API_KEY is not configured.")
        if provider == "openai":
            raise AIProviderUnavailable(
                "AI fuzz generation is implemented for the 'groq' provider; "
                "set WORKFLOWGUARD_AI_PROVIDER=groq or run deterministic fuzzing."
            )
        return GroqFuzzGenerationProvider(settings.ai_api_key, settings.ai_model, settings.ai_timeout_seconds)
    raise AIProviderUnavailable(f"Unsupported AI provider '{settings.ai_provider}'.")


def _workflow_digest(workflow: Workflow) -> dict[str, Any]:
    """A compact view of the graph - the full canonical dump wastes most of the context."""
    return {
        "name": workflow.name,
        "source_prompt": workflow.source_prompt,
        "nodes": [
            {
                "id": node.id,
                "name": node.name,
                "type": str(node.type),
                "provider": node.provider,
                "operation": node.operation,
                "configuration_keys": sorted(node.configuration.keys()),
            }
            for node in workflow.nodes
        ],
        "edges": [
            {"source": edge.source, "target": edge.target, "label": edge.label, "condition": edge.condition}
            for edge in workflow.edges
        ],
    }


def _to_fuzz_cases(suggested: _SuggestedCases, workflow: Workflow, max_cases: int) -> list[FuzzCase]:
    """Map validated model output onto FuzzCase, dropping anything that does not fit.

    Model output is untrusted: node ids that do not exist, unknown failure types, and
    unbounded occurrence counts are silently discarded rather than propagated into the
    simulator.
    """
    known_nodes = {node.id: node for node in workflow.nodes}
    valid_failures = {item.value for item in FailureType}
    cases: list[FuzzCase] = []

    for item in suggested.cases[:max_cases]:
        targets = [node_id for node_id in item.target_node_ids if node_id in known_nodes]
        occurrence = max(1, min(MAX_OCCURRENCE, item.occurrence))
        injections = [
            FailureInjection(node_id=node_id, failure_type=FailureType(name), occurrence=occurrence)
            for node_id in targets
            for name in item.failure_types
            if name in valid_failures
            and (name not in {FailureType.MALFORMED_OUTPUT.value} or known_nodes[node_id].type == NodeType.LLM)
        ]
        input_data = _safe_input(item.input_json)
        if not injections and not input_data:
            continue

        strategy = FuzzStrategy.COMBINED if injections and input_data else (
            FuzzStrategy.FAILURE_INJECTION if injections else FuzzStrategy.INPUT_MUTATION
        )
        cases.append(
            FuzzCase(
                name=item.name[:120],
                description=item.description[:500],
                strategy=strategy,
                input_data=input_data,
                failure_injections=injections,
                targeted_node_ids=targets,
                expected_handling=item.expected_handling,
                generated_by=TestGeneratedBy.AI,
                rationale=item.rationale,
                tags=["fuzz", "ai_generated"],
            )
        )
    return cases


def _safe_input(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
