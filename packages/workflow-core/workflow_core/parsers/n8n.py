from __future__ import annotations

import json
from pathlib import Path

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


class N8NParser(WorkflowParser):
    format_name = SourceFormat.N8N.value
    extensions = {".json"}

    def validate_source(self, content: bytes) -> bool:
        try:
            data = safe_json_loads(content)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return False
        return isinstance(data, dict) and isinstance(data.get("nodes"), list) and isinstance(data.get("connections"), dict)

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
        if not self.validate_source(content):
            raise WorkflowParseError("n8n workflow must include nodes[] and connections{}.")

        nodes: list[Node] = []
        name_to_id: dict[str, str] = {}
        for raw_node in data.get("nodes", []):
            node_id = str(raw_node.get("id") or raw_node.get("name") or "")
            node_name = str(raw_node.get("name") or node_id)
            if not node_id:
                raise WorkflowParseError("n8n node is missing both id and name.")
            name_to_id[node_name] = node_id
            n8n_type = str(raw_node.get("type") or "")
            nodes.append(
                Node(
                    id=node_id,
                    name=node_name,
                    type=_map_n8n_node_type(n8n_type),
                    subtype=n8n_type,
                    provider="n8n",
                    operation=str(raw_node.get("typeVersion") or ""),
                    configuration=raw_node.get("parameters") or {},
                    metadata={
                        "position": raw_node.get("position"),
                        "credentials": raw_node.get("credentials"),
                        "raw": raw_node,
                    },
                )
            )

        edges: list[Edge] = []
        for source_name, outputs in data.get("connections", {}).items():
            source_id = name_to_id.get(source_name, source_name)
            for output_type, groups in outputs.items():
                for output_index, targets in enumerate(groups or []):
                    for target in targets or []:
                        target_name = str(target.get("node") or "")
                        target_id = name_to_id.get(target_name, target_name)
                        edges.append(
                            Edge(
                                id=f"{source_id}:{output_type}:{output_index}->{target_id}:{target.get('index', 0)}",
                                source=source_id,
                                target=target_id,
                                label=output_type,
                                metadata={"output_index": output_index, "target": target},
                            )
                        )

        workflow = Workflow(
            id=str(data.get("id") or Path(filename).stem),
            name=str(data.get("name") or Path(filename).stem),
            source_format=SourceFormat.N8N,
            source_type=source_type,
            source_prompt=source_prompt,
            metadata={k: v for k, v in data.items() if k not in {"nodes", "connections"}},
            nodes=nodes,
            edges=edges,
        )
        return ParsedWorkflow(workflow=workflow, raw_content=content.decode("utf-8"), content_type=content_type)


def _map_n8n_node_type(n8n_type: str) -> NodeType:
    value = n8n_type.lower()
    if "trigger" in value or "webhook" in value:
        return NodeType.TRIGGER
    if "if" in value or "switch" in value:
        return NodeType.CONDITION
    if "openai" in value or "lm" in value or "langchain" in value:
        return NodeType.LLM
    if "postgres" in value or "mysql" in value or "database" in value:
        return NodeType.DATABASE
    if "gmail" in value or "email" in value or "mail" in value:
        return NodeType.EMAIL
    if "http" in value or "api" in value:
        return NodeType.EXTERNAL_API
    return NodeType.ACTION
