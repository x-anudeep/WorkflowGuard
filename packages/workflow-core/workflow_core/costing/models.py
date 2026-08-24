from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class CostCategory(StrEnum):
    LLM = "llm"
    EXTERNAL_API = "external_api"
    COMPUTE = "compute"
    DATABASE = "database"
    STORAGE = "storage"
    EMAIL_MESSAGING = "email_messaging"
    OTHER = "other"


class PricingUnit(StrEnum):
    TOKEN_1K = "1k_tokens"
    CALL = "call"
    EXECUTION = "execution"
    MB = "mb"


class PricingEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    category: CostCategory
    provider: str
    model: str | None = None
    effective_date: date
    input_unit_cost: float = 0
    output_unit_cost: float = 0
    call_unit_cost: float = 0
    unit: PricingUnit = PricingUnit.CALL
    currency: str = "USD"
    source: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CostScenario(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = "Default scenario"
    executions_per_day: int = 100
    executions_per_month: int | None = None
    average_payload_kb: float = 10
    average_input_tokens: int = 1000
    average_output_tokens: int = 300
    failure_retry_rate: float = 0.05
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def monthly_executions(self) -> int:
        return self.executions_per_month if self.executions_per_month is not None else self.executions_per_day * 30


class CostLineItem(BaseModel):
    node_id: str | None = None
    node_name: str | None = None
    category: CostCategory
    provider: str | None = None
    model: str | None = None
    calls_per_execution: float = 1
    input_tokens: int = 0
    output_tokens: int = 0
    unit_cost: float = 0
    estimated_cost_per_run: float
    pricing_assumption: dict[str, Any] = Field(default_factory=dict)
    explanation: str


class CostEstimate(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    workflow_id: str
    workflow_version_id: str | None = None
    scenario: CostScenario
    line_items: list[CostLineItem] = Field(default_factory=list)
    cost_per_run: float
    daily_cost: float
    monthly_cost: float
    annual_cost: float
    assumptions: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OptimizationFinding(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    rule_id: str
    title: str
    message: str
    category: CostCategory
    node_id: str | None = None
    estimated_monthly_savings: float = 0
    confidence: str = "medium"
    deterministic: bool = True
    recommendation: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class CostComparison(BaseModel):
    current: CostEstimate
    optimized: CostEstimate | None = None
    potential_monthly_savings: float = 0
    potential_savings_percent: float = 0
    optimization_findings: list[OptimizationFinding] = Field(default_factory=list)
