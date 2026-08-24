from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SourceFormat(StrEnum):
    BPMN = "bpmn"
    GENERIC_JSON = "generic_json"
    N8N = "n8n"


class SourceType(StrEnum):
    HUMAN = "human"
    AI_GENERATED = "ai_generated"
    UNKNOWN = "unknown"


class NodeType(StrEnum):
    TRIGGER = "trigger"
    ACTION = "action"
    CONDITION = "condition"
    LLM = "llm"
    HUMAN_APPROVAL = "human_approval"
    EXTERNAL_API = "external_api"
    DATABASE = "database"
    END = "end"
    EVENT = "event"
    GATEWAY = "gateway"
    TASK = "task"
    UNKNOWN = "unknown"


class ValidationSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class WorkflowVariable(BaseModel):
    name: str
    type: str | None = None
    default: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Node(BaseModel):
    id: str
    name: str
    type: NodeType = NodeType.UNKNOWN
    subtype: str | None = None
    provider: str | None = None
    operation: str | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(use_enum_values=True)

    @field_validator("id", "name")
    @classmethod
    def non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class Edge(BaseModel):
    id: str = Field(default_factory=lambda: f"edge_{uuid4().hex}")
    source: str
    target: str
    condition: str | None = None
    label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source", "target")
    @classmethod
    def non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class ValidationFinding(BaseModel):
    rule_id: str
    severity: ValidationSeverity
    title: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None
    remediation: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(use_enum_values=True)


class Workflow(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    source_format: SourceFormat
    source_type: SourceType = SourceType.UNKNOWN
    source_prompt: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    variables: list[WorkflowVariable] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(use_enum_values=True)

    @field_validator("name")
    @classmethod
    def name_non_empty(cls, value: str) -> str:
        value = value.strip()
        return value or "Untitled workflow"

    @property
    def start_node_ids(self) -> set[str]:
        incoming = {edge.target for edge in self.edges}
        typed_starts = {node.id for node in self.nodes if node.type == NodeType.TRIGGER}
        return typed_starts or {node.id for node in self.nodes if node.id not in incoming}

    @property
    def terminal_node_ids(self) -> set[str]:
        outgoing = {edge.source for edge in self.edges}
        typed_ends = {node.id for node in self.nodes if node.type == NodeType.END}
        return typed_ends or {node.id for node in self.nodes if node.id not in outgoing}
