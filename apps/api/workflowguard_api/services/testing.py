from __future__ import annotations

import uuid

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload
from workflow_core.canonical.models import Workflow
from workflow_core.evaluation import DeterministicRequirementExtractor
from workflow_core.evaluation.models import RequirementSpec
from workflow_core.testing import (
    DeterministicTestGenerator,
    WorkflowTest,
    WorkflowTestRun,
    WorkflowTestRunner,
)
from workflow_core.testing.models import TestGenerationResult

from workflowguard_api.ai.providers import AIProviderError, AIProviderUnavailable
from workflowguard_api.ai.test_generation import (
    TestGenerationProvider,
    test_generation_provider_from_settings,
)
from workflowguard_api.core.config import get_settings
from workflowguard_api.models.db import (
    RequirementSpecificationRecord,
    WorkflowTestRecord,
    WorkflowTestRunRecord,
)
from workflowguard_api.services.evaluations import EvaluationService
from workflowguard_api.services.execution import build_engine
from workflowguard_api.services.workflows import WorkflowService


class WorkflowTestNotFoundError(LookupError):
    pass


class WorkflowTestRunNotFoundError(LookupError):
    pass


class WorkflowTestingService:
    def __init__(
        self,
        db: Session,
        ai_provider: TestGenerationProvider | None = None,
        engine=None,
    ) -> None:
        self.db = db
        self.workflow_service = WorkflowService(db)
        self.evaluation_service = EvaluationService(db)
        self.generator = DeterministicTestGenerator()
        self.extractor = DeterministicRequirementExtractor()
        self.runner = WorkflowTestRunner(engine or build_engine())
        self.ai_provider = ai_provider

    def generate_tests(self, workflow_id: uuid.UUID, *, use_ai: bool = True, replace_existing: bool = False) -> tuple[TestGenerationResult, list[WorkflowTestRecord]]:
        record, version, workflow = self._workflow_context(workflow_id)
        requirement_spec = self._latest_requirement_spec(workflow_id) or (
            self.extractor.extract(workflow.source_prompt) if workflow.source_prompt else None
        )
        deterministic = self.generator.generate(workflow, requirement_spec)
        warnings = list(deterministic.warnings)
        tests = list(deterministic.tests)

        if use_ai:
            try:
                provider = self.ai_provider or test_generation_provider_from_settings(get_settings())
                ai_result = provider.generate_tests(workflow, requirement_spec)
                for test in ai_result.tests:
                    test.generated_by = "AI"
                    test.metadata["ai_provider"] = provider.provider_name
                    test.metadata["ai_model"] = provider.model_name
                tests.extend(ai_result.tests)
                warnings.extend(ai_result.warnings)
            except AIProviderUnavailable as exc:
                warnings.append(f"AI generation skipped: {exc}")
            except AIProviderError as exc:
                # Covers HTTP status errors, timeouts, and malformed/non-JSON bodies. No AI
                # test is added: a provider that answered with an error code has told us
                # nothing about this workflow, and a partial suite is worse than none because
                # generated tests feed coverage and the quality gate.
                warnings.append(f"AI generation failed; deterministic tests were kept: {exc}")
            except Exception as exc:  # noqa: BLE001 - provider boundary, never lose the suite
                warnings.append(
                    f"AI generation failed unexpectedly; deterministic tests were kept: "
                    f"{type(exc).__name__}: {exc}"
                )

        if replace_existing:
            for existing in self.list_tests(workflow_id):
                self.db.delete(existing)
            self.db.flush()

        # Generation is idempotent by name. `_dedupe_tests` only collapses duplicates
        # within this batch; without also skipping names already stored, every press of
        # "Generate Tests" re-persisted the whole corpus and doubled the test count.
        existing_names = (
            set()
            if replace_existing
            else {existing.name for existing in self.list_tests(workflow_id)}
        )
        fresh = [test for test in _dedupe_tests(tests) if test.name not in existing_names]
        if not fresh and existing_names:
            warnings.append(
                "No new tests were generated; the existing suite already covers every "
                "generated case. Use replace_existing to regenerate it from scratch."
            )
        records = [self._persist_test(record.id, version.id, test) for test in fresh]
        self.db.commit()
        return (
            TestGenerationResult(
                tests=[self._record_to_test(item) for item in records],
                generated_by=deterministic.generated_by,
                rationale=deterministic.rationale,
                warnings=warnings,
            ),
            self.list_tests(workflow_id),
        )

    def create_test(self, workflow_id: uuid.UUID, test: WorkflowTest) -> WorkflowTestRecord:
        record, version, _workflow = self._workflow_context(workflow_id)
        persisted = self._persist_test(record.id, version.id, test)
        self.db.commit()
        return self.get_test(record.id, persisted.id)

    def list_tests(self, workflow_id: uuid.UUID) -> list[WorkflowTestRecord]:
        self.workflow_service.get_workflow(workflow_id)
        return list(
            self.db.execute(
                select(WorkflowTestRecord)
                .where(WorkflowTestRecord.workflow_id == workflow_id)
                .options(selectinload(WorkflowTestRecord.runs))
                .order_by(desc(WorkflowTestRecord.created_at))
            )
            .scalars()
            .all()
        )

    def get_test(self, workflow_id: uuid.UUID, test_id: uuid.UUID) -> WorkflowTestRecord:
        test = (
            self.db.execute(
                select(WorkflowTestRecord)
                .where(WorkflowTestRecord.workflow_id == workflow_id, WorkflowTestRecord.id == test_id)
                .options(selectinload(WorkflowTestRecord.runs))
            )
            .scalars()
            .first()
        )
        if test is None:
            raise WorkflowTestNotFoundError(str(test_id))
        return test

    def run_tests(self, workflow_id: uuid.UUID, test_ids: list[uuid.UUID] | None = None) -> list[WorkflowTestRunRecord]:
        record, version, workflow = self._workflow_context(workflow_id)
        tests = self.list_tests(workflow_id)
        if test_ids:
            wanted = set(test_ids)
            tests = [test for test in tests if test.id in wanted]
        requirement_spec = self._latest_requirement_spec(workflow_id) or (
            self.extractor.extract(workflow.source_prompt) if workflow.source_prompt else None
        )
        prior_runs: list[WorkflowTestRun] = []
        records = []
        core_tests = [self._record_to_test(test) for test in tests]
        for test_record, core_test in zip(tests, core_tests, strict=True):
            run = self.runner.run(
                workflow,
                core_test,
                all_tests=core_tests,
                prior_runs=prior_runs,
                requirement_spec=requirement_spec,
            )
            prior_runs.append(run)
            records.append(self._persist_run(record.id, version.id, test_record.id, run))
        self.db.commit()
        return self.list_runs(workflow_id, limit=len(records) or 100)

    def run_test(self, test_id: uuid.UUID) -> WorkflowTestRunRecord:
        test = self._get_test_any_workflow(test_id)
        return self.run_tests(test.workflow_id, [test.id])[0]

    def list_runs(self, workflow_id: uuid.UUID, *, limit: int = 100) -> list[WorkflowTestRunRecord]:
        self.workflow_service.get_workflow(workflow_id)
        return list(
            self.db.execute(
                select(WorkflowTestRunRecord)
                .where(WorkflowTestRunRecord.workflow_id == workflow_id)
                .order_by(desc(WorkflowTestRunRecord.created_at))
                .limit(limit)
            )
            .scalars()
            .all()
        )

    def get_run(self, run_id: uuid.UUID) -> WorkflowTestRunRecord:
        run = self.db.get(WorkflowTestRunRecord, run_id)
        if run is None:
            raise WorkflowTestRunNotFoundError(str(run_id))
        return run

    def dashboard_metrics(self) -> dict[str, float | int]:
        total_tests = self.db.scalar(select(func.count(WorkflowTestRecord.id))) or 0
        failing_runs = (
            self.db.scalar(
                select(func.count(WorkflowTestRunRecord.id)).where(WorkflowTestRunRecord.status.in_(["FAILED", "ERROR"]))
            )
            or 0
        )
        latest_run = (
            self.db.execute(select(WorkflowTestRunRecord).order_by(desc(WorkflowTestRunRecord.created_at)).limit(1))
            .scalars()
            .first()
        )
        latest_coverage = 0.0
        if latest_run and latest_run.coverage:
            latest_coverage = float(latest_run.coverage.get("overall_coverage") or 0)
        return {
            "total_workflow_tests": int(total_tests),
            "latest_test_coverage": round(latest_coverage, 2),
            "failing_test_runs": int(failing_runs),
        }

    def _workflow_context(self, workflow_id: uuid.UUID):
        record = self.workflow_service.get_workflow(workflow_id)
        version = self.workflow_service.get_current_version(record)
        workflow = Workflow.model_validate(version.canonical_json).model_copy(update={"id": str(record.id)})
        return record, version, workflow

    def _latest_requirement_spec(self, workflow_id: uuid.UUID) -> RequirementSpec | None:
        spec_record = self.evaluation_service.latest_requirements(workflow_id)
        return _spec_from_record(spec_record) if spec_record else None

    def _persist_test(self, workflow_id: uuid.UUID, version_id: uuid.UUID, test: WorkflowTest) -> WorkflowTestRecord:
        test = test.model_copy(update={"workflow_id": str(workflow_id), "workflow_version_id": str(version_id)})
        record = WorkflowTestRecord(
            workflow_id=workflow_id,
            version_id=version_id,
            name=test.name,
            description=test.description,
            generated_by=str(test.generated_by),
            input_data=test.input_data,
            mocked_integrations=[mock.model_dump(mode="json") for mock in test.mocked_integrations],
            failure_injections=[failure.model_dump(mode="json") for failure in test.failure_injections],
            expected_path=test.expected_path,
            expected_outputs=test.expected_outputs,
            expected_side_effects=test.expected_side_effects,
            forbidden_side_effects=test.forbidden_side_effects,
            assertions=[assertion.model_dump(mode="json") for assertion in test.assertions],
            expected_error=test.expected_error,
            tags=test.tags,
            importance=str(test.importance),
            enabled=1 if test.enabled else 0,
            rationale=test.rationale,
            linked_requirement_id=test.linked_requirement_id,
            metadata_json=test.metadata,
        )
        self.db.add(record)
        self.db.flush()
        return record

    def _persist_run(
        self,
        workflow_id: uuid.UUID,
        version_id: uuid.UUID,
        test_id: uuid.UUID,
        run: WorkflowTestRun,
    ) -> WorkflowTestRunRecord:
        record = WorkflowTestRunRecord(
            workflow_id=workflow_id,
            version_id=version_id,
            test_id=test_id,
            status=str(run.status),
            execution_trace=run.simulation.model_dump(mode="json"),
            assertion_results=[result.model_dump(mode="json") for result in run.assertion_results],
            failures=run.failures,
            duration_ms=run.duration_ms,
            coverage=run.coverage.model_dump(mode="json") if run.coverage else {},
        )
        self.db.add(record)
        self.db.flush()
        return record

    def _record_to_test(self, record: WorkflowTestRecord) -> WorkflowTest:
        return WorkflowTest(
            id=str(record.id),
            workflow_id=str(record.workflow_id),
            workflow_version_id=str(record.version_id) if record.version_id else None,
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
        )

    def _get_test_any_workflow(self, test_id: uuid.UUID) -> WorkflowTestRecord:
        test = self.db.get(WorkflowTestRecord, test_id, options=[selectinload(WorkflowTestRecord.runs)])
        if test is None:
            raise WorkflowTestNotFoundError(str(test_id))
        return test


def _dedupe_tests(tests: list[WorkflowTest]) -> list[WorkflowTest]:
    deduped: dict[str, WorkflowTest] = {}
    for test in tests:
        deduped.setdefault(test.name, test)
    return list(deduped.values())


def _spec_from_record(record: RequirementSpecificationRecord | None) -> RequirementSpec | None:
    if not record:
        return None
    return RequirementSpec.model_validate(record.spec_json)
