from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from workflow_core.evaluation.models import EvaluationFinding
from workflow_core.testing.models import (
    FailureInjection,
    SimulationResult,
    TestGeneratedBy,
)


class FuzzStrategy(StrEnum):
    """How a fuzz case was produced."""

    BASELINE = "baseline"
    INPUT_MUTATION = "input_mutation"
    FAILURE_INJECTION = "failure_injection"
    COMBINED = "combined"
    ADVERSARIAL_TEXT = "adversarial_text"


class ErrorHandlingVerdict(StrEnum):
    """What the workflow actually did when the fuzz case perturbed it."""

    HANDLED = "handled"
    UNHANDLED_CRASH = "unhandled_crash"
    SILENT_SUCCESS = "silent_success"
    HUNG = "hung"
    NOT_TRIGGERED = "not_triggered"


class FuzzCase(BaseModel):
    id: str = Field(default_factory=lambda: f"fuzz_{uuid4().hex[:10]}")
    name: str
    description: str
    strategy: FuzzStrategy = FuzzStrategy.INPUT_MUTATION
    seed: int = 0
    input_data: dict[str, Any] = Field(default_factory=dict)
    failure_injections: list[FailureInjection] = Field(default_factory=list)
    targeted_node_ids: list[str] = Field(default_factory=list)
    expected_handling: str | None = None
    generated_by: TestGeneratedBy = TestGeneratedBy.SYSTEM
    rationale: str | None = None
    tags: list[str] = Field(default_factory=list)

    model_config = ConfigDict(use_enum_values=True)

    @field_validator("name", "description")
    @classmethod
    def non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class FuzzCaseResult(BaseModel):
    case: FuzzCase
    verdict: ErrorHandlingVerdict
    simulation: SimulationResult
    observed: str
    evidence: list[str] = Field(default_factory=list)

    model_config = ConfigDict(use_enum_values=True)


class FuzzReport(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    workflow_id: str
    seed: int = 0
    results: list[FuzzCaseResult] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    #: Cases that actually perturbed the workflow - the robustness denominator. Stored
    #: rather than derived so a report rehydrated from the database without its
    #: individual cases still reports what it measured.
    exercised_cases: int = 0
    robustness_score: int = 100
    findings: list[EvaluationFinding] = Field(default_factory=list)
    generated_by: TestGeneratedBy = TestGeneratedBy.SYSTEM
    ai_provider: str | None = None
    ai_model: str | None = None
    ai_metadata: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(use_enum_values=True)
