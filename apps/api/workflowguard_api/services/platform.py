from __future__ import annotations

from collections import Counter, defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from workflowguard_api.models.db import (
    CostEstimateRecord,
    EvaluationFindingRecord,
    EvaluationRun,
    OptimizationFindingRecord,
    QualityGateRunRecord,
    RepairProposalRecord,
    ValidationFindingRecord,
    ValidationRun,
    WorkflowTestRecord,
    WorkflowTestRunRecord,
    WorkflowVersion,
)
from workflowguard_api.services.workflows import WorkflowService


class PlatformMetricsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def dashboard(self) -> dict:
        workflows = WorkflowService(self.db).list_workflows()
        versions = self.db.scalar(select(func.count(WorkflowVersion.id))) or 0
        validations = self.db.scalar(select(func.count(ValidationRun.id))) or 0
        evaluations = list(self.db.execute(select(EvaluationRun).order_by(EvaluationRun.created_at)).scalars().all())
        test_runs = list(self.db.execute(select(WorkflowTestRunRecord).order_by(WorkflowTestRunRecord.created_at)).scalars().all())
        costs = list(self.db.execute(select(CostEstimateRecord).order_by(CostEstimateRecord.created_at)).scalars().all())
        savings = self.db.scalar(select(func.sum(OptimizationFindingRecord.estimated_monthly_savings))) or 0
        latest_cost_total = sum(_latest_costs_by_workflow(costs).values())
        pass_rate = _pass_rate(test_runs)
        avg_coverage = _average_coverage(test_runs)
        findings_by_severity = Counter()
        for severity, count in self.db.execute(select(ValidationFindingRecord.severity, func.count()).group_by(ValidationFindingRecord.severity)):
            findings_by_severity[severity] += count
        for severity, count in self.db.execute(select(EvaluationFindingRecord.severity, func.count()).group_by(EvaluationFindingRecord.severity)):
            findings_by_severity[severity] += count
        return {
            "total_workflows": len(workflows),
            "total_workflow_versions": int(versions),
            "total_validation_runs": int(validations),
            "average_structural_score": _avg([run.structural_quality_score for record in workflows for run in record.validation_runs]),
            "critical_issues": int(findings_by_severity["CRITICAL"]),
            "total_evaluation_runs": len(evaluations),
            "average_overall_score": _avg([run.overall_score for run in evaluations]),
            "average_quality_score": _avg([run.score for run in self.db.execute(select(QualityGateRunRecord)).scalars().all()]),
            "total_workflow_tests": int(self.db.scalar(select(func.count(WorkflowTestRecord.id))) or 0),
            "test_pass_rate": pass_rate,
            "average_coverage": avg_coverage,
            "latest_test_coverage": avg_coverage,
            "failing_test_runs": sum(1 for run in test_runs if run.status in {"FAILED", "ERROR"}),
            "latest_monthly_cost": round(float(latest_cost_total), 4),
            "potential_cost_savings": round(float(savings), 4),
            "open_repair_proposals": int(
                self.db.scalar(select(func.count(RepairProposalRecord.id)).where(RepairProposalRecord.status == "proposed")) or 0
            ),
            "recent_workflows": workflows[:5],
            "charts": {
                "quality_over_time": [{"date": run.created_at.isoformat(), "score": run.overall_score} for run in evaluations[-12:]],
                "cost_trend": [{"date": cost.created_at.isoformat(), "monthly_cost": cost.monthly_cost} for cost in costs[-12:]],
                "test_pass_rate": _pass_rate_points(test_runs),
                "findings_by_severity": dict(findings_by_severity),
                "workflows_by_source": dict(Counter(record.source_type for record in workflows)),
                "workflows_by_format": dict(Counter(record.source_format for record in workflows)),
                "most_expensive_workflows": _most_expensive_workflows(costs, workflows),
            },
        }


def _avg(values: list[float]) -> float:
    return round(float(sum(values) / len(values)), 2) if values else 0.0


def _average_coverage(runs) -> float:
    latest = {}
    for run in runs:
        latest[run.test_id] = run
    values = [float((run.coverage or {}).get("overall_coverage") or 0) for run in latest.values()]
    return _avg(values)


def _pass_rate(runs) -> float:
    latest = {}
    for run in runs:
        latest[run.test_id] = run
    if not latest:
        return 0.0
    passed = sum(1 for run in latest.values() if run.status == "PASSED")
    return round((passed / len(latest)) * 100, 2)


def _pass_rate_points(runs) -> list[dict]:
    grouped = defaultdict(list)
    for run in runs:
        grouped[run.created_at.date().isoformat()].append(run)
    return [{"date": date, "pass_rate": _pass_rate(items)} for date, items in sorted(grouped.items())[-12:]]


def _latest_costs_by_workflow(costs) -> dict:
    latest = {}
    for cost in costs:
        latest[cost.workflow_id] = cost.monthly_cost
    return latest


def _most_expensive_workflows(costs, workflows) -> list[dict]:
    names = {record.id: record.name for record in workflows}
    latest = _latest_costs_by_workflow(costs)
    return [
        {"workflow_id": str(workflow_id), "name": names.get(workflow_id, "Workflow"), "monthly_cost": monthly_cost}
        for workflow_id, monthly_cost in sorted(latest.items(), key=lambda item: item[1], reverse=True)[:5]
    ]
