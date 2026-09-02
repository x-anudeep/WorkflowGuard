from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import desc, select
from sqlalchemy.orm import Session
from workflow_core.documents import MarkdownRequirementParser
from workflow_core.documents.models import DocumentKind, RequirementDocument

from workflowguard_api.core.config import get_settings
from workflowguard_api.models.db import WorkflowAttachmentRecord, WorkflowRecord
from workflowguard_api.services.audit import AuditService

#: Text formats only. PDF and docx each need a new dependency and are deliberately out of scope.
SUPPORTED_SUFFIXES = (".md", ".markdown", ".txt")


class AttachmentNotFoundError(LookupError):
    pass


class UnsupportedAttachmentError(ValueError):
    pass


class AttachmentService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.parser = MarkdownRequirementParser()

    def add(
        self,
        workflow_id: uuid.UUID,
        *,
        filename: str,
        content: bytes,
        content_type: str | None = None,
        kind: str | None = None,
    ) -> WorkflowAttachmentRecord:
        workflow = self.db.get(WorkflowRecord, workflow_id)
        if workflow is None:
            raise AttachmentNotFoundError("Workflow not found")

        lowered = filename.lower()
        if not lowered.endswith(SUPPORTED_SUFFIXES):
            raise UnsupportedAttachmentError(
                f"Unsupported attachment format. Supported: {', '.join(SUPPORTED_SUFFIXES)}."
            )

        max_bytes = get_settings().max_upload_bytes
        if len(content) > max_bytes:
            raise UnsupportedAttachmentError(f"Attachment exceeds the {max_bytes} byte limit.")

        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UnsupportedAttachmentError("Attachment must be UTF-8 encoded text.") from exc

        document = self.parser.parse(text, filename=filename)
        resolved_kind = _coerce_kind(kind) or document.kind

        record = WorkflowAttachmentRecord(
            workflow_id=workflow_id,
            version_id=workflow.current_version_id,
            kind=str(resolved_kind),
            filename=filename,
            content_type=content_type,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            raw_content=text,
            extracted_json=document.model_dump(mode="json"),
            clause_count=len(document.clauses),
        )
        self.db.add(record)
        self.db.flush()
        AuditService(self.db).record(
            "attachment_added",
            f"Attached requirement document {filename}.",
            workflow_id=workflow_id,
            version_id=workflow.current_version_id,
            metadata={"kind": str(resolved_kind), "clauses": record.clause_count},
            commit=False,
        )
        self.db.commit()
        self.db.refresh(record)
        return record

    def list_for_workflow(self, workflow_id: uuid.UUID) -> list[WorkflowAttachmentRecord]:
        return list(
            self.db.execute(
                select(WorkflowAttachmentRecord)
                .where(WorkflowAttachmentRecord.workflow_id == workflow_id)
                .order_by(desc(WorkflowAttachmentRecord.created_at))
            )
            .scalars()
            .all()
        )

    def get(self, attachment_id: uuid.UUID) -> WorkflowAttachmentRecord:
        record = self.db.get(WorkflowAttachmentRecord, attachment_id)
        if record is None:
            raise AttachmentNotFoundError("Attachment not found")
        return record

    def delete(self, attachment_id: uuid.UUID) -> None:
        record = self.get(attachment_id)
        workflow_id = record.workflow_id
        filename = record.filename
        self.db.delete(record)
        AuditService(self.db).record(
            "attachment_removed",
            f"Removed requirement document {filename}.",
            workflow_id=workflow_id,
            commit=False,
        )
        self.db.commit()

    def documents_for(self, workflow_id: uuid.UUID) -> list[RequirementDocument]:
        """Rehydrate the parsed documents that feed requirement extraction.

        Parsed at upload time and stored, so evaluation never re-parses and a parser change
        cannot silently move an existing workflow's score without a re-upload.
        """
        documents: list[RequirementDocument] = []
        for record in reversed(self.list_for_workflow(workflow_id)):
            if not record.extracted_json:
                continue
            try:
                documents.append(RequirementDocument.model_validate(record.extracted_json))
            except ValueError:
                continue
        return documents


def _coerce_kind(kind: str | None) -> DocumentKind | None:
    if not kind:
        return None
    try:
        return DocumentKind(kind.lower())
    except ValueError:
        return None
