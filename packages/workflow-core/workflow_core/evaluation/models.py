from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from workflow_core.canonical.models import ValidationSeverity


class EvaluationDimension(StrEnum):
    STRUCTURAL = "structural"
    PROMPT_ALIGNMENT = "prompt_alignment"
    RELIABILITY = "reliability"
    # Retired: no analyzer produces it and it carries no weight. Kept so evaluations
    # stored while it was active still deserialize.
    HALLUCINATION = "hallucination"
    SECURITY = "security"
    MAINTAINABILITY = "maintainability"
    COST_EFFICIENCY = "cost_efficiency"
    TEST_COVERAGE = "test_coverage"


class RequirementKind(StrEnum):
    TRIGGER = "trigger"
    ACTION = "action"
    CONDITION = "condition"
    APPROVAL = "approval"
    INTEGRATION = "integration"
    OUTPUT = "output"
    ERROR_BEHAVIOR = "error_behavior"
    PROHIBITED_BEHAVIOR = "prohibited_behavior"
    CONSTRAINT = "constraint"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RequirementItem(BaseModel):
    id: str = Field(default_factory=lambda: f"req_{uuid4().hex[:10]}")
    kind: RequirementKind
    text: str
    normalized: str
    required: bool = True
    source_excerpt: str | None = None
    #: Which requirements input this came from. Documents and prompts are matched by different
    #: means and a miss from each carries different weight, so the provenance has to survive.
    source: str = "prompt"
    #: Where in the document, e.g. "BR-4" or "Step 3". Always None for prompt requirements.
    source_anchor: str | None = None
    source_document_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(use_enum_values=True)


class RequirementConstraint(BaseModel):
    id: str = Field(default_factory=lambda: f"constraint_{uuid4().hex[:10]}")
    when: str
    must: str
    unless: str | None = None
    source_excerpt: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RequirementSpec(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    source_prompt: str
    summary: str
    trigger: RequirementItem | None = None
    requirements: list[RequirementItem] = Field(default_factory=list)
    required_order: list[str] = Field(default_factory=list)
    constraints: list[RequirementConstraint] = Field(default_factory=list)
    prohibited_behaviors: list[RequirementItem] = Field(default_factory=list)
    expected_outputs: list[RequirementItem] = Field(default_factory=list)
    extraction_method: str = "deterministic"
    confidence: Confidence = Confidence.MEDIUM
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(use_enum_values=True)

    @field_validator("source_prompt")
    @classmethod
    def prompt_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("source_prompt must not be empty")
        return value


class RequirementMatch(BaseModel):
    requirement_id: str
    requirement_text: str
    status: str
    matched_node_ids: list[str] = Field(default_factory=list)
    evidence: str
    confidence: Confidence = Confidence.MEDIUM
    #: "deterministic" or "ai:<provider>". A miss found by token overlap is far weaker
    #: evidence than one an AI judged, and the finding severity depends on which it was.
    match_method: str = "deterministic"

    model_config = ConfigDict(use_enum_values=True)


class EvaluationFinding(BaseModel):
    id: str = Field(default_factory=lambda: f"finding_{uuid4().hex[:10]}")
    rule_id: str
    dimension: EvaluationDimension
    severity: ValidationSeverity
    title: str
    message: str
    expected: str
    found: str
    why_it_matters: str
    node_id: str | None = None
    edge_id: str | None = None
    path: list[str] = Field(default_factory=list)
    remediation: str | None = None
    confidence: Confidence = Confidence.MEDIUM
    #: How many subjects this rule was applicable to - external API nodes, LLM nodes,
    #: requirements. Lets scoring say "3 of 12 external calls lack a timeout" instead of
    #: subtracting a flat penalty three times, which made scores track workflow size.
    rule_population: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(use_enum_values=True)


class DimensionScore(BaseModel):
    dimension: EvaluationDimension
    score: int
    explanation: str
    calculation: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(use_enum_values=True)


class EvaluationResult(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    workflow_id: str
    requirement_spec: RequirementSpec | None = None
    requirement_matches: list[RequirementMatch] = Field(default_factory=list)
    findings: list[EvaluationFinding] = Field(default_factory=list)
    dimension_scores: list[DimensionScore] = Field(default_factory=list)
    overall_score: int
    structural_score: int
    status: str = "completed"
    evaluator_version: str = "part2-deterministic-v2"
    ai_provider: str | None = None
    ai_model: str | None = None
    ai_metadata: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(use_enum_values=True)
