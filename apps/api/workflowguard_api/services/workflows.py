from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload
from workflow_core import ValidationEngine
from workflow_core.canonical.models import SourceType, Workflow
from workflow_core.parsers.errors import WorkflowParseError
from workflow_core.parsers.registry import default_parser_registry

from workflowguard_api.models.db import (
    ValidationFindingRecord,
    ValidationRun,
    WorkflowEdge,
    WorkflowFile,
    WorkflowNode,
    WorkflowRecord,
    WorkflowVersion,
)


class WorkflowNotFoundError(LookupError):
    pass


class WorkflowService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.registry = default_parser_registry()
        self.validator = ValidationEngine()

    def upload(
        self,
        *,
        filename: str,
        content: bytes,
        source_type: SourceType,
        source_prompt: str | None,
        content_type: str | None,
    ) -> tuple[WorkflowRecord, ValidationRun]:
        try:
            parsed = self.registry.parse(filename, content, source_type, source_prompt, content_type)
        except WorkflowParseError:
            raise
        except Exception as exc:
            raise WorkflowParseError(str(exc)) from exc
        workflow_record = self._persist_workflow(parsed.workflow, filename, content, parsed.raw_content, content_type)
        run = self.validate(workflow_record.id)
        return workflow_record, run

    def create_from_canonical(self, workflow: Workflow) -> tuple[WorkflowRecord, ValidationRun]:
        record = self._persist_workflow(workflow, "canonical.json", workflow.model_dump_json().encode(), workflow.model_dump_json(), "application/json")
        run = self.validate(record.id)
        return record, run

    def create_version_from_canonical(self, workflow_id: uuid.UUID, workflow: Workflow) -> WorkflowVersion:
        record = self.get_workflow(workflow_id)
        next_number = max((version.version_number for version in record.versions), default=0) + 1
        canonical = workflow.model_dump(mode="json")
        canonical["id"] = str(record.id)
        version = WorkflowVersion(
            workflow_id=record.id,
            version_number=next_number,
            canonical_json=canonical,
            variables_json=[variable.model_dump(mode="json") for variable in workflow.variables],
        )
        self.db.add(version)
        self.db.flush()
        record.current_version_id = version.id
        for node in workflow.nodes:
            self.db.add(
                WorkflowNode(
                    workflow_id=record.id,
                    version_id=version.id,
                    node_id=node.id,
                    name=node.name,
                    type=str(node.type),
                    subtype=node.subtype,
                    provider=node.provider,
                    operation=node.operation,
                    configuration=node.configuration,
                    input_schema=node.input_schema,
                    output_schema=node.output_schema,
                    metadata_json=node.metadata,
                )
            )
        for edge in workflow.edges:
            self.db.add(
                WorkflowEdge(
                    workflow_id=record.id,
                    version_id=version.id,
                    edge_id=edge.id,
                    source=edge.source,
                    target=edge.target,
                    condition=edge.condition,
                    label=edge.label,
                    metadata_json=edge.metadata,
                )
            )
        self.db.commit()
        self.db.refresh(version)
        return version

    def list_workflows(self) -> list[WorkflowRecord]:
        return list(
            self.db.execute(
                select(WorkflowRecord)
                .options(selectinload(WorkflowRecord.validation_runs).selectinload(ValidationRun.findings))
                .order_by(desc(WorkflowRecord.created_at))
            )
            .scalars()
            .all()
        )

    def get_workflow(self, workflow_id: uuid.UUID) -> WorkflowRecord:
        record = self.db.get(
            WorkflowRecord,
            workflow_id,
            options=[
                selectinload(WorkflowRecord.versions).selectinload(WorkflowVersion.nodes),
                selectinload(WorkflowRecord.versions).selectinload(WorkflowVersion.edges),
                selectinload(WorkflowRecord.validation_runs).selectinload(ValidationRun.findings),
            ],
        )
        if record is None:
            raise WorkflowNotFoundError(str(workflow_id))
        return record

    def get_current_version(self, record: WorkflowRecord) -> WorkflowVersion:
        for version in record.versions:
            if version.id == record.current_version_id:
                return version
        if record.versions:
            return sorted(record.versions, key=lambda item: item.version_number)[-1]
        raise WorkflowNotFoundError(f"Workflow {record.id} has no versions.")

    def validate(self, workflow_id: uuid.UUID) -> ValidationRun:
        record = self.get_workflow(workflow_id)
        version = self.get_current_version(record)
        workflow = Workflow.model_validate(version.canonical_json)
        result = self.validator.validate(workflow)
        run = ValidationRun(
            workflow_id=record.id,
            version_id=version.id,
            structural_quality_score=result.structural_quality_score,
            status="completed",
        )
        self.db.add(run)
        self.db.flush()
        for finding in result.findings:
            self.db.add(
                ValidationFindingRecord(
                    validation_run_id=run.id,
                    workflow_id=record.id,
                    version_id=version.id,
                    rule_id=finding.rule_id,
                    severity=str(finding.severity),
                    title=finding.title,
                    message=finding.message,
                    node_id=finding.node_id,
                    edge_id=finding.edge_id,
                    remediation=finding.remediation,
                    metadata_json=finding.metadata,
                )
            )
        self.db.commit()
        self.db.refresh(run)
        return run

    def latest_validation(self, workflow_id: uuid.UUID) -> ValidationRun | None:
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

    def dashboard_metrics(self) -> dict[str, object]:
        total_workflows = self.db.scalar(select(func.count(WorkflowRecord.id))) or 0
        total_validation_runs = self.db.scalar(select(func.count(ValidationRun.id))) or 0
        avg_score = self.db.scalar(select(func.avg(ValidationRun.structural_quality_score))) or 0
        critical_issues = (
            self.db.scalar(
                select(func.count(ValidationFindingRecord.id)).where(ValidationFindingRecord.severity == "CRITICAL")
            )
            or 0
        )
        return {
            "total_workflows": total_workflows,
            "total_validation_runs": total_validation_runs,
            "average_structural_score": round(float(avg_score), 2),
            "critical_issues": critical_issues,
            "recent_workflows": self.list_workflows()[:5],
        }

    def _persist_workflow(
        self,
        workflow: Workflow,
        filename: str,
        content: bytes,
        raw_content: str,
        content_type: str | None,
    ) -> WorkflowRecord:
        record = WorkflowRecord(
            name=workflow.name,
            source_format=str(workflow.source_format),
            source_type=str(workflow.source_type),
            source_prompt=workflow.source_prompt,
            metadata_json=workflow.metadata,
        )
        self.db.add(record)
        self.db.flush()
        canonical = workflow.model_dump(mode="json")
        canonical["id"] = str(record.id)
        version = WorkflowVersion(
            workflow_id=record.id,
            version_number=1,
            canonical_json=canonical,
            variables_json=[variable.model_dump(mode="json") for variable in workflow.variables],
        )
        self.db.add(version)
        self.db.flush()
        record.current_version_id = version.id

        self.db.add(
            WorkflowFile(
                workflow_id=record.id,
                version_id=version.id,
                filename=filename,
                content_type=content_type,
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                raw_content=raw_content,
            )
        )
        for node in workflow.nodes:
            self.db.add(
                WorkflowNode(
                    workflow_id=record.id,
                    version_id=version.id,
                    node_id=node.id,
                    name=node.name,
                    type=str(node.type),
                    subtype=node.subtype,
                    provider=node.provider,
                    operation=node.operation,
                    configuration=node.configuration,
                    input_schema=node.input_schema,
                    output_schema=node.output_schema,
                    metadata_json=node.metadata,
                )
            )
        for edge in workflow.edges:
            self.db.add(
                WorkflowEdge(
                    workflow_id=record.id,
                    version_id=version.id,
                    edge_id=edge.id,
                    source=edge.source,
                    target=edge.target,
                    condition=edge.condition,
                    label=edge.label,
                    metadata_json=edge.metadata,
                )
            )
        self.db.commit()
        return self.get_workflow(record.id)
