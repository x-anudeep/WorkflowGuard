from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session
from workflow_core.canonical.models import SourceType, Workflow
from workflow_core.comparison import VersionComparisonEngine
from workflow_core.costing import CostEstimator, CostScenario, PricingEntry
from workflow_core.parsers.errors import WorkflowParseError
from workflow_core.testing import WorkflowTest
from workflow_core.validation import ValidationEngine

from workflowguard_api.db.session import get_db
from workflowguard_api.models.db import ValidationRun, WorkflowRecord
from workflowguard_api.schemas.workflows import (
    DashboardMetrics,
    DimensionScoreRead,
    EvaluationFindingRead,
    EvaluationRequest,
    EvaluationRunRead,
    GenerateTestsRequest,
    GenerateTestsResponse,
    GraphRead,
    CostEstimateRead,
    CostScenarioCreate,
    OptimizationFindingRead,
    PricingEntryCreate,
    PricingEntryRead,
    RepairDecisionRequest,
    RepairGenerateRequest,
    RepairProposalRead,
    RequirementSpecRead,
    RunWorkflowTestsRequest,
    TestRunSummary,
    ValidationFindingRead,
    ValidationRunRead,
    WorkflowCreate,
    WorkflowDetail,
    WorkflowSummary,
    WorkflowTestCreate,
    WorkflowTestRead,
    WorkflowTestRunRead,
    WorkflowVersionRead,
    VersionCompareRead,
)
from workflowguard_api.services.costs import CostService
from workflowguard_api.services.evaluations import EvaluationNotFoundError, EvaluationService
from workflowguard_api.services.repairs import RepairProposalNotFoundError, RepairService
from workflowguard_api.services.testing import (
    WorkflowTestNotFoundError,
    WorkflowTestRunNotFoundError,
    WorkflowTestingService,
)
from workflowguard_api.services.workflows import WorkflowNotFoundError, WorkflowService

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/dashboard", response_model=DashboardMetrics)
def dashboard(db: Session = Depends(get_db)) -> DashboardMetrics:
    service = WorkflowService(db)
    evaluation_service = EvaluationService(db)
    testing_service = WorkflowTestingService(db)
    cost_service = CostService(db)
    repair_service = RepairService(db)
    metrics = service.dashboard_metrics()
    evaluation_metrics = evaluation_service.dashboard_metrics()
    testing_metrics = testing_service.dashboard_metrics()
    cost_metrics = cost_service.dashboard_metrics()
    repair_metrics = repair_service.dashboard_metrics()
    return DashboardMetrics(
        total_workflows=metrics["total_workflows"],
        total_validation_runs=metrics["total_validation_runs"],
        average_structural_score=metrics["average_structural_score"],
        critical_issues=metrics["critical_issues"],
        total_evaluation_runs=evaluation_metrics["total_evaluation_runs"],
        average_overall_score=evaluation_metrics["average_overall_score"],
        total_workflow_tests=testing_metrics["total_workflow_tests"],
        latest_test_coverage=testing_metrics["latest_test_coverage"],
        failing_test_runs=testing_metrics["failing_test_runs"],
        latest_monthly_cost=cost_metrics["latest_monthly_cost"],
        open_repair_proposals=repair_metrics["open_repair_proposals"],
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


@router.post("/workflows/{workflow_id}/tests/generate", response_model=GenerateTestsResponse)
def generate_tests(
    workflow_id: UUID,
    payload: GenerateTestsRequest | None = None,
    db: Session = Depends(get_db),
) -> GenerateTestsResponse:
    try:
        result, records = WorkflowTestingService(db).generate_tests(
            workflow_id,
            use_ai=payload.use_ai if payload else True,
            replace_existing=payload.replace_existing if payload else False,
        )
        return GenerateTestsResponse(
            generated=len(records),
            tests=[_workflow_test(record) for record in records],
            rationale=result.rationale,
            warnings=result.warnings,
        )
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found") from exc


@router.post("/workflows/{workflow_id}/tests", response_model=WorkflowTestRead, status_code=status.HTTP_201_CREATED)
def create_test(workflow_id: UUID, payload: WorkflowTestCreate, db: Session = Depends(get_db)) -> WorkflowTestRead:
    try:
        test = WorkflowTest.model_validate(payload.model_dump())
        return _workflow_test(WorkflowTestingService(db).create_test(workflow_id, test))
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
        return _cost_estimate(CostService(db).estimate(workflow_id, scenario))
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
        return _repair(
            RepairService(db).generate(
                workflow_id,
                payload.finding if payload else None,
                use_ai=payload.use_ai if payload else True,
            )
        )
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
        return _repair(RepairService(db).accept(proposal_id))
    except RepairProposalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repair proposal not found") from exc


@router.post("/repairs/{proposal_id}/reject", response_model=RepairProposalRead)
def reject_repair(
    proposal_id: UUID,
    payload: RepairDecisionRequest | None = None,
    db: Session = Depends(get_db),
) -> RepairProposalRead:
    try:
        return _repair(RepairService(db).reject(proposal_id, payload.reason if payload else None))
    except RepairProposalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repair proposal not found") from exc


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
