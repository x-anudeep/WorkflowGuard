from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from workflow_core.canonical.models import Edge, Node


class PatchOperation(StrEnum):
    UPDATE_NODE_CONFIGURATION = "update_node_configuration"
    ADD_NODE = "add_node"
    ADD_EDGE = "add_edge"
    REMOVE_EDGE = "remove_edge"


class RepairPatchOperation(BaseModel):
    op: PatchOperation
    node_id: str | None = None
    edge_id: str | None = None
    configuration_patch: dict[str, Any] = Field(default_factory=dict)
    node: Node | None = None
    edge: Edge | None = None
    rationale: str

    @field_validator("rationale")
    @classmethod
    def non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("rationale must not be empty")
        return value


class RepairPatch(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    finding_id: str | None = None
    title: str
    summary: str
    operations: list[RepairPatchOperation]
    safety_notes: list[str] = Field(default_factory=list)
    behavior_changes: list[str] = Field(default_factory=list)


class RepairPreview(BaseModel):
    patch: RepairPatch
    before: dict[str, Any]
    after: dict[str, Any]
    validation_findings: list[dict[str, Any]] = Field(default_factory=list)
    evaluation_findings: list[dict[str, Any]] = Field(default_factory=list)
    test_summary: dict[str, Any] = Field(default_factory=dict)
    cost_summary: dict[str, Any] = Field(default_factory=dict)
    safety_flags: list[str] = Field(default_factory=list)
