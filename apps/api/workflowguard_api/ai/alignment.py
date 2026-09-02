from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError
from workflow_core.canonical.models import Workflow
from workflow_core.evaluation.models import Confidence, RequirementMatch, RequirementSpec

from workflowguard_api.ai.errors import (
    AIProviderError,
    AIProviderUnavailable,
    MalformedAIResponse,
)
from workflowguard_api.ai.groq_client import groq_json_completion
from workflowguard_api.core.config import Settings

OPENAI_URL = "https://api.openai.com/v1/chat/completions"

SYSTEM_PROMPT = (
    "You decide whether each requirement is implemented by the given workflow graph. "
    "Requirements may come from a business requirements document, so they are written in "
    "business language while nodes are named in technical language; judge intent, not wording. "
    "Return one verdict per requirement id. Use only node ids that appear in the inventory. "
    "Answer 'missing' only when no node or path plausibly implements the requirement."
)

#: Flat and $ref-free so Groq's strict json_schema mode accepts it.
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "requirement_id": {"type": "string"},
                    "status": {"type": "string", "enum": ["matched", "partial", "missing"]},
                    "matched_node_ids": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["requirement_id", "status", "matched_node_ids", "evidence", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["matches"],
    "additionalProperties": False,
}


class _MatchSuggestion(BaseModel):
    requirement_id: str
    status: str = "missing"
    matched_node_ids: list[str] = Field(default_factory=list)
    evidence: str = ""
    confidence: str = "medium"


class _MatchSuggestions(BaseModel):
    matches: list[_MatchSuggestion] = Field(default_factory=list)


class AlignmentProvider(ABC):
    provider_name: str
    model_name: str | None

    @abstractmethod
    def match_requirements(self, spec: RequirementSpec, workflow: Workflow) -> list[RequirementMatch]:
        raise NotImplementedError


class NoopAlignmentProvider(AlignmentProvider):
    provider_name = "none"
    model_name = None

    def match_requirements(self, spec: RequirementSpec, workflow: Workflow) -> list[RequirementMatch]:
        raise AIProviderUnavailable("No AI alignment provider is configured.")


class OpenAIAlignmentProvider(AlignmentProvider):
    provider_name = "openai"

    def __init__(self, api_key: str, model_name: str, timeout_seconds: float = 20.0) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds

    def match_requirements(self, spec: RequirementSpec, workflow: Workflow) -> list[RequirementMatch]:
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(_request_payload(spec, workflow))},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            response = httpx.post(
                OPENAI_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise AIProviderError("OpenAI alignment request timed out.") from exc
        if response.status_code in {401, 403}:
            raise AIProviderUnavailable("OpenAI rejected the configured credentials.")
        if response.status_code >= 400:
            raise AIProviderError(f"OpenAI alignment request failed with {response.status_code}.")
        text = response.json()["choices"][0]["message"]["content"]
        return _clamp(text, spec, workflow, f"ai:{self.provider_name}")


class GroqAlignmentProvider(AlignmentProvider):
    provider_name = "groq"

    def __init__(self, api_key: str, model_name: str, timeout_seconds: float = 20.0) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds

    def match_requirements(self, spec: RequirementSpec, workflow: Workflow) -> list[RequirementMatch]:
        text = groq_json_completion(
            api_key=self.api_key,
            model=self.model_name,
            system=SYSTEM_PROMPT,
            user=json.dumps(_request_payload(spec, workflow)),
            schema=RESPONSE_SCHEMA,
            schema_name="workflowguard_requirement_matches",
            timeout_seconds=self.timeout_seconds,
        )
        return _clamp(text, spec, workflow, f"ai:{self.provider_name}")


class StaticMockAlignmentProvider(AlignmentProvider):
    provider_name = "mock"
    model_name = "mock-alignment"

    def __init__(self, matches: list[RequirementMatch]) -> None:
        self.matches = matches

    def match_requirements(self, spec: RequirementSpec, workflow: Workflow) -> list[RequirementMatch]:
        return self.matches


def alignment_provider_from_settings(settings: Settings) -> AlignmentProvider:
    provider = settings.ai_provider.lower()
    if provider in {"", "none", "disabled"}:
        return NoopAlignmentProvider()
    if provider == "openai":
        if not settings.ai_api_key:
            raise AIProviderUnavailable("WORKFLOWGUARD_AI_API_KEY is not configured.")
        return OpenAIAlignmentProvider(settings.ai_api_key, settings.ai_model, settings.ai_timeout_seconds)
    if provider == "groq":
        if not settings.ai_api_key:
            raise AIProviderUnavailable("WORKFLOWGUARD_AI_API_KEY is not configured.")
        return GroqAlignmentProvider(settings.ai_api_key, settings.ai_model, settings.ai_timeout_seconds)
    raise AIProviderUnavailable(f"Unsupported AI provider '{settings.ai_provider}'.")


def _request_payload(spec: RequirementSpec, workflow: Workflow) -> dict[str, Any]:
    """A compact node inventory - the full canonical graph is mostly noise for this decision."""
    return {
        "requirements": [
            {
                "id": item.id,
                "kind": str(item.kind),
                "text": item.text,
                "source": item.source,
                "source_anchor": item.source_anchor,
            }
            for item in spec.requirements
        ],
        "nodes": [
            {
                "id": node.id,
                "name": node.name,
                "type": str(node.type),
                "subtype": node.subtype,
                "provider": node.provider,
                "configuration": _trim(node.configuration),
            }
            for node in workflow.nodes
        ],
        "edges": [
            {"source": edge.source, "target": edge.target, "label": edge.label, "condition": edge.condition}
            for edge in workflow.edges
        ],
    }


def _trim(configuration: dict[str, Any] | None, limit: int = 240) -> dict[str, Any]:
    if not configuration:
        return {}
    trimmed: dict[str, Any] = {}
    for key, value in configuration.items():
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        trimmed[key] = text[:limit]
    return trimmed


def _clamp(text: str, spec: RequirementSpec, workflow: Workflow, method: str) -> list[RequirementMatch]:
    """Validate and bound the model's verdicts.

    Raw model output is never trusted: unknown requirement ids and node ids are dropped, an
    unrecognised status becomes 'missing', and any requirement the model simply forgot is
    treated as missing rather than silently passing.
    """
    try:
        suggestions = _MatchSuggestions.model_validate_json(text)
    except (ValidationError, ValueError):
        try:
            suggestions = _MatchSuggestions.model_validate(json.loads(text))
        except Exception as nested:
            raise MalformedAIResponse("AI provider returned malformed requirement match JSON.") from nested

    by_id = {item.id: item for item in spec.requirements}
    node_ids = {node.id for node in workflow.nodes}
    matches: dict[str, RequirementMatch] = {}

    for suggestion in suggestions.matches:
        requirement = by_id.get(suggestion.requirement_id)
        if requirement is None:
            continue
        status = suggestion.status if suggestion.status in {"matched", "partial", "missing"} else "missing"
        matched_nodes = [node_id for node_id in suggestion.matched_node_ids if node_id in node_ids]
        if status == "matched" and not matched_nodes:
            status = "missing"
        confidence = _confidence(suggestion.confidence)
        if status == "partial":
            # Downstream (ordering checks, the UI) only understands matched/missing, so a
            # partial is recorded as a low-confidence match rather than a third status.
            status = "matched" if matched_nodes else "missing"
            confidence = Confidence.LOW
        matches[requirement.id] = RequirementMatch(
            requirement_id=requirement.id,
            requirement_text=requirement.text,
            status=status,
            matched_node_ids=matched_nodes[:3],
            evidence=suggestion.evidence[:500]
            or ("Matched by AI requirement alignment." if status == "matched" else "No implementing node identified."),
            confidence=confidence,
            match_method=method,
        )

    for requirement in spec.requirements:
        if requirement.id not in matches:
            matches[requirement.id] = RequirementMatch(
                requirement_id=requirement.id,
                requirement_text=requirement.text,
                status="missing",
                evidence="The model returned no verdict for this requirement.",
                confidence=Confidence.LOW,
                match_method=method,
            )
    return [matches[item.id] for item in spec.requirements]


def _confidence(value: str) -> Confidence:
    try:
        return Confidence(value.lower())
    except ValueError:
        return Confidence.MEDIUM
