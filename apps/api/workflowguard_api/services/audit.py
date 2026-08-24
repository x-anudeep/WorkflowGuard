from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from workflowguard_api.models.db import AuditEventRecord


class AuditService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def record(
        self,
        event_type: str,
        message: str,
        *,
        workflow_id: uuid.UUID | None = None,
        version_id: uuid.UUID | None = None,
        actor: str = "system",
        metadata: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> AuditEventRecord:
        event = AuditEventRecord(
            workflow_id=workflow_id,
            version_id=version_id,
            event_type=event_type,
            actor=actor,
            message=message,
            metadata_json=metadata or {},
        )
        self.db.add(event)
        if commit:
            self.db.commit()
            self.db.refresh(event)
        else:
            self.db.flush()
        return event

    def list_for_workflow(self, workflow_id: uuid.UUID, *, limit: int = 100) -> list[AuditEventRecord]:
        return list(
            self.db.execute(
                select(AuditEventRecord)
                .where(AuditEventRecord.workflow_id == workflow_id)
                .order_by(desc(AuditEventRecord.created_at))
                .limit(limit)
            )
            .scalars()
            .all()
        )
