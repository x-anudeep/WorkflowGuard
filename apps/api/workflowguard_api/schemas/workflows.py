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
    total_evaluation_runs: int = 0
    average_overall_score: float = 0
    total_workflow_tests: int = 0
    latest_test_coverage: float = 0
    failing_test_runs: int = 0
    recent_workflows: list[WorkflowSummary]


class EvaluationRequest(BaseModel):
    use_ai: bool = True


class RequirementSpecRead(BaseModel):
    id: UUID | None = None
    workflow_id: UUID | None = None
    version_id: UUID | None = None
    source_prompt: str
    extraction_method: str
    confidence: str
    spec: dict[str, Any]
    model_provider: str | None = None
    model_name: str | None = None
    created_at: datetime | None = None


class EvaluationFindingRead(BaseModel):
    id: UUID | None = None
    rule_id: str
    dimension: str
    severity: str
    title: str
    message: str
    expected: str
    found: str
    why_it_matters: str
    node_id: str | None = None
    edge_id: str | None = None
    path: list[str] = Field(default_factory=list)
    remediation: str | None = None
    confidence: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DimensionScoreRead(BaseModel):
    dimension: str
    score: float
    explanation: str
    calculation: dict[str, Any] = Field(default_factory=dict)


class RequirementMatchRead(BaseModel):
    requirement_id: str
    requirement_text: str
    status: str
    matched_node_ids: list[str] = Field(default_factory=list)
    evidence: str
    confidence: str


class EvaluationRunRead(BaseModel):
    id: UUID
    workflow_id: UUID
    version_id: UUID
    requirement_spec_id: UUID | None = None
    validation_run_id: UUID | None = None
    status: str
    overall_score: float
    structural_score: float
    evaluator_version: str
    ai_provider: str | None = None
    ai_model: str | None = None
    ai_metadata: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    requirement_matches: list[RequirementMatchRead] = Field(default_factory=list)
    dimension_scores: list[DimensionScoreRead] = Field(default_factory=list)
    findings: list[EvaluationFindingRead] = Field(default_factory=list)
    requirement_spec: RequirementSpecRead | None = None
    created_at: datetime


class MockIntegrationRead(BaseModel):
    node_id: str
    response: Any = None
    status_code: int | None = None
    latency_ms: int = 25
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FailureInjectionRead(BaseModel):
    node_id: str
    failure_type: str
    occurrence: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowAssertionRead(BaseModel):
    type: str
    target: str | None = None
    expected: Any = None
    description: str | None = None


class WorkflowTestCreate(BaseModel):
    name: str
    description: str
    generated_by: str = "HUMAN"
    input_data: dict[str, Any] = Field(default_factory=dict)
    mocked_integrations: list[MockIntegrationRead] = Field(default_factory=list)
    failure_injections: list[FailureInjectionRead] = Field(default_factory=list)
    expected_path: list[str] = Field(default_factory=list)
    expected_outputs: dict[str, Any] = Field(default_factory=dict)
    expected_side_effects: list[str] = Field(default_factory=list)
    forbidden_side_effects: list[str] = Field(default_factory=list)
    assertions: list[WorkflowAssertionRead] = Field(default_factory=list)
    expected_error: str | None = None
    tags: list[str] = Field(default_factory=list)
    importance: str = "MEDIUM"
    enabled: bool = True
    rationale: str | None = None
    linked_requirement_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowTestRead(WorkflowTestCreate):
    id: UUID
    workflow_id: UUID
    version_id: UUID | None = None
    latest_status: str | None = None
    latest_run_id: UUID | None = None
    latest_run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class GenerateTestsRequest(BaseModel):
    use_ai: bool = True
    replace_existing: bool = False


class GenerateTestsResponse(BaseModel):
    generated: int
    tests: list[WorkflowTestRead]
    rationale: str
    warnings: list[str] = Field(default_factory=list)


class RunWorkflowTestsRequest(BaseModel):
    test_ids: list[UUID] | None = None


class AssertionResultRead(BaseModel):
    assertion: WorkflowAssertionRead
    passed: bool
    message: str


class CoverageRead(BaseModel):
    node_coverage: float
    edge_coverage: float
    branch_coverage: float
    requirement_coverage: float
    overall_coverage: float
    covered_nodes: list[str] = Field(default_factory=list)
    covered_edges: list[str] = Field(default_factory=list)
    covered_requirements: list[str] = Field(default_factory=list)
    calculation: dict[str, Any] = Field(default_factory=dict)


class WorkflowTestRunRead(BaseModel):
    id: UUID
    workflow_id: UUID
    version_id: UUID
    test_id: UUID
    status: str
    execution_trace: dict[str, Any]
    assertion_results: list[AssertionResultRead] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    duration_ms: int
    coverage: CoverageRead | None = None
    created_at: datetime


class TestRunSummary(BaseModel):
    total_tests: int
    passed: int
    failed: int
    error: int
    skipped: int
    latest_coverage: float
    last_run_at: datetime | None = None
    runs: list[WorkflowTestRunRead]
