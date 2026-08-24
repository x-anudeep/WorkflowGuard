from pathlib import Path

import pytest
from workflow_core.canonical.models import SourceFormat
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
