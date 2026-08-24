from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class QualityGateConfig(BaseModel):
    structural_min: float = 90
    prompt_alignment_min: float = 90
    security_min: float = 85
    reliability_min: float = 80
    maintainability_min: float = 70
    test_coverage_min: float = 85
    require_all_critical_tests_pass: bool = True
    allow_critical_security_findings: bool = False
    monthly_cost_increase_max_percent: float = 20
    metadata: dict[str, Any] = Field(default_factory=dict)


class QualityGateReason(BaseModel):
    rule_id: str
    passed: bool
    title: str
    message: str
    expected: str
    actual: str
    severity: Literal["INFO", "WARNING", "ERROR", "CRITICAL"] = "ERROR"
    metadata: dict[str, Any] = Field(default_factory=dict)


class QualityGateResult(BaseModel):
    status: Literal["PASS", "FAIL"]
    score: float
    reasons: list[QualityGateReason]
    config: QualityGateConfig
    dimensions: dict[str, float | None] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
