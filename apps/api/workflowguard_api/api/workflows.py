from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session
from workflow_core.canonical.models import SourceType, Workflow
from workflow_core.parsers.errors import WorkflowParseError

from workflowguard_api.db.session import get_db
from workflowguard_api.models.db import ValidationRun, WorkflowRecord
from workflowguard_api.schemas.workflows import (
    DashboardMetrics,
    DimensionScoreRead,
    EvaluationFindingRead,
    EvaluationRequest,
    EvaluationRunRead,
    GraphRead,
    RequirementSpecRead,
    ValidationFindingRead,
    ValidationRunRead,
    WorkflowCreate,
    WorkflowDetail,
    WorkflowSummary,
    WorkflowVersionRead,
)
from workflowguard_api.services.evaluations import EvaluationNotFoundError, EvaluationService
from workflowguard_api.services.workflows import WorkflowNotFoundError, WorkflowService

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/dashboard", response_model=DashboardMetrics)
def dashboard(db: Session = Depends(get_db)) -> DashboardMetrics:
    service = WorkflowService(db)
    evaluation_service = EvaluationService(db)
    metrics = service.dashboard_metrics()
    evaluation_metrics = evaluation_service.dashboard_metrics()
    return DashboardMetrics(
        total_workflows=metrics["total_workflows"],
        total_validation_runs=metrics["total_validation_runs"],
        average_structural_score=metrics["average_structural_score"],
        critical_issues=metrics["critical_issues"],
        total_evaluation_runs=evaluation_metrics["total_evaluation_runs"],
        average_overall_score=evaluation_metrics["average_overall_score"],
        recent_workflows=[_summary(record) for record in metrics["recent_workflows"]],
    )


@router.post("/workflows", response_model=WorkflowDetail, status_code=status.HTTP_201_CREATED)
def create_workflow(payload: WorkflowCreate, db: Session = Depends(get_db)) -> WorkflowDetail:
    try:
        workflow = Workflow.model_validate(payload.canonical)
        workflow.name = payload.name
        workflow.source_format = payload.source_format
        workflow.source_type = payload.source_type
        workflow.source_prompt = payload.source_prompt
        record, _run = WorkflowService(db).create_from_canonical(workflow)
        return _detail(WorkflowService(db).get_workflow(record.id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/workflows/upload", response_model=WorkflowDetail, status_code=status.HTTP_201_CREATED)
async def upload_workflow(
    file: UploadFile = File(...),
    source_type: SourceType = Form(SourceType.UNKNOWN),
    source_prompt: str | None = Form(None),
    db: Session = Depends(get_db),
) -> WorkflowDetail:
    content = await file.read()
    try:
        record, _run = WorkflowService(db).upload(
            filename=file.filename or "workflow",
            content=content,
            source_type=source_type,
            source_prompt=source_prompt,
            content_type=file.content_type,
        )
        return _detail(record)
    except WorkflowParseError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/workflows", response_model=list[WorkflowSummary])
def list_workflows(db: Session = Depends(get_db)) -> list[WorkflowSummary]:
    return [_summary(record) for record in WorkflowService(db).list_workflows()]


@router.get("/workflows/{workflow_id}", response_model=WorkflowDetail)
def get_workflow(workflow_id: UUID, db: Session = Depends(get_db)) -> WorkflowDetail:
    try:
        return _detail(WorkflowService(db).get_workflow(workflow_id))
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc


@router.get("/workflows/{workflow_id}/versions", response_model=list[WorkflowVersionRead])
def versions(workflow_id: UUID, db: Session = Depends(get_db)) -> list[WorkflowVersionRead]:
    try:
        record = WorkflowService(db).get_workflow(workflow_id)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc
    return [
        WorkflowVersionRead(id=version.id, workflow_id=version.workflow_id, version_number=version.version_number, created_at=version.created_at)
        for version in sorted(record.versions, key=lambda item: item.version_number)
    ]


@router.post("/workflows/{workflow_id}/validate", response_model=ValidationRunRead)
def validate(workflow_id: UUID, db: Session = Depends(get_db)) -> ValidationRunRead:
    try:
        return _validation_run(WorkflowService(db).validate(workflow_id))
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc


@router.get("/workflows/{workflow_id}/validation", response_model=ValidationRunRead | None)
def latest_validation(workflow_id: UUID, db: Session = Depends(get_db)) -> ValidationRunRead | None:
    try:
        WorkflowService(db).get_workflow(workflow_id)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc
    run = WorkflowService(db).latest_validation(workflow_id)
    return _validation_run(run) if run else None


@router.get("/workflows/{workflow_id}/graph", response_model=GraphRead)
def graph(workflow_id: UUID, db: Session = Depends(get_db)) -> GraphRead:
    try:
        service = WorkflowService(db)
        record = service.get_workflow(workflow_id)
        version = service.get_current_version(record)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc
    canonical = version.canonical_json
    return GraphRead(
        workflow_id=record.id,
        version_id=version.id,
        nodes=canonical.get("nodes", []),
        edges=canonical.get("edges", []),
    )


@router.post("/workflows/{workflow_id}/evaluate", response_model=EvaluationRunRead)
def evaluate_workflow(
    workflow_id: UUID,
    payload: EvaluationRequest | None = None,
    db: Session = Depends(get_db),
) -> EvaluationRunRead:
    try:
        run = EvaluationService(db).evaluate(workflow_id, use_ai=payload.use_ai if payload else True)
        return _evaluation_run(run)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc


@router.get("/workflows/{workflow_id}/evaluations", response_model=list[EvaluationRunRead])
def list_evaluations(workflow_id: UUID, db: Session = Depends(get_db)) -> list[EvaluationRunRead]:
    try:
        return [_evaluation_run(run) for run in EvaluationService(db).list_evaluations(workflow_id)]
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc


@router.get("/workflows/{workflow_id}/evaluations/{evaluation_id}", response_model=EvaluationRunRead)
def get_evaluation(workflow_id: UUID, evaluation_id: UUID, db: Session = Depends(get_db)) -> EvaluationRunRead:
    try:
        return _evaluation_run(EvaluationService(db).get_evaluation(workflow_id, evaluation_id))
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc
    except EvaluationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation not found") from exc


@router.get("/workflows/{workflow_id}/requirements", response_model=RequirementSpecRead | None)
def get_requirements(workflow_id: UUID, db: Session = Depends(get_db)) -> RequirementSpecRead | None:
    try:
        spec = EvaluationService(db).latest_requirements(workflow_id)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc
    return _requirement_spec(spec) if spec else None


def _summary(record: WorkflowRecord) -> WorkflowSummary:
    latest = _latest_run(record)
    return WorkflowSummary(
        id=record.id,
        name=record.name,
        source_format=record.source_format,
        source_type=record.source_type,
        structural_quality_score=latest.structural_quality_score if latest else None,
        critical_findings=sum(1 for finding in latest.findings if finding.severity == "CRITICAL") if latest else 0,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _detail(record: WorkflowRecord) -> WorkflowDetail:
    summary = _summary(record)
    version = next((item for item in record.versions if item.id == record.current_version_id), record.versions[-1])
    return WorkflowDetail(
        **summary.model_dump(),
        source_prompt=record.source_prompt,
        metadata=record.metadata_json,
        current_version_id=record.current_version_id,
        canonical=version.canonical_json,
    )


def _latest_run(record: WorkflowRecord) -> ValidationRun | None:
    if not record.validation_runs:
        return None
    return sorted(record.validation_runs, key=lambda run: run.created_at)[-1]


def _validation_run(run: ValidationRun) -> ValidationRunRead:
    return ValidationRunRead(
        id=run.id,
        workflow_id=run.workflow_id,
        version_id=run.version_id,
        structural_quality_score=run.structural_quality_score,
        status=run.status,
        created_at=run.created_at,
        findings=[
            ValidationFindingRead(
                id=finding.id,
                rule_id=finding.rule_id,
                severity=finding.severity,
                title=finding.title,
                message=finding.message,
                node_id=finding.node_id,
                edge_id=finding.edge_id,
                remediation=finding.remediation,
                metadata=finding.metadata_json,
            )
            for finding in run.findings
        ],
    )


def _requirement_spec(spec) -> RequirementSpecRead:
    return RequirementSpecRead(
        id=spec.id,
        workflow_id=spec.workflow_id,
        version_id=spec.version_id,
        source_prompt=spec.source_prompt,
        extraction_method=spec.extraction_method,
        confidence=spec.confidence,
        spec=spec.spec_json,
        model_provider=spec.model_provider,
        model_name=spec.model_name,
        created_at=spec.created_at,
    )


def _evaluation_run(run) -> EvaluationRunRead:
    return EvaluationRunRead(
        id=run.id,
        workflow_id=run.workflow_id,
        version_id=run.version_id,
        requirement_spec_id=run.requirement_spec_id,
        validation_run_id=run.validation_run_id,
        status=run.status,
        overall_score=run.overall_score,
        structural_score=run.structural_score,
        evaluator_version=run.evaluator_version,
        ai_provider=run.ai_provider,
        ai_model=run.ai_model,
        ai_metadata=run.ai_metadata,
        limitations=run.limitations,
        requirement_matches=run.requirement_matches,
        dimension_scores=[
            DimensionScoreRead(
                dimension=score.dimension,
                score=score.score,
                explanation=score.explanation,
                calculation=score.calculation,
            )
            for score in sorted(run.dimension_scores, key=lambda item: item.dimension)
        ],
        findings=[
            EvaluationFindingRead(
                id=finding.id,
                rule_id=finding.rule_id,
                dimension=finding.dimension,
                severity=finding.severity,
                title=finding.title,
                message=finding.message,
                expected=finding.expected,
                found=finding.found,
                why_it_matters=finding.why_it_matters,
                node_id=finding.node_id,
                edge_id=finding.edge_id,
                path=finding.path_json,
                remediation=finding.remediation,
                confidence=finding.confidence,
                metadata=finding.metadata_json,
            )
            for finding in run.findings
        ],
        requirement_spec=_requirement_spec(run.requirement_spec) if run.requirement_spec else None,
        created_at=run.created_at,
    )
