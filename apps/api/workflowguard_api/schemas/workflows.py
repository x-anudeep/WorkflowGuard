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


class AttachmentRead(BaseModel):
    id: UUID
    workflow_id: UUID
    version_id: UUID | None = None
    kind: str
    filename: str
    content_type: str | None = None
    size_bytes: int
    clause_count: int
    created_at: datetime


class AttachmentDetail(AttachmentRead):
    raw_content: str
    sections: list[dict[str, Any]] = Field(default_factory=list)
    clauses: list[dict[str, Any]] = Field(default_factory=list)


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
    total_workflow_versions: int = 0
    total_validation_runs: int
    average_structural_score: float
    critical_issues: int
    total_evaluation_runs: int = 0
    average_overall_score: float = 0
    average_quality_score: float = 0
    total_workflow_tests: int = 0
    test_pass_rate: float = 0
    average_coverage: float = 0
    latest_test_coverage: float = 0
    failing_test_runs: int = 0
    latest_monthly_cost: float = 0
    potential_cost_savings: float = 0
    open_repair_proposals: int = 0
    charts: dict[str, Any] = Field(default_factory=dict)
    recent_workflows: list[WorkflowSummary]


class AuditEventRead(BaseModel):
    id: UUID
    workflow_id: UUID | None = None
    version_id: UUID | None = None
    event_type: str
    actor: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class QualityGateConfigRead(BaseModel):
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


class QualityGateReasonRead(BaseModel):
    rule_id: str
    passed: bool
    title: str
    message: str
    expected: str
    actual: str
    severity: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class QualityGateRunRead(BaseModel):
    id: UUID
    workflow_id: UUID
    version_id: UUID
    status: str
    score: float
    config: QualityGateConfigRead
    dimensions: dict[str, float | None] = Field(default_factory=dict)
    reasons: list[QualityGateReasonRead]
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


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
    #: Defaulted so evaluation runs stored before matching became AI-assisted still read back.
    match_method: str = "deterministic"


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


class FuzzCaseRead(BaseModel):
    id: UUID
    case_id: str
    name: str
    description: str
    strategy: str
    verdict: str
    observed: str
    generated_by: str
    seed: int
    input_data: dict[str, Any] = Field(default_factory=dict)
    failure_injections: list[dict[str, Any]] = Field(default_factory=list)
    targeted_node_ids: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    execution_trace: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class FuzzRunRead(BaseModel):
    id: UUID
    workflow_id: UUID
    version_id: UUID
    seed: int
    total_cases: int
    exercised_cases: int
    handled: int
    unhandled_crash: int
    silent_success: int
    hung: int
    not_triggered: int
    robustness_score: int
    generated_by: str
    ai_provider: str | None = None
    ai_model: str | None = None
    ai_metadata: dict[str, Any] = Field(default_factory=dict)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    created_at: datetime
    cases: list[FuzzCaseRead] = Field(default_factory=list)


class FuzzRunRequest(BaseModel):
    use_ai: bool = True
    seed: int | None = None
    max_cases: int | None = Field(default=None, ge=1, le=500)


class PricingEntryCreate(BaseModel):
    category: str
    provider: str
    model: str | None = None
    effective_date: datetime
    input_unit_cost: float = 0
    output_unit_cost: float = 0
    call_unit_cost: float = 0
    unit: str = "call"
    currency: str = "USD"
    source: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PricingEntryRead(PricingEntryCreate):
    id: UUID
    created_at: datetime


class CostScenarioCreate(BaseModel):
    name: str = "Default scenario"
    executions_per_day: int = 100
    executions_per_month: int | None = None
    average_payload_kb: float = 10
    average_input_tokens: int = 1000
    average_output_tokens: int = 300
    failure_retry_rate: float = 0.05
    metadata: dict[str, Any] = Field(default_factory=dict)


class CostLineItemRead(BaseModel):
    node_id: str | None = None
    node_name: str | None = None
    category: str
    provider: str | None = None
    model: str | None = None
    calls_per_execution: float
    input_tokens: int
    output_tokens: int
    unit_cost: float
    estimated_cost_per_run: float
    pricing_assumption: dict[str, Any] = Field(default_factory=dict)
    explanation: str


class OptimizationFindingRead(BaseModel):
    id: UUID | str
    rule_id: str
    title: str
    message: str
    category: str
    node_id: str | None = None
    estimated_monthly_savings: float
    confidence: str
    deterministic: bool
    recommendation: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class CostEstimateRead(BaseModel):
    id: UUID | str
    workflow_id: UUID | str
    version_id: UUID | str | None = None
    scenario: dict[str, Any]
    line_items: list[CostLineItemRead]
    cost_per_run: float
    daily_cost: float
    monthly_cost: float
    annual_cost: float
    assumptions: list[str]
    optimization_findings: list[OptimizationFindingRead] = Field(default_factory=list)
    created_at: datetime


class VersionCompareRead(BaseModel):
    workflow_a_id: str
    workflow_b_id: str
    nodes_added: list[str]
    nodes_removed: list[str]
    edges_added: list[str]
    edges_removed: list[str]
    configuration_changed: list[str]
    validation_score_delta: float | None = None
    prompt_alignment_delta: float | None = None
    security_delta: float | None = None
    reliability_delta: float | None = None
    test_coverage_delta: float | None = None
    estimated_cost_delta: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RepairGenerateRequest(BaseModel):
    finding: dict[str, Any] | None = None
    use_ai: bool = True


class RepairDecisionRequest(BaseModel):
    reason: str | None = None


class RepairProposalRead(BaseModel):
    id: UUID
    workflow_id: UUID
    version_id: UUID
    finding_id: str | None = None
    status: str
    patch: dict[str, Any]
    preview: dict[str, Any]
    safety_flags: list[str]
    accepted_version_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
