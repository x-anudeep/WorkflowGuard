import json
from pathlib import Path

import pytest

from workflow_core.analysis import condition_signals_failure, label_signals_failure
from workflow_core.canonical.models import NodeType, SourceFormat
from workflow_core.parsers.errors import WorkflowParseError
from workflow_core.parsers.registry import default_parser_registry
from workflow_core.validation.engine import ValidationEngine

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "examples"


@pytest.mark.parametrize(
    ("path", "format_name", "node_count"),
    [
        ("bpmn/valid-workflow.bpmn", SourceFormat.BPMN, 4),
        ("json/valid-workflow.json", SourceFormat.GENERIC_JSON, 4),
        ("n8n/valid-workflow.json", SourceFormat.N8N, 2),
    ],
)
def test_parsers_create_canonical_workflows(path: str, format_name: SourceFormat, node_count: int) -> None:
    file_path = EXAMPLES / path
    parsed = default_parser_registry().parse(file_path.name, file_path.read_bytes())
    assert parsed.workflow.source_format == format_name
    assert len(parsed.workflow.nodes) == node_count
    assert parsed.workflow.name


@pytest.mark.parametrize("path", ["bpmn/malformed.bpmn", "json/malformed.json", "n8n/malformed.json"])
def test_malformed_sources_raise_parse_errors(path: str) -> None:
    file_path = EXAMPLES / path
    with pytest.raises(WorkflowParseError):
        default_parser_registry().parse(file_path.name, file_path.read_bytes())


@pytest.mark.parametrize(
    ("path", "rule_id"),
    [
        ("json/orphan-node.json", "WG-GRAPH-006"),
        ("json/invalid-connection.json", "WG-GRAPH-003"),
        ("json/cycle.json", "WG-GRAPH-008"),
        ("n8n/invalid-connection.json", "WG-GRAPH-003"),
        ("bpmn/orphan-node.bpmn", "WG-GRAPH-006"),
    ],
)
def test_validation_rules_detect_expected_findings(path: str, rule_id: str) -> None:
    file_path = EXAMPLES / path
    workflow = default_parser_registry().parse(file_path.name, file_path.read_bytes()).workflow
    result = ValidationEngine().validate(workflow)
    assert any(finding.rule_id == rule_id for finding in result.findings)
    assert 0 <= result.structural_quality_score <= 100


def test_valid_workflow_has_high_structural_score() -> None:
    file_path = EXAMPLES / "json/valid-workflow.json"
    workflow = default_parser_registry().parse(file_path.name, file_path.read_bytes()).workflow
    result = ValidationEngine().validate(workflow)
    assert result.structural_quality_score >= 85
    assert not any(finding.severity in {"ERROR", "CRITICAL"} for finding in result.findings)


def test_qubi_parser_maps_node_types_and_lifts_branch_conditions() -> None:
    """qubi keeps behaviour in a nested `data` object and conditions on the Branch node."""
    content = json.dumps(
        {
            "nodes": [
                {"id": "n1", "position": {"x": 0, "y": 0}, "data": {"type": "Start", "name": "Start"}},
                {
                    "id": "n2",
                    "position": {"x": 1, "y": 0},
                    "data": {
                        "type": "Http",
                        "name": "Charge Card",
                        "method": "POST",
                        "url": "https://pay.internal/charge",
                        "saveOutputAs": "payResult",
                    },
                },
                {
                    "id": "n3",
                    "position": {"x": 2, "y": 0},
                    "data": {
                        "type": "Branch",
                        "name": "Paid?",
                        "conditions": [
                            {"expression": "{{payResult.success}} == false", "targetNodeId": "n4"},
                            {"expression": "{{payResult.success}} == true", "targetNodeId": "n5"},
                        ],
                    },
                },
                {"id": "n4", "position": {"x": 3, "y": 1}, "data": {"type": "HitlTask", "name": "Review"}},
                {"id": "n5", "position": {"x": 3, "y": 0}, "data": {"type": "End", "name": "End"}},
            ],
            "edges": [
                {"id": "e1", "source": "n1", "target": "n2"},
                {"id": "e2", "source": "n2", "target": "n3"},
                {"id": "e3", "source": "n3", "target": "n4"},
                {"id": "e4", "source": "n3", "target": "n5"},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
            "executionMode": "Sequential",
        }
    ).encode()

    workflow = default_parser_registry().parse("flow.json", content).workflow

    assert workflow.source_format == SourceFormat.QUBI
    types = {node.id: node.type for node in workflow.nodes}
    assert types["n1"] == NodeType.TRIGGER
    assert types["n2"] == NodeType.EXTERNAL_API
    assert types["n3"] == NodeType.CONDITION
    assert types["n4"] == NodeType.HUMAN_APPROVAL
    assert types["n5"] == NodeType.END

    charge = next(node for node in workflow.nodes if node.id == "n2")
    assert charge.name == "Charge Card"
    assert charge.provider == "pay.internal"
    assert charge.operation == "POST"
    assert charge.configuration["url"] == "https://pay.internal/charge"

    # Branch conditions belong to the Branch node in the source; they must land on the
    # edges they govern, with the {{ }} markers removed so consumers can parse them.
    conditions = {edge.id: edge.condition for edge in workflow.edges}
    assert conditions["e3"] == "payResult.success == false"
    assert conditions["e4"] == "payResult.success == true"
    assert conditions["e1"] is None


def test_qubi_export_is_not_claimed_by_the_generic_json_parser() -> None:
    content = json.dumps(
        {
            "nodes": [{"id": "n1", "position": {"x": 0, "y": 0}, "data": {"type": "Start", "name": "Start"}}],
            "edges": [],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        }
    ).encode()
    parser = default_parser_registry().detect("flow.json", content)
    assert parser.format_name == "qubi"


def test_failure_path_detection_reads_polarity_not_substrings() -> None:
    """`retryAllocationResult.success == true` is the success branch, not an error path."""
    assert condition_signals_failure("allocationResult.success == false")
    assert not condition_signals_failure("allocationResult.success == true")
    assert not condition_signals_failure("retryAllocationResult.success == true")
    assert condition_signals_failure("errorField != null")
    assert not condition_signals_failure("errorField == null")
    assert condition_signals_failure('order.paymentStatus != "paid"')
    assert not condition_signals_failure('signupPayload.plan == "enterprise"')
    assert condition_signals_failure("resp.statusCode >= 400")

    assert label_signals_failure("on error")
    assert label_signals_failure("catch")
    assert not label_signals_failure("retryAllocationResult")
