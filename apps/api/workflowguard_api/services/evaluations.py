from __future__ import annotations

import uuid

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload
from workflow_core.canonical.models import ValidationFinding, Workflow
from workflow_core.evaluation import (
    DeterministicRequirementExtractor,
    RequirementSpec,
    SemanticEvaluationEngine,
)
from workflow_core.evaluation.models import RequirementMatch

from workflowguard_api.ai.alignment import AlignmentProvider, alignment_provider_from_settings
from workflowguard_api.ai.errors import MalformedAIResponse
from workflowguard_api.ai.providers import (
    AIProviderError,
    AIProviderUnavailable,
    RequirementExtractionProvider,
    provider_from_settings,
)
from workflowguard_api.core.config import get_settings
from workflowguard_api.models.db import (
    DimensionScoreRecord,
    EvaluationFindingRecord,
    EvaluationRun,
    RequirementSpecificationRecord,
    WorkflowRecord,
)
from workflowguard_api.services.attachments import AttachmentService
from workflowguard_api.services.fuzzing import FuzzService
from workflowguard_api.services.workflows import WorkflowService


class EvaluationNotFoundError(LookupError):
    pass


class EvaluationService:
    def __init__(
        self,
        db: Session,
        ai_provider: RequirementExtractionProvider | None = None,
        alignment_provider: AlignmentProvider | None = None,
    ) -> None:
        self.db = db
        self.workflow_service = WorkflowService(db)
        self.engine = SemanticEvaluationEngine()
        self.extractor = DeterministicRequirementExtractor()
        self.ai_provider = ai_provider
        self.alignment_provider = alignment_provider

    def evaluate(self, workflow_id: uuid.UUID, *, use_ai: bool = True) -> EvaluationRun:
        record = self.workflow_service.get_workflow(workflow_id)
        version = self.workflow_service.get_current_version(record)
        workflow = Workflow.model_validate(version.canonical_json)
        validation_run = self.workflow_service.latest_validation(workflow_id) or self.workflow_service.validate(workflow_id)
        workflow = workflow.model_copy(update={"id": str(record.id)})

        spec, spec_record, ai_metadata, ai_provider_name, ai_model = self._build_requirement_spec(
            record, version.id, workflow, use_ai=use_ai
        )
        validation_findings = [
            _validation_finding_to_core(finding)
            for finding in validation_run.findings
        ]
        # Reliability blends measured fuzz survival with static analysis when a campaign
        # exists for this exact version; without one the score stays purely static.
        fuzz_report = FuzzService(self.db).report_for_evaluation(record.id, version.id)
        # Document requirements are written in business language the keyword matcher cannot
        # bridge, so they get an AI matcher when one is configured. Prompt-only workflows
        # keep the deterministic path exactly as before.
        matches, match_metadata = self._match_requirements(spec, workflow, use_ai=use_ai)
        ai_metadata.update(match_metadata)
        result = self.engine.evaluate(
            workflow,
            structural_score=round(validation_run.structural_quality_score),
            validation_findings=validation_findings,
            requirement_spec=spec,
            fuzz_report=fuzz_report,
            requirement_matches=matches,
        )
        result.ai_metadata.update(ai_metadata)
        result.ai_provider = ai_provider_name
        result.ai_model = ai_model

        run = EvaluationRun(
            workflow_id=record.id,
            version_id=version.id,
            requirement_spec_id=spec_record.id if spec_record else None,
            validation_run_id=validation_run.id,
            status=result.status,
            overall_score=result.overall_score,
            structural_score=result.structural_score,
            evaluator_version=result.evaluator_version,
            ai_provider=result.ai_provider,
            ai_model=result.ai_model,
            ai_metadata=result.ai_metadata,
            limitations=result.limitations,
            requirement_matches=[match.model_dump(mode="json") for match in result.requirement_matches],
        )
        self.db.add(run)
        self.db.flush()

        for score in result.dimension_scores:
            self.db.add(
                DimensionScoreRecord(
                    evaluation_run_id=run.id,
                    workflow_id=record.id,
                    version_id=version.id,
                    dimension=str(score.dimension),
                    score=score.score,
                    explanation=score.explanation,
                    calculation=score.calculation,
                )
            )
        for finding in result.findings:
            self.db.add(
                EvaluationFindingRecord(
                    evaluation_run_id=run.id,
                    workflow_id=record.id,
                    version_id=version.id,
                    rule_id=finding.rule_id,
                    dimension=str(finding.dimension),
                    severity=str(finding.severity),
                    title=finding.title,
                    message=finding.message,
                    expected=finding.expected,
                    found=finding.found,
                    why_it_matters=finding.why_it_matters,
                    node_id=finding.node_id,
                    edge_id=finding.edge_id,
                    path_json=finding.path,
                    remediation=finding.remediation,
                    confidence=str(finding.confidence),
                    metadata_json=finding.metadata,
                )
            )
        self.db.commit()
        return self.get_evaluation(record.id, run.id)

    def list_evaluations(self, workflow_id: uuid.UUID) -> list[EvaluationRun]:
        self.workflow_service.get_workflow(workflow_id)
        return list(
            self.db.execute(
                select(EvaluationRun)
                .where(EvaluationRun.workflow_id == workflow_id)
                .options(
                    selectinload(EvaluationRun.findings),
                    selectinload(EvaluationRun.dimension_scores),
                    selectinload(EvaluationRun.requirement_spec),
                )
                .order_by(desc(EvaluationRun.created_at))
            )
            .scalars()
            .all()
        )

    def get_evaluation(self, workflow_id: uuid.UUID, evaluation_id: uuid.UUID) -> EvaluationRun:
        run = (
            self.db.execute(
                select(EvaluationRun)
                .where(EvaluationRun.workflow_id == workflow_id, EvaluationRun.id == evaluation_id)
                .options(
                    selectinload(EvaluationRun.findings),
                    selectinload(EvaluationRun.dimension_scores),
                    selectinload(EvaluationRun.requirement_spec),
                )
            )
            .scalars()
            .first()
        )
        if run is None:
            raise EvaluationNotFoundError(str(evaluation_id))
        return run

    def latest_requirements(self, workflow_id: uuid.UUID) -> RequirementSpecificationRecord | None:
        self.workflow_service.get_workflow(workflow_id)
        return (
            self.db.execute(
                select(RequirementSpecificationRecord)
                .where(RequirementSpecificationRecord.workflow_id == workflow_id)
                .order_by(desc(RequirementSpecificationRecord.created_at))
                .limit(1)
            )
            .scalars()
            .first()
        )

    def dashboard_metrics(self) -> dict[str, float | int]:
        total = self.db.scalar(select(func.count(EvaluationRun.id))) or 0
        avg = self.db.scalar(select(func.avg(EvaluationRun.overall_score))) or 0
        return {"total_evaluation_runs": int(total), "average_overall_score": round(float(avg), 2)}

    def _match_requirements(
        self,
        spec: RequirementSpec | None,
        workflow: Workflow,
        *,
        use_ai: bool,
    ) -> tuple[list[RequirementMatch] | None, dict[str, str]]:
        """Ask an AI provider to judge requirement/node correspondence.

        Only worth doing when the spec carries document requirements: prompt requirements share
        vocabulary with node names, so the deterministic matcher handles them well and calling a
        model for them would change existing scores for no benefit.
        """
        if spec is None:
            return None, {}
        if not any(item.source == "document" for item in spec.requirements):
            return None, {}
        if not use_ai:
            return None, {"match_status": "disabled_by_request"}

        try:
            provider = self.alignment_provider or alignment_provider_from_settings(get_settings())
            matches = provider.match_requirements(spec, workflow)
        except AIProviderUnavailable as exc:
            return None, {"match_status": "unavailable_fallback", "match_reason": str(exc)}
        except AIProviderError as exc:
            return None, {"match_status": "error_fallback", "match_reason": str(exc)}
        except MalformedAIResponse as exc:
            return None, {"match_status": "error_fallback", "match_reason": str(exc)}
        return matches, {
            "match_status": "used",
            "match_provider": provider.provider_name,
            "match_model": provider.model_name or "",
        }

    def _build_requirement_spec(
        self,
        record: WorkflowRecord,
        version_id: uuid.UUID,
        workflow: Workflow,
        *,
        use_ai: bool,
    ) -> tuple[RequirementSpec | None, RequirementSpecificationRecord | None, dict, str | None, str | None]:
        documents = AttachmentService(self.db).documents_for(record.id)
        if not workflow.source_prompt and not documents:
            return None, None, {"ai_status": "skipped_no_requirements"}, None, None
        if not workflow.source_prompt and not any(document.clauses for document in documents):
            return None, None, {"ai_status": "skipped_no_prompt"}, None, None

        ai_metadata: dict[str, str] = {}
        provider_name: str | None = None
        model_name: str | None = None
        spec: RequirementSpec
        if use_ai and workflow.source_prompt:
            try:
                provider = self.ai_provider or provider_from_settings(get_settings())
                spec = provider.extract_requirements(workflow.source_prompt)
                provider_name = provider.provider_name
                model_name = provider.model_name
                spec.extraction_method = f"ai:{provider.provider_name}"
                ai_metadata["ai_status"] = "used"
            except AIProviderUnavailable as exc:
                spec = self.extractor.extract(workflow.source_prompt)
                ai_metadata = {"ai_status": "unavailable_fallback", "reason": str(exc)}
            except AIProviderError as exc:
                spec = self.extractor.extract(workflow.source_prompt)
                ai_metadata = {"ai_status": "error_fallback", "reason": str(exc)}
        elif workflow.source_prompt:
            spec = self.extractor.extract(workflow.source_prompt)
            ai_metadata["ai_status"] = "disabled_by_request"
        else:
            spec = self.extractor.extract_composite(None, None)
            ai_metadata["ai_status"] = "documents_only"

        if documents:
            # Merge the document clauses onto whatever the prompt produced. Clauses are already
            # atomic, so they bypass the prompt clause splitter entirely.
            spec = self.extractor.merge_documents(spec, documents, prompt=workflow.source_prompt)

        record_spec = RequirementSpecificationRecord(
            workflow_id=record.id,
            version_id=version_id,
            # The composite text, not the raw prompt: it is the audit record of everything the
            # workflow was matched against, and a document-only workflow has no prompt at all.
            source_prompt=spec.source_prompt,
            extraction_method=spec.extraction_method,
            confidence=str(spec.confidence),
            spec_json=spec.model_dump(mode="json"),
            model_provider=provider_name,
            model_name=model_name,
        )
        self.db.add(record_spec)
        self.db.flush()
        return spec, record_spec, ai_metadata, provider_name, model_name


def _validation_finding_to_core(record) -> ValidationFinding:
    return ValidationFinding(
        rule_id=record.rule_id,
        severity=record.severity,
        title=record.title,
        message=record.message,
        node_id=record.node_id,
        edge_id=record.edge_id,
        remediation=record.remediation,
        metadata=record.metadata_json,
    )
