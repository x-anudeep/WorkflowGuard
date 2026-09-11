from __future__ import annotations

import uuid

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload
from workflow_core.canonical.models import Workflow
from workflow_core.evaluation import DeterministicRequirementExtractor
from workflow_core.evaluation.models import RequirementSpec
from workflow_core.fuzzing import DeterministicFuzzGenerator, FuzzEngine, FuzzReport
from workflow_core.fuzzing.models import ErrorHandlingVerdict, FuzzCase
from workflow_core.testing.models import TestGeneratedBy

from workflowguard_api.ai.errors import AIProviderError, AIProviderUnavailable
from workflowguard_api.ai.fuzzing import FuzzGenerationProvider, fuzz_provider_from_settings
from workflowguard_api.core.config import get_settings
from workflowguard_api.db.jsonb import scrub_null_bytes
from workflowguard_api.models.db import (
    FuzzCaseRecord,
    FuzzRunRecord,
    RequirementSpecificationRecord,
)
from workflowguard_api.services.audit import AuditService
from workflowguard_api.services.execution import build_engine
from workflowguard_api.services.workflows import WorkflowService

#: Full simulation traces for a large campaign would dominate the row size; keep the
#: trace only for cases a human will actually open.
_TRACE_VERDICTS = frozenset(
    {
        ErrorHandlingVerdict.UNHANDLED_CRASH,
        ErrorHandlingVerdict.SILENT_SUCCESS,
        ErrorHandlingVerdict.HUNG,
    }
)


class FuzzRunNotFoundError(LookupError):
    pass


class FuzzService:
    def __init__(self, db: Session, ai_provider: FuzzGenerationProvider | None = None) -> None:
        self.db = db
        self.workflow_service = WorkflowService(db)
        self.engine = FuzzEngine(build_engine(propagate_failures=True))
        self.generator = DeterministicFuzzGenerator()
        self.extractor = DeterministicRequirementExtractor()
        self.audit = AuditService(db)
        self.ai_provider = ai_provider

    def run_campaign(
        self,
        workflow_id: uuid.UUID,
        *,
        use_ai: bool = True,
        seed: int | None = None,
        max_cases: int | None = None,
    ) -> FuzzRunRecord:
        settings = get_settings()
        seed = settings.fuzz_default_seed if seed is None else seed
        max_cases = settings.fuzz_max_cases if max_cases is None else max_cases

        record = self.workflow_service.get_workflow(workflow_id)
        version = self.workflow_service.get_current_version(record)
        workflow = Workflow.model_validate(version.canonical_json).model_copy(
            update={"id": str(record.id)}
        )
        requirement_spec = self._latest_requirement_spec(workflow_id) or (
            self.extractor.extract(workflow.source_prompt) if workflow.source_prompt else None
        )

        cases, generated_by, provider_name, model_name, ai_metadata = self._build_cases(
            workflow, requirement_spec, use_ai=use_ai, seed=seed, max_cases=max_cases
        )
        report = self.engine.run(
            workflow,
            cases,
            requirement_spec=requirement_spec,
            seed=seed,
            max_cases=max_cases,
            generated_by=generated_by,
            ai_provider=provider_name,
            ai_model=model_name,
            ai_metadata=ai_metadata,
        )
        return self._persist(record.id, version.id, report)

    def latest_run(self, workflow_id: uuid.UUID, version_id: uuid.UUID | None = None) -> FuzzRunRecord | None:
        query = select(FuzzRunRecord).where(FuzzRunRecord.workflow_id == workflow_id)
        if version_id is not None:
            query = query.where(FuzzRunRecord.version_id == version_id)
        return (
            self.db.execute(
                query.options(selectinload(FuzzRunRecord.cases))
                .order_by(desc(FuzzRunRecord.created_at))
                .limit(1)
            )
            .scalars()
            .first()
        )

    def list_runs(self, workflow_id: uuid.UUID) -> list[FuzzRunRecord]:
        self.workflow_service.get_workflow(workflow_id)
        return list(
            self.db.execute(
                select(FuzzRunRecord)
                .where(FuzzRunRecord.workflow_id == workflow_id)
                .options(selectinload(FuzzRunRecord.cases))
                .order_by(desc(FuzzRunRecord.created_at))
            )
            .scalars()
            .all()
        )

    def get_run(self, workflow_id: uuid.UUID, run_id: uuid.UUID) -> FuzzRunRecord:
        run = (
            self.db.execute(
                select(FuzzRunRecord)
                .where(FuzzRunRecord.workflow_id == workflow_id, FuzzRunRecord.id == run_id)
                .options(selectinload(FuzzRunRecord.cases))
            )
            .scalars()
            .first()
        )
        if run is None:
            raise FuzzRunNotFoundError(str(run_id))
        return run

    def report_for_evaluation(self, workflow_id: uuid.UUID, version_id: uuid.UUID) -> FuzzReport | None:
        """Rehydrate the latest campaign for this version, for the reliability blend.

        Only the aggregate is needed - the findings and counts - so stored cases are not
        rebuilt into full results.
        """
        run = self.latest_run(workflow_id, version_id)
        if run is None:
            return None
        return FuzzReport.model_validate(
            {
                "workflow_id": str(workflow_id),
                "seed": run.seed,
                "results": [],
                "counts": _counts_from_record(run),
                "exercised_cases": run.exercised_cases,
                "robustness_score": run.robustness_score,
                "findings": run.findings,
                "generated_by": run.generated_by,
                "ai_provider": run.ai_provider,
                "ai_model": run.ai_model,
                "ai_metadata": run.ai_metadata,
                "limitations": run.limitations,
                "suggestions": run.suggestions,
            }
        )

    def _build_cases(
        self,
        workflow: Workflow,
        requirement_spec: RequirementSpec | None,
        *,
        use_ai: bool,
        seed: int,
        max_cases: int,
    ) -> tuple[list[FuzzCase], TestGeneratedBy, str | None, str | None, dict[str, str]]:
        """Deterministic corpus always runs; AI cases are added on top when available.

        The deterministic generator is not a fallback of last resort here - it provides
        the systematic coverage (every failure type against every dependency) that a
        model will not reliably enumerate. AI cases add workflow-specific attacks.
        """
        deterministic = self.generator.generate(workflow, requirement_spec, seed=seed, max_cases=max_cases)
        if not use_ai:
            return deterministic, TestGeneratedBy.SYSTEM, None, None, {"ai_status": "disabled_by_request"}

        try:
            provider = self.ai_provider or fuzz_provider_from_settings(get_settings())
            ai_cases = provider.generate_cases(workflow, requirement_spec, max_cases=max_cases)
        except AIProviderUnavailable as exc:
            return deterministic, TestGeneratedBy.SYSTEM, None, None, {
                "ai_status": "unavailable_fallback",
                "reason": str(exc),
            }
        except AIProviderError as exc:
            return deterministic, TestGeneratedBy.SYSTEM, None, None, {
                "ai_status": "error_fallback",
                "reason": str(exc),
            }

        combined = [*deterministic, *ai_cases][: max_cases * 2]
        return (
            combined,
            TestGeneratedBy.AI if ai_cases else TestGeneratedBy.SYSTEM,
            provider.provider_name,
            provider.model_name,
            {"ai_status": "used", "ai_cases": str(len(ai_cases))},
        )

    def _persist(self, workflow_id: uuid.UUID, version_id: uuid.UUID, report: FuzzReport) -> FuzzRunRecord:
        counts = report.counts
        run = FuzzRunRecord(
            workflow_id=workflow_id,
            version_id=version_id,
            seed=report.seed,
            total_cases=len(report.results),
            exercised_cases=report.exercised_cases,
            handled=counts.get(ErrorHandlingVerdict.HANDLED.value, 0),
            unhandled_crash=counts.get(ErrorHandlingVerdict.UNHANDLED_CRASH.value, 0),
            silent_success=counts.get(ErrorHandlingVerdict.SILENT_SUCCESS.value, 0),
            hung=counts.get(ErrorHandlingVerdict.HUNG.value, 0),
            not_triggered=counts.get(ErrorHandlingVerdict.NOT_TRIGGERED.value, 0),
            robustness_score=report.robustness_score,
            generated_by=str(report.generated_by),
            ai_provider=report.ai_provider,
            ai_model=report.ai_model,
            ai_metadata=scrub_null_bytes(dict(report.ai_metadata)),
            # Findings quote the input that produced them, so a null-byte mutation
            # reaches these columns too.
            findings=scrub_null_bytes([finding.model_dump(mode="json") for finding in report.findings]),
            limitations=scrub_null_bytes(list(report.limitations)),
            suggestions=scrub_null_bytes(list(report.suggestions)),
        )
        self.db.add(run)
        self.db.flush()

        for result in report.results:
            verdict = ErrorHandlingVerdict(result.verdict)
            self.db.add(
                FuzzCaseRecord(
                    fuzz_run_id=run.id,
                    workflow_id=workflow_id,
                    case_id=result.case.id,
                    name=scrub_null_bytes(result.case.name),
                    description=scrub_null_bytes(result.case.description),
                    strategy=str(result.case.strategy),
                    verdict=verdict.value,
                    observed=scrub_null_bytes(result.observed),
                    generated_by=str(result.case.generated_by),
                    seed=result.case.seed,
                    # A null byte is one of the input mutations the fuzzer feeds in, and
                    # it reaches every one of these columns -- the input itself, the
                    # trace of the run it produced, and the evidence quoting it. Postgres
                    # JSONB cannot store U+0000, so it is replaced on the way in.
                    input_data=scrub_null_bytes(dict(result.case.input_data)),
                    failure_injections=scrub_null_bytes(
                        [injection.model_dump(mode="json") for injection in result.case.failure_injections]
                    ),
                    targeted_node_ids=list(result.case.targeted_node_ids),
                    evidence=scrub_null_bytes(list(result.evidence)),
                    execution_trace=scrub_null_bytes(
                        result.simulation.model_dump(mode="json") if verdict in _TRACE_VERDICTS else {}
                    ),
                )
            )

        self.audit.record(
            "fuzz.campaign",
            f"Fuzz campaign scored {report.robustness_score}/100 across "
            f"{report.exercised_cases} exercised case(s).",
            workflow_id=workflow_id,
            version_id=version_id,
            metadata={"seed": report.seed, "counts": counts, **report.ai_metadata},
            commit=False,
        )
        self.db.commit()
        return self.get_run(workflow_id, run.id)

    def _latest_requirement_spec(self, workflow_id: uuid.UUID) -> RequirementSpec | None:
        record = (
            self.db.execute(
                select(RequirementSpecificationRecord)
                .where(RequirementSpecificationRecord.workflow_id == workflow_id)
                .order_by(desc(RequirementSpecificationRecord.created_at))
                .limit(1)
            )
            .scalars()
            .first()
        )
        return RequirementSpec.model_validate(record.spec_json) if record else None


def _counts_from_record(run: FuzzRunRecord) -> dict[str, int]:
    return {
        ErrorHandlingVerdict.HANDLED.value: run.handled,
        ErrorHandlingVerdict.UNHANDLED_CRASH.value: run.unhandled_crash,
        ErrorHandlingVerdict.SILENT_SUCCESS.value: run.silent_success,
        ErrorHandlingVerdict.HUNG.value: run.hung,
        ErrorHandlingVerdict.NOT_TRIGGERED.value: run.not_triggered,
    }
