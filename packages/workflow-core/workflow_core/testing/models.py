from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TestGeneratedBy(StrEnum):
    HUMAN = "HUMAN"
    AI = "AI"
    SYSTEM = "SYSTEM"


class TestImportance(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TestRunStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


class AssertionType(StrEnum):
    NODE_EXECUTED = "node_executed"
    NODE_NOT_EXECUTED = "node_not_executed"
    EDGE_EXECUTED = "edge_executed"
    OUTPUT_EQUALS = "output_equals"
    OUTPUT_CONTAINS = "output_contains"
    ERROR_OCCURRED = "error_occurred"
    RETRY_COUNT = "retry_count"
    APPROVAL_REQUESTED = "approval_requested"
    EXTERNAL_CALLED = "external_called"
    EXTERNAL_NOT_CALLED = "external_not_called"
    TERMINATED_SUCCESSFULLY = "terminated_successfully"


class FailureType(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    HTTP_500 = "http_500"
    AUTHORIZATION = "authorization"
    UNAVAILABLE = "unavailable"
    MALFORMED_OUTPUT = "malformed_output"


class MockIntegration(BaseModel):
    node_id: str
    response: Any = None
    status_code: int | None = None
    latency_ms: int = 25
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FailureInjection(BaseModel):
    node_id: str
    failure_type: FailureType
    occurrence: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(use_enum_values=True)


class WorkflowAssertion(BaseModel):
    type: AssertionType
    target: str | None = None
    expected: Any = None
    description: str | None = None

    model_config = ConfigDict(use_enum_values=True)


class WorkflowTest(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    workflow_id: str | None = None
    workflow_version_id: str | None = None
    name: str
    description: str
    generated_by: TestGeneratedBy = TestGeneratedBy.SYSTEM
    input_data: dict[str, Any] = Field(default_factory=dict)
    mocked_integrations: list[MockIntegration] = Field(default_factory=list)
    failure_injections: list[FailureInjection] = Field(default_factory=list)
    expected_path: list[str] = Field(default_factory=list)
    expected_outputs: dict[str, Any] = Field(default_factory=dict)
    expected_side_effects: list[str] = Field(default_factory=list)
    forbidden_side_effects: list[str] = Field(default_factory=list)
    assertions: list[WorkflowAssertion] = Field(default_factory=list)
    expected_error: str | None = None
    tags: list[str] = Field(default_factory=list)
    importance: TestImportance = TestImportance.MEDIUM
    enabled: bool = True
    rationale: str | None = None
    linked_requirement_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(use_enum_values=True)

    @field_validator("name", "description")
    @classmethod
    def non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class NodeExecution(BaseModel):
    node_id: str
    node_name: str
    node_type: str
    status: str
    input_data: dict[str, Any] = Field(default_factory=dict)
    output_data: dict[str, Any] = Field(default_factory=dict)
    branch_decision: str | None = None
    mocked: bool = False
    retries: int = 0
    latency_ms: int = 0
    error: str | None = None


class SimulatedCall(BaseModel):
    node_id: str
    provider: str | None = None
    operation: str | None = None
    request: dict[str, Any] = Field(default_factory=dict)
    response: Any = None
    status_code: int | None = None
    latency_ms: int = 0
    error: str | None = None


class SimulationResult(BaseModel):
    workflow_id: str
    test_id: str
    status: TestRunStatus
    execution_order: list[str] = Field(default_factory=list)
    executed_edges: list[str] = Field(default_factory=list)
    node_executions: list[NodeExecution] = Field(default_factory=list)
    branch_decisions: dict[str, str] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    external_calls: list[SimulatedCall] = Field(default_factory=list)
    approval_requests: list[str] = Field(default_factory=list)
    retries: dict[str, int] = Field(default_factory=dict)
    failures: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    token_estimate: int = 0
    #: Where the execution was an approximation rather than a measurement - a construct the
    #: engine could not express faithfully, a node body not yet modelled, an auto-answered
    #: approval. Carried on the result so a report can say so instead of implying the run
    #: exercised something it did not.
    warnings: list[str] = Field(default_factory=list)

    model_config = ConfigDict(use_enum_values=True)


class AssertionResult(BaseModel):
    assertion: WorkflowAssertion
    passed: bool
    message: str


class CoverageResult(BaseModel):
    node_coverage: float
    edge_coverage: float
    branch_coverage: float
    requirement_coverage: float
    overall_coverage: float
    covered_nodes: list[str] = Field(default_factory=list)
    covered_edges: list[str] = Field(default_factory=list)
    covered_requirements: list[str] = Field(default_factory=list)
    calculation: dict[str, Any] = Field(default_factory=dict)


class WorkflowTestRun(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    workflow_id: str
    workflow_version_id: str | None = None
    test_id: str
    status: TestRunStatus
    simulation: SimulationResult
    assertion_results: list[AssertionResult] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    coverage: CoverageResult | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(use_enum_values=True)


class TestGenerationResult(BaseModel):
    tests: list[WorkflowTest]
    generated_by: TestGeneratedBy = TestGeneratedBy.SYSTEM
    rationale: str
    warnings: list[str] = Field(default_factory=list)

    model_config = ConfigDict(use_enum_values=True)
