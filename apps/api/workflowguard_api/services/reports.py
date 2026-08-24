from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload
from workflow_core.reporting import render_markdown_report

from workflowguard_api.models.db import EvaluationRun, ValidationRun
from workflowguard_api.services.costs import CostService
from workflowguard_api.services.quality import QualityGateService
from workflowguard_api.services.testing import WorkflowTestingService
from workflowguard_api.services.workflows import WorkflowService


class ReportService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.workflow_service = WorkflowService(db)

    def build(self, workflow_id: uuid.UUID) -> dict[str, Any]:
        record = self.workflow_service.get_workflow(workflow_id)
        version = self.workflow_service.get_current_version(record)
        validation = self._latest_validation(workflow_id)
        evaluation = self._latest_evaluation(workflow_id)
        tests = WorkflowTestingService(self.db).list_runs(workflow_id)
        test_summary = _test_summary(tests)
        cost = CostService(self.db).latest_estimate(workflow_id)
        gate = QualityGateService(self.db).latest(workflow_id)
        dimensions = {score.dimension: score.score for score in evaluation.dimension_scores} if evaluation else {}
        return {
            "workflow": {
                "id": str(record.id),
                "name": record.name,
                "version_id": str(version.id),
                "source_format": record.source_format,
                "source_type": record.source_type,
                "source_prompt": record.source_prompt,
                "created_at": record.created_at.isoformat(),
            },
            "scores": {
                "overall": evaluation.overall_score if evaluation else None,
                "structural": validation.structural_quality_score if validation else None,
                "prompt_alignment": dimensions.get("prompt_alignment"),
                "security": dimensions.get("security"),
                "reliability": dimensions.get("reliability"),
                "maintainability": dimensions.get("maintainability"),
                "test_coverage": test_summary["latest_coverage"],
            },
            "quality_gate": {
                "id": str(gate.id),
                "status": gate.status,
                "score": gate.score,
                "dimensions": gate.dimensions_json,
                "reasons": gate.reasons_json,
                "created_at": gate.created_at.isoformat(),
            },
            "validation_findings": [_validation_finding(finding) for finding in (validation.findings if validation else [])],
            "evaluation_findings": [_evaluation_finding(finding) for finding in (evaluation.findings if evaluation else [])],
            "requirement_matches": evaluation.requirement_matches if evaluation else [],
            "tests": test_summary,
            "cost": {
                "cost_per_run": cost.cost_per_run,
                "monthly_cost": cost.monthly_cost,
                "annual_cost": cost.annual_cost,
                "assumptions": cost.assumptions,
            },
            "optimization_findings": [
                {
                    "rule_id": finding.rule_id,
                    "title": finding.title,
                    "recommendation": finding.recommendation,
                    "estimated_monthly_savings": finding.estimated_monthly_savings,
                }
                for finding in cost.optimization_findings
            ],
        }

    def markdown(self, workflow_id: uuid.UUID) -> str:
        return render_markdown_report(self.build(workflow_id))

    def html(self, workflow_id: uuid.UUID) -> str:
        markdown = self.markdown(workflow_id)
        body = "\n".join(f"<p>{line}</p>" if line and not line.startswith("#") else f"<h1>{line[2:]}</h1>" for line in markdown.splitlines())
        return f"<!doctype html><html><head><meta charset='utf-8'><title>WorkflowGuard Report</title></head><body>{body}</body></html>"

    def _latest_validation(self, workflow_id: uuid.UUID) -> ValidationRun | None:
        return (
            self.db.execute(
                select(ValidationRun)
                .where(ValidationRun.workflow_id == workflow_id)
                .options(selectinload(ValidationRun.findings))
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
                .options(
                    selectinload(EvaluationRun.findings),
                    selectinload(EvaluationRun.dimension_scores),
                    selectinload(EvaluationRun.requirement_spec),
                )
                .order_by(desc(EvaluationRun.created_at))
                .limit(1)
            )
            .scalars()
            .first()
        )


def _test_summary(runs) -> dict[str, Any]:
    latest = runs[0] if runs else None
    latest_by_test = {}
    for run in runs:
        latest_by_test.setdefault(run.test_id, run)
    latest_runs = list(latest_by_test.values())
    return {
        "total_tests": len(latest_by_test),
        "passed": sum(1 for run in latest_runs if run.status == "PASSED"),
        "failed": sum(1 for run in latest_runs if run.status == "FAILED"),
        "error": sum(1 for run in latest_runs if run.status == "ERROR"),
        "skipped": sum(1 for run in latest_runs if run.status == "SKIPPED"),
        "latest_coverage": float((latest.coverage or {}).get("overall_coverage") or 0) if latest else 0,
    }


def _validation_finding(finding) -> dict[str, Any]:
    return {
        "rule_id": finding.rule_id,
        "severity": finding.severity,
        "title": finding.title,
        "message": finding.message,
        "node_id": finding.node_id,
        "edge_id": finding.edge_id,
        "remediation": finding.remediation,
    }


def _evaluation_finding(finding) -> dict[str, Any]:
    return {
        "rule_id": finding.rule_id,
        "dimension": finding.dimension,
        "severity": finding.severity,
        "title": finding.title,
        "message": finding.message,
        "expected": finding.expected,
        "found": finding.found,
        "node_id": finding.node_id,
        "remediation": finding.remediation,
        "confidence": finding.confidence,
    }
