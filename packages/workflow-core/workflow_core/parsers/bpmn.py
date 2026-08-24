from __future__ import annotations

from pathlib import Path

from lxml import etree

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
from workflow_core.parsers.security import safe_xml_root

BPMN_NS = {"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL"}
FLOW_NODE_TAGS = {
    "startEvent",
    "endEvent",
    "task",
    "userTask",
    "serviceTask",
    "scriptTask",
    "businessRuleTask",
    "sendTask",
    "receiveTask",
    "manualTask",
    "exclusiveGateway",
    "parallelGateway",
    "inclusiveGateway",
    "eventBasedGateway",
    "subProcess",
}


class BPMNParser(WorkflowParser):
    format_name = SourceFormat.BPMN.value
    extensions = {".bpmn", ".xml"}

    def validate_source(self, content: bytes) -> bool:
        try:
            root = safe_xml_root(content)
        except (ValueError, etree.XMLSyntaxError):
            return False
        return etree.QName(root).localname == "definitions" and "BPMN" in etree.QName(root).namespace

    def parse(
        self,
        filename: str,
        content: bytes,
        source_type: SourceType = SourceType.UNKNOWN,
        source_prompt: str | None = None,
        content_type: str | None = None,
    ) -> ParsedWorkflow:
        try:
            root = safe_xml_root(content)
        except (ValueError, etree.XMLSyntaxError) as exc:
            raise WorkflowParseError(f"Malformed XML: {exc}") from exc
        if not self.validate_source(content):
            raise WorkflowParseError("XML document is not a BPMN 2.0 definitions document.")

        process = root.find(".//bpmn:process", BPMN_NS)
        process_name = process.get("name") if process is not None else None
        nodes: list[Node] = []
        edges: list[Edge] = []

        for element in root.xpath(".//bpmn:*", namespaces=BPMN_NS):
            local = etree.QName(element).localname
            if local in FLOW_NODE_TAGS:
                nodes.append(
                    Node(
                        id=element.get("id"),
                        name=element.get("name") or element.get("id"),
                        type=_map_bpmn_type(local),
                        subtype=local,
                        provider="bpmn",
                        configuration=_extension_metadata(element),
                        metadata={
                            "incoming": element.xpath("./bpmn:incoming/text()", namespaces=BPMN_NS),
                            "outgoing": element.xpath("./bpmn:outgoing/text()", namespaces=BPMN_NS),
                        },
                    )
                )
            elif local == "sequenceFlow":
                condition = element.find("./bpmn:conditionExpression", BPMN_NS)
                edges.append(
                    Edge(
                        id=element.get("id") or f"{element.get('sourceRef')}->{element.get('targetRef')}",
                        source=element.get("sourceRef") or "",
                        target=element.get("targetRef") or "",
                        condition=condition.text.strip() if condition is not None and condition.text else None,
                        label=element.get("name"),
                        metadata={"raw_attributes": dict(element.attrib)},
                    )
                )

        workflow = Workflow(
            id=process.get("id") if process is not None and process.get("id") else Path(filename).stem,
            name=process_name or Path(filename).stem,
            source_format=SourceFormat.BPMN,
            source_type=source_type,
            source_prompt=source_prompt,
            metadata={
                "definitions_id": root.get("id"),
                "target_namespace": root.get("targetNamespace"),
                "source_filename": filename,
            },
            nodes=nodes,
            edges=edges,
        )
        return ParsedWorkflow(workflow=workflow, raw_content=content.decode("utf-8"), content_type=content_type)


def _map_bpmn_type(local_name: str) -> NodeType:
    if local_name == "startEvent":
        return NodeType.TRIGGER
    if local_name == "endEvent":
        return NodeType.END
    if "Gateway" in local_name:
        return NodeType.CONDITION
    if local_name == "userTask":
        return NodeType.HUMAN_APPROVAL
    if local_name in {"serviceTask", "sendTask", "receiveTask"}:
        return NodeType.EXTERNAL_API
    return NodeType.TASK


def _extension_metadata(element: etree._Element) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for child in element:
        if etree.QName(child).localname == "extensionElements":
            metadata["extension_elements"] = etree.tostring(child, encoding="unicode")
    return metadata
