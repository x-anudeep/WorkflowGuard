from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from workflow_core.canonical.models import SourceType, Workflow
from workflow_core.comparison import VersionComparisonEngine
from workflow_core.costing import CostEstimator, CostScenario, PricingEntry
from workflow_core.parsers.errors import WorkflowParseError
from workflow_core.quality import QualityGateConfig
from workflow_core.testing import WorkflowTest
from workflow_core.validation import ValidationEngine

from workflowguard_api.db.session import get_db
from workflowguard_api.models.db import AuditEventRecord, QualityGateRunRecord, ValidationRun, WorkflowRecord
from workflowguard_api.schemas.workflows import (
    AttachmentDetail,
    AttachmentRead,
    AuditEventRead,
    CostEstimateRead,
    CostScenarioCreate,
    DashboardMetrics,
    DimensionScoreRead,
    EvaluationFindingRead,
    EvaluationRequest,
    EvaluationRunRead,
    FuzzCaseRead,
    FuzzRunRead,
    FuzzRunRequest,
    GenerateTestsRequest,
    GenerateTestsResponse,
    GraphRead,
    OptimizationFindingRead,
    PricingEntryCreate,
    PricingEntryRead,
    QualityGateConfigRead,
    QualityGateRunRead,
    RepairDecisionRequest,
    RepairGenerateRequest,
    RepairProposalRead,
    RequirementSpecRead,
    RunWorkflowTestsRequest,
    TestRunSummary,
    ValidationFindingRead,
    ValidationRunRead,
    VersionCompareRead,
    WorkflowCreate,
    WorkflowDetail,
    WorkflowSummary,
    WorkflowTestCreate,
    WorkflowTestRead,
    WorkflowTestRunRead,
    WorkflowVersionRead,
)
from workflowguard_api.services.attachments import (
    AttachmentNotFoundError,
    AttachmentService,
    UnsupportedAttachmentError,
)
from workflowguard_api.services.audit import AuditService
from workflowguard_api.services.costs import CostService
from workflowguard_api.services.evaluations import EvaluationNotFoundError, EvaluationService
from workflowguard_api.services.fuzzing import FuzzRunNotFoundError, FuzzService
from workflowguard_api.services.platform import PlatformMetricsService
from workflowguard_api.services.quality import QualityGateService
from workflowguard_api.services.repairs import RepairProposalNotFoundError, RepairService
from workflowguard_api.services.reports import ReportService
from workflowguard_api.services.testing import (
    WorkflowTestingService,
    WorkflowTestNotFoundError,
    WorkflowTestRunNotFoundError,
)
from workflowguard_api.services.workflows import WorkflowNotFoundError, WorkflowService

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("select 1"))
    return {"status": "ready"}


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(db: Session = Depends(get_db)) -> str:
    data = PlatformMetricsService(db).dashboard()
    return "\n".join(
        [
            "# HELP workflowguard_workflows_total Total workflows.",
            "# TYPE workflowguard_workflows_total gauge",
            f"workflowguard_workflows_total {data['total_workflows']}",
            "# HELP workflowguard_validation_runs_total Total validation runs.",
            "# TYPE workflowguard_validation_runs_total gauge",
            f"workflowguard_validation_runs_total {data['total_validation_runs']}",
            "# HELP workflowguard_quality_score_average Average quality gate score.",
            "# TYPE workflowguard_quality_score_average gauge",
            f"workflowguard_quality_score_average {data['average_quality_score']}",
        ]
    )


@router.get("/dashboard", response_model=DashboardMetrics)
def dashboard(db: Session = Depends(get_db)) -> DashboardMetrics:
    metrics = PlatformMetricsService(db).dashboard()
    return DashboardMetrics(
        total_workflows=metrics["total_workflows"],
        total_workflow_versions=metrics["total_workflow_versions"],
        total_validation_runs=metrics["total_validation_runs"],
        average_structural_score=metrics["average_structural_score"],
        critical_issues=metrics["critical_issues"],
        total_evaluation_runs=metrics["total_evaluation_runs"],
        average_overall_score=metrics["average_overall_score"],
        average_quality_score=metrics["average_quality_score"],
        total_workflow_tests=metrics["total_workflow_tests"],
        test_pass_rate=metrics["test_pass_rate"],
        average_coverage=metrics["average_coverage"],
        latest_test_coverage=metrics["latest_test_coverage"],
        failing_test_runs=metrics["failing_test_runs"],
        latest_monthly_cost=metrics["latest_monthly_cost"],
        potential_cost_savings=metrics["potential_cost_savings"],
        open_repair_proposals=metrics["open_repair_proposals"],
        charts=metrics["charts"],
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
        AuditService(db).record("uploaded", "Workflow created from canonical JSON.", workflow_id=record.id, version_id=record.current_version_id)
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
        AuditService(db).record(
            "uploaded",
            f"Uploaded {file.filename or 'workflow'}.",
            workflow_id=record.id,
            version_id=record.current_version_id,
            metadata={"content_type": file.content_type, "source_type": str(source_type)},
        )
        return _detail(record)
    except WorkflowParseError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/workflows", response_model=list[WorkflowSummary])
def list_workflows(
    q: str | None = Query(None),
    source_format: str | None = Query(None),
    source_type: str | None = Query(None),
    min_score: float | None = Query(None),
    has_critical: bool | None = Query(None),
    db: Session = Depends(get_db),
) -> list[WorkflowSummary]:
    records = WorkflowService(db).list_workflows()
    if q:
        q_lower = q.lower()
        records = [
            record
            for record in records
            if q_lower in record.name.lower()
            or q_lower in (record.source_prompt or "").lower()
            or q_lower in str(record.metadata_json).lower()
        ]
    summaries = [_summary(record) for record in records]
    if source_format:
        summaries = [item for item in summaries if item.source_format == source_format]
    if source_type:
        summaries = [item for item in summaries if item.source_type == source_type]
    if min_score is not None:
        summaries = [item for item in summaries if (item.structural_quality_score or 0) >= min_score]
    if has_critical is not None:
        summaries = [item for item in summaries if (item.critical_findings > 0) is has_critical]
    return summaries


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


@router.post(
    "/workflows/{workflow_id}/attachments",
    response_model=AttachmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_attachment(
    workflow_id: UUID,
    file: UploadFile = File(...),
    kind: str | None = Form(None),
    db: Session = Depends(get_db),
) -> AttachmentRead:
    content = await file.read()
    try:
        record = AttachmentService(db).add(
            workflow_id,
            filename=file.filename or "requirements.md",
            content=content,
            content_type=file.content_type,
            kind=kind,
        )
    except AttachmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc
    except UnsupportedAttachmentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _attachment(record)


@router.get("/workflows/{workflow_id}/attachments", response_model=list[AttachmentRead])
def list_attachments(workflow_id: UUID, db: Session = Depends(get_db)) -> list[AttachmentRead]:
    return [_attachment(record) for record in AttachmentService(db).list_for_workflow(workflow_id)]


@router.get("/attachments/{attachment_id}", response_model=AttachmentDetail)
def get_attachment(attachment_id: UUID, db: Session = Depends(get_db)) -> AttachmentDetail:
    try:
        record = AttachmentService(db).get(attachment_id)
    except AttachmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found") from exc
    extracted = record.extracted_json or {}
    return AttachmentDetail(
        **_attachment(record).model_dump(),
        raw_content=record.raw_content,
        sections=extracted.get("sections", []),
        clauses=extracted.get("clauses", []),
    )


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_attachment(attachment_id: UUID, db: Session = Depends(get_db)) -> Response:
    try:
        AttachmentService(db).delete(attachment_id)
    except AttachmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/workflows/{workflow_id}/validate", response_model=ValidationRunRead)
def validate(workflow_id: UUID, db: Session = Depends(get_db)) -> ValidationRunRead:
    try:
        run = WorkflowService(db).validate(workflow_id)
        AuditService(db).record("validated", "Static validation completed.", workflow_id=workflow_id, version_id=run.version_id)
        return _validation_run(run)
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
        AuditService(db).record("evaluated", "Semantic workflow evaluation completed.", workflow_id=workflow_id, version_id=run.version_id)
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


@router.post("/workflows/{workflow_id}/tests/generate", response_model=GenerateTestsResponse)
def generate_tests(
    workflow_id: UUID,
    payload: GenerateTestsRequest | None = None,
    db: Session = Depends(get_db),
) -> GenerateTestsResponse:
    try:
        result, all_tests = WorkflowTestingService(db).generate_tests(
            workflow_id,
            use_ai=payload.use_ai if payload else True,
            replace_existing=payload.replace_existing if payload else False,
        )
        # `generated` counts what this call created; `tests` is the whole suite, so the
        # panel and the status card cannot disagree about how many tests exist. These
        # were previously both the suite size, which reported every regeneration as
        # having generated the entire corpus again.
        created = len(result.tests)
        AuditService(db).record("tests_generated", f"Generated {created} workflow tests.", workflow_id=workflow_id)
        return GenerateTestsResponse(
            generated=created,
            tests=[_workflow_test(record) for record in all_tests],
            rationale=result.rationale,
            warnings=result.warnings,
        )
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc


@router.post("/workflows/{workflow_id}/tests", response_model=WorkflowTestRead, status_code=status.HTTP_201_CREATED)
def create_test(workflow_id: UUID, payload: WorkflowTestCreate, db: Session = Depends(get_db)) -> WorkflowTestRead:
    try:
        test = WorkflowTest.model_validate(payload.model_dump())
        record = WorkflowTestingService(db).create_test(workflow_id, test)
        AuditService(db).record("test_created", f"Created test {record.name}.", workflow_id=workflow_id, version_id=record.version_id)
        return _workflow_test(record)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/workflows/{workflow_id}/tests", response_model=list[WorkflowTestRead])
def list_tests(workflow_id: UUID, db: Session = Depends(get_db)) -> list[WorkflowTestRead]:
    try:
        return [_workflow_test(record) for record in WorkflowTestingService(db).list_tests(workflow_id)]
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc


@router.post("/workflows/{workflow_id}/tests/run", response_model=TestRunSummary)
def run_workflow_tests(
    workflow_id: UUID,
    payload: RunWorkflowTestsRequest | None = None,
    db: Session = Depends(get_db),
) -> TestRunSummary:
    try:
        runs = WorkflowTestingService(db).run_tests(workflow_id, payload.test_ids if payload else None)
        AuditService(db).record("tests_executed", f"Executed {len(runs)} workflow tests.", workflow_id=workflow_id)
        return _test_run_summary(WorkflowTestingService(db).list_tests(workflow_id), runs)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc


@router.post("/tests/{test_id}/run", response_model=WorkflowTestRunRead)
def run_single_test(test_id: UUID, db: Session = Depends(get_db)) -> WorkflowTestRunRead:
    try:
        return _workflow_test_run(WorkflowTestingService(db).run_test(test_id))
    except WorkflowTestNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found") from exc


@router.get("/workflows/{workflow_id}/test-runs", response_model=TestRunSummary)
def list_test_runs(workflow_id: UUID, db: Session = Depends(get_db)) -> TestRunSummary:
    try:
        service = WorkflowTestingService(db)
        return _test_run_summary(service.list_tests(workflow_id), service.list_runs(workflow_id))
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc


@router.get("/test-runs/{run_id}", response_model=WorkflowTestRunRead)
def get_test_run(run_id: UUID, db: Session = Depends(get_db)) -> WorkflowTestRunRead:
    try:
        return _workflow_test_run(WorkflowTestingService(db).get_run(run_id))
    except WorkflowTestRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test run not found") from exc


@router.post("/workflows/{workflow_id}/fuzz", response_model=FuzzRunRead)
def run_fuzz_campaign(
    workflow_id: UUID,
    payload: FuzzRunRequest | None = None,
    db: Session = Depends(get_db),
) -> FuzzRunRead:
    request = payload or FuzzRunRequest()
    try:
        run = FuzzService(db).run_campaign(
            workflow_id,
            use_ai=request.use_ai,
            seed=request.seed,
            max_cases=request.max_cases,
        )
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc
    return _fuzz_run(run)


@router.get("/workflows/{workflow_id}/fuzz", response_model=list[FuzzRunRead])
def list_fuzz_runs(workflow_id: UUID, db: Session = Depends(get_db)) -> list[FuzzRunRead]:
    try:
        return [_fuzz_run(run) for run in FuzzService(db).list_runs(workflow_id)]
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc


@router.get("/workflows/{workflow_id}/fuzz/latest", response_model=FuzzRunRead | None)
def latest_fuzz_run(workflow_id: UUID, db: Session = Depends(get_db)) -> FuzzRunRead | None:
    try:
        run = FuzzService(db).latest_run(workflow_id)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc
    return _fuzz_run(run) if run else None


@router.get("/workflows/{workflow_id}/fuzz/{run_id}", response_model=FuzzRunRead)
def get_fuzz_run(workflow_id: UUID, run_id: UUID, db: Session = Depends(get_db)) -> FuzzRunRead:
    try:
        return _fuzz_run(FuzzService(db).get_run(workflow_id, run_id))
    except (WorkflowNotFoundError, FuzzRunNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fuzz run not found") from exc


@router.get("/pricing", response_model=list[PricingEntryRead])
def pricing(db: Session = Depends(get_db)) -> list[PricingEntryRead]:
    return [_pricing(record) for record in CostService(db).pricing()]


@router.post("/pricing", response_model=PricingEntryRead, status_code=status.HTTP_201_CREATED)
def add_pricing(payload: PricingEntryCreate, db: Session = Depends(get_db)) -> PricingEntryRead:
    try:
        return _pricing(CostService(db).add_pricing(PricingEntry.model_validate(payload.model_dump())))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/workflows/{workflow_id}/cost", response_model=CostEstimateRead)
def estimate_cost(
    workflow_id: UUID,
    payload: CostScenarioCreate | None = None,
    db: Session = Depends(get_db),
) -> CostEstimateRead:
    try:
        scenario = CostScenario.model_validate(payload.model_dump()) if payload else CostScenario()
        estimate = CostService(db).estimate(workflow_id, scenario)
        AuditService(db).record("cost_estimated", "Workflow cost scenario estimated.", workflow_id=workflow_id, version_id=estimate.version_id)
        return _cost_estimate(estimate)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/workflows/{workflow_id}/cost", response_model=CostEstimateRead)
def latest_cost(workflow_id: UUID, db: Session = Depends(get_db)) -> CostEstimateRead:
    try:
        return _cost_estimate(CostService(db).latest_estimate(workflow_id))
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc


@router.get("/workflows/{workflow_id}/versions/compare", response_model=VersionCompareRead)
def compare_versions(
    workflow_id: UUID,
    from_version: UUID | None = Query(None),
    to_version: UUID | None = Query(None),
    db: Session = Depends(get_db),
) -> VersionCompareRead:
    try:
        record = WorkflowService(db).get_workflow(workflow_id)
        versions_by_id = {version.id: version for version in record.versions}
        sorted_versions = sorted(record.versions, key=lambda item: item.version_number)
        before_version = versions_by_id.get(from_version) if from_version else (sorted_versions[-2] if len(sorted_versions) > 1 else sorted_versions[0])
        after_version = versions_by_id.get(to_version) if to_version else sorted_versions[-1]
        if before_version is None or after_version is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
        before = Workflow.model_validate(before_version.canonical_json)
        after = Workflow.model_validate(after_version.canonical_json)
        before_validation = ValidationEngine().validate(before)
        after_validation = ValidationEngine().validate(after)
        estimator = CostEstimator(CostService(db)._pricing_catalog())
        before_cost = estimator.estimate(before).cost_per_run
        after_cost = estimator.estimate(after).cost_per_run
        comparison = VersionComparisonEngine().compare(
            before,
            after,
            validation_before=before_validation.structural_quality_score,
            validation_after=after_validation.structural_quality_score,
            cost_before=before_cost,
            cost_after=after_cost,
        )
        return VersionCompareRead(**comparison.model_dump(mode="json"))
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc


@router.post("/workflows/{workflow_id}/repairs/generate", response_model=RepairProposalRead)
def generate_repair(
    workflow_id: UUID,
    payload: RepairGenerateRequest | None = None,
    db: Session = Depends(get_db),
) -> RepairProposalRead:
    try:
        proposal = RepairService(db).generate(
            workflow_id,
            payload.finding if payload else None,
            use_ai=payload.use_ai if payload else True,
        )
        AuditService(db).record("repair_proposed", "Repair proposal generated.", workflow_id=workflow_id, version_id=proposal.version_id)
        return _repair(proposal)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/workflows/{workflow_id}/repairs", response_model=list[RepairProposalRead])
def list_repairs(workflow_id: UUID, db: Session = Depends(get_db)) -> list[RepairProposalRead]:
    try:
        return [_repair(record) for record in RepairService(db).list(workflow_id)]
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc


@router.post("/repairs/{proposal_id}/accept", response_model=RepairProposalRead)
def accept_repair(proposal_id: UUID, db: Session = Depends(get_db)) -> RepairProposalRead:
    try:
        proposal = RepairService(db).accept(proposal_id)
        AuditService(db).record(
            "repair_accepted",
            "Repair proposal accepted and a new workflow version was created.",
            workflow_id=proposal.workflow_id,
            version_id=proposal.accepted_version_id,
            metadata={"proposal_id": str(proposal.id)},
        )
        return _repair(proposal)
    except RepairProposalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repair proposal not found") from exc


@router.post("/repairs/{proposal_id}/reject", response_model=RepairProposalRead)
def reject_repair(
    proposal_id: UUID,
    payload: RepairDecisionRequest | None = None,
    db: Session = Depends(get_db),
) -> RepairProposalRead:
    try:
        proposal = RepairService(db).reject(proposal_id, payload.reason if payload else None)
        AuditService(db).record(
            "repair_rejected",
            "Repair proposal rejected.",
            workflow_id=proposal.workflow_id,
            version_id=proposal.version_id,
            metadata={"proposal_id": str(proposal.id), "reason": payload.reason if payload else None},
        )
        return _repair(proposal)
    except RepairProposalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repair proposal not found") from exc


@router.post("/workflows/{workflow_id}/quality-gate", response_model=QualityGateRunRead)
def check_quality_gate(
    workflow_id: UUID,
    payload: QualityGateConfigRead | None = None,
    db: Session = Depends(get_db),
) -> QualityGateRunRead:
    try:
        config = QualityGateConfig.model_validate(payload.model_dump()) if payload else None
        run = QualityGateService(db).check(workflow_id, config)
        AuditService(db).record("quality_gate_checked", f"Quality gate {run.status}.", workflow_id=workflow_id, version_id=run.version_id)
        return _quality_gate_run(run)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc


@router.get("/workflows/{workflow_id}/quality-gate", response_model=QualityGateRunRead)
def latest_quality_gate(workflow_id: UUID, db: Session = Depends(get_db)) -> QualityGateRunRead:
    try:
        return _quality_gate_run(QualityGateService(db).latest(workflow_id))
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc


@router.get("/workflows/{workflow_id}/history", response_model=list[AuditEventRead])
def workflow_history(workflow_id: UUID, db: Session = Depends(get_db)) -> list[AuditEventRead]:
    try:
        WorkflowService(db).get_workflow(workflow_id)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc
    return [_audit_event(event) for event in AuditService(db).list_for_workflow(workflow_id)]


@router.get("/workflows/{workflow_id}/report")
def workflow_report(
    workflow_id: UUID,
    format: str = Query("json", pattern="^(json|markdown|html)$"),
    db: Session = Depends(get_db),
):
    try:
        service = ReportService(db)
        if format == "markdown":
            return PlainTextResponse(service.markdown(workflow_id), media_type="text/markdown")
        if format == "html":
            return HTMLResponse(service.html(workflow_id))
        return service.build(workflow_id)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc


def _attachment(record) -> AttachmentRead:
    return AttachmentRead(
        id=record.id,
        workflow_id=record.workflow_id,
        version_id=record.version_id,
        kind=record.kind,
        filename=record.filename,
        content_type=record.content_type,
        size_bytes=record.size_bytes,
        clause_count=record.clause_count,
        created_at=record.created_at,
    )


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


def _workflow_test(record) -> WorkflowTestRead:
    latest = sorted(record.runs, key=lambda run: run.created_at)[-1] if record.runs else None
    return WorkflowTestRead(
        id=record.id,
        workflow_id=record.workflow_id,
        version_id=record.version_id,
        name=record.name,
        description=record.description,
        generated_by=record.generated_by,
        input_data=record.input_data,
        mocked_integrations=record.mocked_integrations,
        failure_injections=record.failure_injections,
        expected_path=record.expected_path,
        expected_outputs=record.expected_outputs,
        expected_side_effects=record.expected_side_effects,
        forbidden_side_effects=record.forbidden_side_effects,
        assertions=record.assertions,
        expected_error=record.expected_error,
        tags=record.tags,
        importance=record.importance,
        enabled=bool(record.enabled),
        rationale=record.rationale,
        linked_requirement_id=record.linked_requirement_id,
        metadata=record.metadata_json,
        latest_status=latest.status if latest else None,
        latest_run_id=latest.id if latest else None,
        latest_run_at=latest.created_at if latest else None,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _workflow_test_run(record) -> WorkflowTestRunRead:
    coverage = record.coverage or None
    return WorkflowTestRunRead(
        id=record.id,
        workflow_id=record.workflow_id,
        version_id=record.version_id,
        test_id=record.test_id,
        status=record.status,
        execution_trace=record.execution_trace,
        assertion_results=record.assertion_results,
        failures=record.failures,
        duration_ms=record.duration_ms,
        coverage=coverage,
        created_at=record.created_at,
    )


def _test_run_summary(tests, runs) -> TestRunSummary:
    latest = runs[0] if runs else None
    latest_by_test = {}
    for run in runs:
        latest_by_test.setdefault(run.test_id, run)
    latest_runs = list(latest_by_test.values())
    return TestRunSummary(
        total_tests=len(tests),
        passed=sum(1 for run in latest_runs if run.status == "PASSED"),
        failed=sum(1 for run in latest_runs if run.status == "FAILED"),
        error=sum(1 for run in latest_runs if run.status == "ERROR"),
        skipped=sum(1 for run in latest_runs if run.status == "SKIPPED"),
        latest_coverage=float((latest.coverage or {}).get("overall_coverage") or 0) if latest else 0,
        last_run_at=latest.created_at if latest else None,
        runs=[_workflow_test_run(run) for run in runs],
    )


def _pricing(record) -> PricingEntryRead:
    return PricingEntryRead(
        id=record.id,
        category=record.category,
        provider=record.provider,
        model=record.model,
        effective_date=record.effective_date,
        input_unit_cost=record.input_unit_cost,
        output_unit_cost=record.output_unit_cost,
        call_unit_cost=record.call_unit_cost,
        unit=record.unit,
        currency=record.currency,
        source=record.source,
        metadata=record.metadata_json,
        created_at=record.created_at,
    )


def _cost_estimate(record) -> CostEstimateRead:
    return CostEstimateRead(
        id=record.id,
        workflow_id=record.workflow_id,
        version_id=record.version_id,
        scenario=record.scenario_json,
        line_items=record.line_items,
        cost_per_run=record.cost_per_run,
        daily_cost=record.daily_cost,
        monthly_cost=record.monthly_cost,
        annual_cost=record.annual_cost,
        assumptions=record.assumptions,
        optimization_findings=[
            OptimizationFindingRead(
                id=finding.id,
                rule_id=finding.rule_id,
                title=finding.title,
                message=finding.message,
                category=finding.category,
                node_id=finding.node_id,
                estimated_monthly_savings=finding.estimated_monthly_savings,
                confidence=finding.confidence,
                deterministic=bool(finding.deterministic),
                recommendation=finding.recommendation,
                metadata=finding.metadata_json,
            )
            for finding in record.optimization_findings
        ],
        created_at=record.created_at,
    )


def _repair(record) -> RepairProposalRead:
    return RepairProposalRead(
        id=record.id,
        workflow_id=record.workflow_id,
        version_id=record.version_id,
        finding_id=record.finding_id,
        status=record.status,
        patch=record.patch_json,
        preview=record.preview_json,
        safety_flags=record.safety_flags,
        accepted_version_id=record.accepted_version_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _quality_gate_run(record: QualityGateRunRecord) -> QualityGateRunRead:
    return QualityGateRunRead(
        id=record.id,
        workflow_id=record.workflow_id,
        version_id=record.version_id,
        status=record.status,
        score=record.score,
        config=record.config_json,
        dimensions=record.dimensions_json,
        reasons=record.reasons_json,
        metadata=record.metadata_json,
        created_at=record.created_at,
    )


def _audit_event(record: AuditEventRecord) -> AuditEventRead:
    return AuditEventRead(
        id=record.id,
        workflow_id=record.workflow_id,
        version_id=record.version_id,
        event_type=record.event_type,
        actor=record.actor,
        message=record.message,
        metadata=record.metadata_json,
        created_at=record.created_at,
    )


def _fuzz_run(run) -> FuzzRunRead:
    return FuzzRunRead(
        id=run.id,
        workflow_id=run.workflow_id,
        version_id=run.version_id,
        seed=run.seed,
        total_cases=run.total_cases,
        exercised_cases=run.exercised_cases,
        handled=run.handled,
        unhandled_crash=run.unhandled_crash,
        silent_success=run.silent_success,
        hung=run.hung,
        not_triggered=run.not_triggered,
        robustness_score=run.robustness_score,
        generated_by=run.generated_by,
        ai_provider=run.ai_provider,
        ai_model=run.ai_model,
        ai_metadata=run.ai_metadata,
        findings=run.findings,
        limitations=run.limitations,
        suggestions=run.suggestions,
        created_at=run.created_at,
        cases=[
            FuzzCaseRead(
                id=case.id,
                case_id=case.case_id,
                name=case.name,
                description=case.description,
                strategy=case.strategy,
                verdict=case.verdict,
                observed=case.observed,
                generated_by=case.generated_by,
                seed=case.seed,
                input_data=case.input_data,
                failure_injections=case.failure_injections,
                targeted_node_ids=case.targeted_node_ids,
                evidence=case.evidence,
                execution_trace=case.execution_trace,
                created_at=case.created_at,
            )
            for case in run.cases
        ],
    )
