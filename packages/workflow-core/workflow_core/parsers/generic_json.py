from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

from jsonschema import Draft202012Validator

from workflow_core.canonical.models import (
    Edge,
    Node,
    NodeType,
    SourceFormat,
    SourceType,
    Workflow,
)
from workflow_core.parsers.base import ParsedWorkflow, WorkflowParser
from workflow_core.parsers.errors import WorkflowParseError
from workflow_core.parsers.security import safe_json_loads

GENERIC_WORKFLOW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["nodes"],
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id"],
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                    "subtype": {"type": "string"},
                    "provider": {"type": "string"},
                    "operation": {"type": "string"},
                    "configuration": {"type": "object"},
                    "input_schema": {"type": "object"},
                    "output_schema": {"type": "object"},
                    "metadata": {"type": "object"},
                },
            },
        },
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["source", "target"],
                "properties": {
                    "id": {"type": "string"},
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "condition": {"type": "string"},
                    "label": {"type": "string"},
                    "metadata": {"type": "object"},
                },
            },
        },
        "variables": {"type": "array"},
        "metadata": {"type": "object"},
    },
}


class GenericJSONParser(WorkflowParser):
    format_name: ClassVar[str] = SourceFormat.GENERIC_JSON.value
    extensions: ClassVar[set[str]] = {".json"}

    def validate_source(self, content: bytes) -> bool:
        try:
            data = safe_json_loads(content)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return False
        return isinstance(data, dict) and "nodes" in data and "connections" not in data

    def parse(
        self,
        filename: str,
        content: bytes,
        source_type: SourceType = SourceType.UNKNOWN,
        source_prompt: str | None = None,
        content_type: str | None = None,
    ) -> ParsedWorkflow:
        try:
            data = safe_json_loads(content)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkflowParseError(f"Malformed JSON: {exc}") from exc

        validator = Draft202012Validator(GENERIC_WORKFLOW_SCHEMA)
        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
        if errors:
            first = errors[0]
            path = ".".join(str(part) for part in first.path) or "$"
            raise WorkflowParseError(f"Generic workflow schema error at {path}: {first.message}")

        nodes = [
            Node(
                id=str(item["id"]),
                name=str(item.get("name") or item["id"]),
                type=_node_type(item.get("type")),
                subtype=item.get("subtype"),
                provider=item.get("provider"),
                operation=item.get("operation"),
                configuration=item.get("configuration") or {},
                input_schema=item.get("input_schema"),
                output_schema=item.get("output_schema"),
                metadata=item.get("metadata") or {},
            )
            for item in data.get("nodes", [])
        ]
        edges = [
            Edge(
                id=str(item.get("id") or f"{item['source']}->{item['target']}"),
                source=str(item["source"]),
                target=str(item["target"]),
                condition=item.get("condition"),
                label=item.get("label"),
                metadata=item.get("metadata") or {},
            )
            for item in data.get("edges", [])
        ]
        workflow = Workflow(
            id=str(data.get("id") or Path(filename).stem),
            name=str(data.get("name") or Path(filename).stem),
            source_format=SourceFormat.GENERIC_JSON,
            source_type=source_type,
            source_prompt=source_prompt,
            metadata=data.get("metadata") or {},
            nodes=nodes,
            edges=edges,
            variables=data.get("variables") or [],
        )
        return ParsedWorkflow(workflow=workflow, raw_content=content.decode("utf-8"), content_type=content_type)


def _node_type(value: Any) -> NodeType:
    if not value:
        return NodeType.UNKNOWN
    normalized = str(value).lower()
    return NodeType(normalized) if normalized in NodeType._value2member_map_ else NodeType.UNKNOWN
