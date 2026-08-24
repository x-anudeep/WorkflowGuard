from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from workflowguard_api.db.session import Base


def json_type() -> JSON:
    return JSON().with_variant(JSONB, "postgresql")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="Default Project")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    workflows: Mapped[list[WorkflowRecord]] = relationship(back_populates="project")


class WorkflowRecord(Base):
    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_format: Mapped[str] = mapped_column(String(50), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", MutableDict.as_mutable(json_type()), default=dict, nullable=False)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    project: Mapped[Project | None] = relationship(back_populates="workflows")
    versions: Mapped[list[WorkflowVersion]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", foreign_keys="WorkflowVersion.workflow_id"
    )
    validation_runs: Mapped[list[ValidationRun]] = relationship(back_populates="workflow", cascade="all, delete-orphan")
    requirement_specs: Mapped[list[RequirementSpecificationRecord]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )
    evaluation_runs: Mapped[list[EvaluationRun]] = relationship(back_populates="workflow", cascade="all, delete-orphan")
    workflow_tests: Mapped[list[WorkflowTestRecord]] = relationship(back_populates="workflow", cascade="all, delete-orphan")
    test_runs: Mapped[list[WorkflowTestRunRecord]] = relationship(back_populates="workflow", cascade="all, delete-orphan")
    cost_estimates: Mapped[list[CostEstimateRecord]] = relationship(back_populates="workflow", cascade="all, delete-orphan")
    repair_proposals: Mapped[list[RepairProposalRecord]] = relationship(back_populates="workflow", cascade="all, delete-orphan")


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("workflow_id", "version_number", name="uq_workflow_version_number"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(json_type()), nullable=False)
    variables_json: Mapped[list] = mapped_column("variables", json_type(), default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    workflow: Mapped[WorkflowRecord] = relationship(back_populates="versions", foreign_keys=[workflow_id])
    file: Mapped[WorkflowFile | None] = relationship(back_populates="version", cascade="all, delete-orphan")
    nodes: Mapped[list[WorkflowNode]] = relationship(back_populates="version", cascade="all, delete-orphan")
    edges: Mapped[list[WorkflowEdge]] = relationship(back_populates="version", cascade="all, delete-orphan")


class WorkflowFile(Base):
    __tablename__ = "workflow_files"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    version: Mapped[WorkflowVersion] = relationship(back_populates="file")


class WorkflowNode(Base):
    __tablename__ = "workflow_nodes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False)
    node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    subtype: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    configuration: Mapped[dict] = mapped_column(MutableDict.as_mutable(json_type()), default=dict, nullable=False)
    input_schema: Mapped[dict | None] = mapped_column(json_type(), nullable=True)
    output_schema: Mapped[dict | None] = mapped_column(json_type(), nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", MutableDict.as_mutable(json_type()), default=dict, nullable=False)

    version: Mapped[WorkflowVersion] = relationship(back_populates="nodes")


class WorkflowEdge(Base):
    __tablename__ = "workflow_edges"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False)
    edge_id: Mapped[str] = mapped_column(String(512), nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", MutableDict.as_mutable(json_type()), default=dict, nullable=False)

    version: Mapped[WorkflowVersion] = relationship(back_populates="edges")


class ValidationRun(Base):
    __tablename__ = "validation_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False)
    structural_quality_score: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    workflow: Mapped[WorkflowRecord] = relationship(back_populates="validation_runs")
    findings: Mapped[list[ValidationFindingRecord]] = relationship(back_populates="run", cascade="all, delete-orphan")


class ValidationFindingRecord(Base):
    __tablename__ = "validation_findings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    validation_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("validation_runs.id"), nullable=False)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    node_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    edge_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    remediation: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", MutableDict.as_mutable(json_type()), default=dict, nullable=False)

    run: Mapped[ValidationRun] = relationship(back_populates="findings")


class RequirementSpecificationRecord(Base):
    __tablename__ = "requirement_specifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False)
    source_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(100), nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    spec_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(json_type()), nullable=False)
    model_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    workflow: Mapped[WorkflowRecord] = relationship(back_populates="requirement_specs")
    evaluation_runs: Mapped[list[EvaluationRun]] = relationship(back_populates="requirement_spec")


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False)
    requirement_spec_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("requirement_specifications.id"), nullable=True
    )
    validation_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("validation_runs.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="completed")
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    structural_score: Mapped[float] = mapped_column(Float, nullable=False)
    evaluator_version: Mapped[str] = mapped_column(String(100), nullable=False)
    ai_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ai_metadata: Mapped[dict] = mapped_column(MutableDict.as_mutable(json_type()), default=dict, nullable=False)
    limitations: Mapped[list] = mapped_column(json_type(), default=list, nullable=False)
    requirement_matches: Mapped[list] = mapped_column(json_type(), default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    workflow: Mapped[WorkflowRecord] = relationship(back_populates="evaluation_runs")
    requirement_spec: Mapped[RequirementSpecificationRecord | None] = relationship(back_populates="evaluation_runs")
    findings: Mapped[list[EvaluationFindingRecord]] = relationship(back_populates="run", cascade="all, delete-orphan")
    dimension_scores: Mapped[list[DimensionScoreRecord]] = relationship(back_populates="run", cascade="all, delete-orphan")


class EvaluationFindingRecord(Base):
    __tablename__ = "evaluation_findings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluation_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_runs.id"), nullable=False)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False)
    dimension: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    expected: Mapped[str] = mapped_column(Text, nullable=False)
    found: Mapped[str] = mapped_column(Text, nullable=False)
    why_it_matters: Mapped[str] = mapped_column(Text, nullable=False)
    node_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    edge_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    path_json: Mapped[list] = mapped_column("path", json_type(), default=list, nullable=False)
    remediation: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", MutableDict.as_mutable(json_type()), default=dict, nullable=False)

    run: Mapped[EvaluationRun] = relationship(back_populates="findings")


class DimensionScoreRecord(Base):
    __tablename__ = "dimension_scores"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluation_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_runs.id"), nullable=False)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False)
    dimension: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    calculation: Mapped[dict] = mapped_column(MutableDict.as_mutable(json_type()), default=dict, nullable=False)

    run: Mapped[EvaluationRun] = relationship(back_populates="dimension_scores")


class WorkflowTestRecord(Base):
    __tablename__ = "workflow_tests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), nullable=False)
    version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_versions.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(50), nullable=False)
    input_data: Mapped[dict] = mapped_column(MutableDict.as_mutable(json_type()), default=dict, nullable=False)
    mocked_integrations: Mapped[list] = mapped_column(json_type(), default=list, nullable=False)
    failure_injections: Mapped[list] = mapped_column(json_type(), default=list, nullable=False)
    expected_path: Mapped[list] = mapped_column(json_type(), default=list, nullable=False)
    expected_outputs: Mapped[dict] = mapped_column(MutableDict.as_mutable(json_type()), default=dict, nullable=False)
    expected_side_effects: Mapped[list] = mapped_column(json_type(), default=list, nullable=False)
    forbidden_side_effects: Mapped[list] = mapped_column(json_type(), default=list, nullable=False)
    assertions: Mapped[list] = mapped_column(json_type(), default=list, nullable=False)
    expected_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(json_type(), default=list, nullable=False)
    importance: Mapped[str] = mapped_column(String(50), nullable=False)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_requirement_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", MutableDict.as_mutable(json_type()), default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    workflow: Mapped[WorkflowRecord] = relationship(back_populates="workflow_tests")
    runs: Mapped[list[WorkflowTestRunRecord]] = relationship(back_populates="test", cascade="all, delete-orphan")


class WorkflowTestRunRecord(Base):
    __tablename__ = "workflow_test_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False)
    test_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_tests.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    execution_trace: Mapped[dict] = mapped_column(MutableDict.as_mutable(json_type()), default=dict, nullable=False)
    assertion_results: Mapped[list] = mapped_column(json_type(), default=list, nullable=False)
    failures: Mapped[list] = mapped_column(json_type(), default=list, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage: Mapped[dict] = mapped_column(MutableDict.as_mutable(json_type()), default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    workflow: Mapped[WorkflowRecord] = relationship(back_populates="test_runs")
    test: Mapped[WorkflowTestRecord] = relationship(back_populates="runs")


class PricingCatalogRecord(Base):
    __tablename__ = "pricing_catalog"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    effective_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_unit_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    output_unit_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    call_unit_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", MutableDict.as_mutable(json_type()), default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CostScenarioRecord(Base):
    __tablename__ = "cost_scenarios"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    inputs_json: Mapped[dict] = mapped_column("inputs", MutableDict.as_mutable(json_type()), default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CostEstimateRecord(Base):
    __tablename__ = "cost_estimates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False)
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cost_scenarios.id"), nullable=True)
    cost_per_run: Mapped[float] = mapped_column(Float, nullable=False)
    daily_cost: Mapped[float] = mapped_column(Float, nullable=False)
    monthly_cost: Mapped[float] = mapped_column(Float, nullable=False)
    annual_cost: Mapped[float] = mapped_column(Float, nullable=False)
    scenario_json: Mapped[dict] = mapped_column("scenario", MutableDict.as_mutable(json_type()), default=dict, nullable=False)
    line_items: Mapped[list] = mapped_column(json_type(), default=list, nullable=False)
    assumptions: Mapped[list] = mapped_column(json_type(), default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    workflow: Mapped[WorkflowRecord] = relationship(back_populates="cost_estimates")
    optimization_findings: Mapped[list[OptimizationFindingRecord]] = relationship(back_populates="estimate", cascade="all, delete-orphan")


class OptimizationFindingRecord(Base):
    __tablename__ = "optimization_findings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), nullable=False)
    cost_estimate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cost_estimates.id"), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    node_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    estimated_monthly_savings: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    confidence: Mapped[str] = mapped_column(String(50), nullable=False)
    deterministic: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", MutableDict.as_mutable(json_type()), default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    estimate: Mapped[CostEstimateRecord] = relationship(back_populates="optimization_findings")


class RepairProposalRecord(Base):
    __tablename__ = "repair_proposals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False)
    finding_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="proposed")
    patch_json: Mapped[dict] = mapped_column("patch", MutableDict.as_mutable(json_type()), nullable=False)
    preview_json: Mapped[dict] = mapped_column("preview", MutableDict.as_mutable(json_type()), default=dict, nullable=False)
    safety_flags: Mapped[list] = mapped_column(json_type(), default=list, nullable=False)
    accepted_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_versions.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    workflow: Mapped[WorkflowRecord] = relationship(back_populates="repair_proposals")
    validation_results: Mapped[list[RepairValidationResultRecord]] = relationship(back_populates="proposal", cascade="all, delete-orphan")


class RepairValidationResultRecord(Base):
    __tablename__ = "repair_validation_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repair_proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repair_proposals.id"), nullable=False)
    result_type: Mapped[str] = mapped_column(String(100), nullable=False)
    result_json: Mapped[dict] = mapped_column("result", MutableDict.as_mutable(json_type()), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    proposal: Mapped[RepairProposalRecord] = relationship(back_populates="validation_results")
