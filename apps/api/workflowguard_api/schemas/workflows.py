from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class WorkflowCreate(BaseModel):
    name: str
    source_format: str
    source_type: str = "unknown"
    source_prompt: str | None = None
    canonical: dict[str, Any]


class WorkflowSummary(BaseModel):
    id: UUID
    name: str
    source_format: str
    source_type: str
    structural_quality_score: float | None = None
    critical_findings: int = 0
    created_at: datetime
    updated_at: datetime


class WorkflowDetail(WorkflowSummary):
    source_prompt: str | None = None
    metadata: dict[str, Any]
    current_version_id: UUID | None = None
    canonical: dict[str, Any]


class WorkflowVersionRead(BaseModel):
    id: UUID
    workflow_id: UUID
    version_number: int
    created_at: datetime


class GraphRead(BaseModel):
    workflow_id: UUID
    version_id: UUID
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class ValidationFindingRead(BaseModel):
    id: UUID | None = None
    rule_id: str
    severity: str
    title: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None
    remediation: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ValidationRunRead(BaseModel):
    id: UUID
    workflow_id: UUID
    version_id: UUID
    structural_quality_score: float
    status: str
    created_at: datetime
    findings: list[ValidationFindingRead]


class DashboardMetrics(BaseModel):
    total_workflows: int
    total_validation_runs: int
    average_structural_score: float
    critical_issues: int
    recent_workflows: list[WorkflowSummary]
