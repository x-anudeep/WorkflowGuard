from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar
import re
from urllib.parse import urlsplit

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

#: qubi node type -> canonical node type. Anything unlisted falls back to UNKNOWN so a
#: new editor node degrades to a plain graph node rather than being misclassified.
NODE_TYPE_MAP: dict[str, NodeType] = {
    "start": NodeType.TRIGGER,
    "end": NodeType.END,
    "http": NodeType.EXTERNAL_API,
    "rpa": NodeType.EXTERNAL_API,
    "branch": NodeType.CONDITION,
    "agent": NodeType.LLM,
    "documentai": NodeType.LLM,
    "hitltask": NodeType.HUMAN_APPROVAL,
    "code": NodeType.ACTION,
    "jsonparser": NodeType.ACTION,
    "textparser": NodeType.ACTION,
    "assign": NodeType.ACTION,
}

#: Keys lifted out of ``data`` into first-class canonical fields rather than configuration.
_PROMOTED_KEYS = frozenset({"type", "name"})


class QubiParser(WorkflowParser):
    """Parser for qubi flow exports.

    Two details make this more than a field rename. Node behaviour lives in a nested
    ``data`` object, and branch conditions live on the *Branch node* as
    ``conditions[{expression, targetNodeId}]`` while the edges carry only id/source/target.
    Both are projected onto the canonical model here, because analyzers reason over node
    ``configuration`` and edge ``condition`` - without the projection every branch and
    every integration would be invisible.
    """

    format_name: ClassVar[str] = SourceFormat.QUBI.value
    extensions: ClassVar[set[str]] = {".json"}

    def validate_source(self, content: bytes) -> bool:
        try:
            data = safe_json_loads(content)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return False
        if not isinstance(data, dict) or "connections" in data:
            return False
        nodes = data.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            return False
        # The distinguishing shape: every node carries a nested `data` object, and the
        # export carries editor state a generic workflow document would not.
        typed = [item for item in nodes if isinstance(item, dict) and isinstance(item.get("data"), dict)]
        return len(typed) == len(nodes) and ("viewport" in data or "executionMode" in data)

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
        if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
            raise WorkflowParseError("qubi workflow must contain a 'nodes' array.")

        raw_nodes = [item for item in data["nodes"] if isinstance(item, dict) and item.get("id")]
        nodes = [_node(item) for item in raw_nodes]
        edges = _edges(data.get("edges") or [], raw_nodes)

        stem = Path(filename).stem
        workflow = Workflow(
            id=str(data.get("id") or stem),
            name=str(data.get("name") or stem),
            source_format=SourceFormat.QUBI,
            source_type=source_type,
            source_prompt=source_prompt,
            metadata={
                key: value
                for key, value in data.items()
                if key in {"viewport", "executionMode"} and value is not None
            },
            nodes=nodes,
            edges=edges,
        )
        return ParsedWorkflow(workflow=workflow, raw_content=content.decode("utf-8"), content_type=content_type)


def _node(item: dict[str, Any]) -> Node:
    payload = item.get("data") or {}
    raw_type = str(payload.get("type") or item.get("type") or "")
    node_id = str(item["id"])
    return Node(
        id=node_id,
        name=str(payload.get("name") or raw_type or node_id),
        type=NODE_TYPE_MAP.get(raw_type.lower(), NodeType.UNKNOWN),
        subtype=raw_type or None,
        provider=_provider(raw_type, payload),
        operation=_operation(raw_type, payload),
        configuration={key: value for key, value in payload.items() if key not in _PROMOTED_KEYS},
        metadata={"position": item["position"]} if isinstance(item.get("position"), dict) else {},
    )


def _provider(raw_type: str, payload: dict[str, Any]) -> str | None:
    """Best-effort integration identity, used by cost and security analysis."""
    lowered = raw_type.lower()
    if lowered == "http":
        host = urlsplit(str(payload.get("url") or "")).hostname
        return host or "http"
    if lowered in {"agent", "documentai"}:
        return lowered
    if lowered == "rpa":
        return "rpa"
    return None


def _operation(raw_type: str, payload: dict[str, Any]) -> str | None:
    lowered = raw_type.lower()
    for key in ("method", "operation", "agentId", "automationId", "taskType"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return lowered or None


def _edges(raw_edges: list[Any], raw_nodes: list[dict[str, Any]]) -> list[Edge]:
    """Build edges, projecting Branch conditions onto the edges they govern.

    A Branch node states its conditions as ``{expression, targetNodeId}``. The exported
    edges carry no condition or label at all, so without this projection every branch in
    a qubi workflow looks like an unconditional fan-out.
    """
    conditions: dict[tuple[str, str], str] = {}
    for item in raw_nodes:
        payload = item.get("data") or {}
        if str(payload.get("type") or "").lower() != "branch":
            continue
        for condition in payload.get("conditions") or []:
            if not isinstance(condition, dict):
                continue
            target = condition.get("targetNodeId")
            expression = condition.get("expression")
            if isinstance(target, str) and isinstance(expression, str) and expression.strip():
                conditions[(str(item["id"]), target)] = _normalize_expression(expression)

    edges: list[Edge] = []
    for item in raw_edges:
        if not isinstance(item, dict) or not item.get("source") or not item.get("target"):
            continue
        source = str(item["source"])
        target = str(item["target"])
        expression = conditions.get((source, target))
        edges.append(
            Edge(
                id=str(item.get("id") or f"{source}->{target}"),
                source=source,
                target=target,
                condition=expression,
                label=item.get("label"),
                metadata={},
            )
        )
    return edges


def _normalize_expression(expression: str) -> str:
    """Strip qubi's ``{{ }}`` template markers from a branch expression.

    The canonical contract is that ``Edge.condition`` is a plain expression over
    workflow state. Leaving the markers in place makes the field reference unparseable
    to every consumer - the simulator reads ``is_executive}}`` as the field name, fails
    to resolve it, and abandons the run at the first branch.
    """
    return _TEMPLATE_MARKERS.sub("", expression).strip()


_TEMPLATE_MARKERS = re.compile(r"\{\{\s*|\s*\}\}")
