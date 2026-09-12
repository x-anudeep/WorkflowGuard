from __future__ import annotations

import uuid

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload
from workflow_core.quality import QualityGateConfig, QualityGateEngine

from workflowguard_api.models.db import (
    EvaluationRun,
    QualityGateRunRecord,
    ValidationRun,
    WorkflowTestRecord,
    WorkflowTestRunRecord,
)
from workflowguard_api.services.workflows import WorkflowService


class QualityGateService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.workflow_service = WorkflowService(db)

    def check(self, workflow_id: uuid.UUID, config: QualityGateConfig | None = None) -> QualityGateRunRecord:
        record = self.workflow_service.get_workflow(workflow_id)
        version = self.workflow_service.get_current_version(record)
        validation = self._latest_validation(workflow_id)
        evaluation = self._latest_evaluation(workflow_id)
        dimensions = _dimensions(evaluation)
        latest_coverage = self._latest_coverage(workflow_id)
        critical_failures, critical_total = self._critical_test_failures(workflow_id)
        result = QualityGateEngine(config).evaluate(
            structural_score=validation.structural_quality_score if validation else None,
            prompt_alignment_score=dimensions.get("prompt_alignment"),
            security_score=dimensions.get("security"),
            reliability_score=dimensions.get("reliability"),
            maintainability_score=dimensions.get("maintainability"),
            test_coverage=latest_coverage,
            critical_test_failures=critical_failures,
            critical_test_total=critical_total,
            critical_security_findings=self._critical_security_findings(evaluation),
        )
        run = QualityGateRunRecord(
            workflow_id=record.id,
            version_id=version.id,
            status=result.status,
            score=result.score,
            config_json=result.config.model_dump(mode="json"),
            dimensions_json=result.dimensions,
            reasons_json=[reason.model_dump(mode="json") for reason in result.reasons],
            metadata_json=result.metadata,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def latest(self, workflow_id: uuid.UUID) -> QualityGateRunRecord:
        self.workflow_service.get_workflow(workflow_id)
        run = (
            self.db.execute(
                select(QualityGateRunRecord)
                .where(QualityGateRunRecord.workflow_id == workflow_id)
                .order_by(desc(QualityGateRunRecord.created_at))
                .limit(1)
            )
            .scalars()
            .first()
        )
        return run or self.check(workflow_id)

    def _latest_validation(self, workflow_id: uuid.UUID) -> ValidationRun | None:
        return (
            self.db.execute(
                select(ValidationRun)
                .where(ValidationRun.workflow_id == workflow_id)
                .order_by(desc(ValidationRun.created_at))
                .limit(1)
            )
            .scalars()
            .first()
        )

    def _latest_evaluation(self, workflow_id: uuid.UUID) -> EvaluationRun | None:
        return (
            self.db.execute(
                select(EvaluationRun)
                .where(EvaluationRun.workflow_id == workflow_id)
                .options(selectinload(EvaluationRun.dimension_scores), selectinload(EvaluationRun.findings))
                .order_by(desc(EvaluationRun.created_at))
                .limit(1)
            )
            .scalars()
            .first()
        )

    def _latest_coverage(self, workflow_id: uuid.UUID) -> float | None:
        run = (
            self.db.execute(
                select(WorkflowTestRunRecord)
                .where(WorkflowTestRunRecord.workflow_id == workflow_id)
                .order_by(desc(WorkflowTestRunRecord.created_at))
                .limit(1)
            )
            .scalars()
            .first()
        )
        if run is None:
            return None
        # An empty coverage blob means the run never executed - the engine was unreachable.
        # Reading that as 0% would fail the gate for an infrastructure problem and call it a
        # workflow defect; `None` means "not measured", which the gate already understands.
        measured = (run.coverage or {}).get("overall_coverage")
        return float(measured) if measured is not None else None

    def _critical_test_failures(self, workflow_id: uuid.UUID) -> tuple[int, int]:
        """Failing high-importance tests, and how many there are in total.

        "High importance" is the happy path, security defences, and one test per stated
        requirement. It deliberately excludes branch-coverage and failure-injection tests:
        missing error handling is already scored by the reliability dimension and the fuzz
        campaign, so gating on it here would count the same defect twice.
        """
        tests = list(
            self.db.execute(select(WorkflowTestRecord).where(WorkflowTestRecord.workflow_id == workflow_id))
            .scalars()
            .all()
        )
        latest_runs = (
            self.db.execute(
                select(WorkflowTestRunRecord)
                .where(WorkflowTestRunRecord.workflow_id == workflow_id)
                .order_by(desc(WorkflowTestRunRecord.created_at))
            )
            .scalars()
            .all()
        )
        latest_by_test = {}
        for run in latest_runs:
            latest_by_test.setdefault(run.test_id, run)
        critical_ids = {test.id for test in tests if test.importance.upper() in {"HIGH", "CRITICAL"}}
        failures = sum(
            1
            for test_id in critical_ids
            if latest_by_test.get(test_id) and latest_by_test[test_id].status in {"FAILED", "ERROR"}
        )
        return failures, len(critical_ids)

    @staticmethod
    def _critical_security_findings(evaluation: EvaluationRun | None) -> int:
        if not evaluation:
            return 0
        return sum(1 for finding in evaluation.findings if finding.dimension == "security" and finding.severity == "CRITICAL")


def _dimensions(evaluation: EvaluationRun | None) -> dict[str, float]:
    if not evaluation:
        return {}
    return {score.dimension: score.score for score in evaluation.dimension_scores}
