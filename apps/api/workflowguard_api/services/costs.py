from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload
from workflow_core.canonical.models import Workflow
from workflow_core.costing import (
    DEFAULT_PRICING_CATALOG,
    CostEstimator,
    CostOptimizationEngine,
    CostScenario,
    PricingCatalog,
    PricingEntry,
)

from workflowguard_api.models.db import (
    CostEstimateRecord,
    CostScenarioRecord,
    OptimizationFindingRecord,
    PricingCatalogRecord,
)
from workflowguard_api.services.workflows import WorkflowService


class CostEstimateNotFoundError(LookupError):
    pass


class CostService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.workflow_service = WorkflowService(db)

    def pricing(self) -> list[PricingCatalogRecord]:
        self._seed_pricing()
        return list(self.db.execute(select(PricingCatalogRecord).order_by(desc(PricingCatalogRecord.effective_date))).scalars().all())

    def add_pricing(self, entry: PricingEntry) -> PricingCatalogRecord:
        record = PricingCatalogRecord(
            category=str(entry.category),
            provider=entry.provider,
            model=entry.model,
            effective_date=datetime.combine(entry.effective_date, datetime.min.time(), tzinfo=timezone.utc),
            input_unit_cost=entry.input_unit_cost,
            output_unit_cost=entry.output_unit_cost,
            call_unit_cost=entry.call_unit_cost,
            unit=str(entry.unit),
            currency=entry.currency,
            source=entry.source,
            metadata_json=entry.metadata,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def estimate(self, workflow_id: uuid.UUID, scenario: CostScenario | None = None) -> CostEstimateRecord:
        record = self.workflow_service.get_workflow(workflow_id)
        version = self.workflow_service.get_current_version(record)
        workflow = Workflow.model_validate(version.canonical_json).model_copy(update={"id": str(record.id)})
        scenario = scenario or CostScenario()
        scenario_record = CostScenarioRecord(workflow_id=record.id, name=scenario.name, inputs_json=scenario.model_dump(mode="json"))
        self.db.add(scenario_record)
        self.db.flush()
        estimate = CostEstimator(self._pricing_catalog()).estimate(workflow, scenario)
        estimate.workflow_version_id = str(version.id)
        findings = CostOptimizationEngine().analyze(workflow, estimate)
        estimate_record = CostEstimateRecord(
            workflow_id=record.id,
            version_id=version.id,
            scenario_id=scenario_record.id,
            cost_per_run=estimate.cost_per_run,
            daily_cost=estimate.daily_cost,
            monthly_cost=estimate.monthly_cost,
            annual_cost=estimate.annual_cost,
            scenario_json=estimate.scenario.model_dump(mode="json"),
            line_items=[item.model_dump(mode="json") for item in estimate.line_items],
            assumptions=estimate.assumptions,
        )
        self.db.add(estimate_record)
        self.db.flush()
        for finding in findings:
            self.db.add(
                OptimizationFindingRecord(
                    workflow_id=record.id,
                    cost_estimate_id=estimate_record.id,
                    rule_id=finding.rule_id,
                    title=finding.title,
                    message=finding.message,
                    category=str(finding.category),
                    node_id=finding.node_id,
                    estimated_monthly_savings=finding.estimated_monthly_savings,
                    confidence=finding.confidence,
                    deterministic=1 if finding.deterministic else 0,
                    recommendation=finding.recommendation,
                    metadata_json=finding.metadata,
                )
            )
        self.db.commit()
        return self.latest_estimate(record.id)

    def latest_estimate(self, workflow_id: uuid.UUID) -> CostEstimateRecord:
        estimate = (
            self.db.execute(
                select(CostEstimateRecord)
                .where(CostEstimateRecord.workflow_id == workflow_id)
                .options(selectinload(CostEstimateRecord.optimization_findings))
                .order_by(desc(CostEstimateRecord.created_at))
                .limit(1)
            )
            .scalars()
            .first()
        )
        if estimate is None:
            return self.estimate(workflow_id)
        return estimate

    def dashboard_metrics(self) -> dict[str, float | int]:
        latest = self.db.execute(select(CostEstimateRecord).order_by(desc(CostEstimateRecord.created_at)).limit(1)).scalars().first()
        return {"latest_monthly_cost": round(float(latest.monthly_cost), 4) if latest else 0}

    def _pricing_catalog(self) -> PricingCatalog:
        entries = [
            PricingEntry(
                id=str(record.id),
                category=record.category,
                provider=record.provider,
                model=record.model,
                effective_date=record.effective_date.date(),
                input_unit_cost=record.input_unit_cost,
                output_unit_cost=record.output_unit_cost,
                call_unit_cost=record.call_unit_cost,
                unit=record.unit,
                currency=record.currency,
                source=record.source,
                metadata=record.metadata_json,
            )
            for record in self.pricing()
        ]
        return PricingCatalog(entries)

    def _seed_pricing(self) -> None:
        existing = self.db.scalar(select(func.count(PricingCatalogRecord.id))) or 0
        if existing:
            return
        for entry in DEFAULT_PRICING_CATALOG:
            self.db.add(
                PricingCatalogRecord(
                    category=str(entry.category),
                    provider=entry.provider,
                    model=entry.model,
                    effective_date=datetime.combine(entry.effective_date, datetime.min.time(), tzinfo=timezone.utc),
                    input_unit_cost=entry.input_unit_cost,
                    output_unit_cost=entry.output_unit_cost,
                    call_unit_cost=entry.call_unit_cost,
                    unit=str(entry.unit),
                    currency=entry.currency,
                    source=entry.source,
                    metadata_json=entry.metadata,
                )
            )
        self.db.commit()
