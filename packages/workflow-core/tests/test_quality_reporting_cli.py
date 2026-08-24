from __future__ import annotations

from pathlib import Path

from workflow_core.cli import main
from workflow_core.quality import QualityGateEngine
from workflow_core.reporting import render_markdown_report

ROOT = Path(__file__).resolve().parents[3]


def test_quality_gate_fails_when_required_dimensions_are_missing() -> None:
    result = QualityGateEngine().evaluate(structural_score=95, test_coverage=90)
    assert result.status == "FAIL"
    assert any(reason.rule_id == "WG-GATE-ALIGNMENT" for reason in result.reasons)


def test_markdown_report_contains_gate_and_scores() -> None:
    markdown = render_markdown_report(
        {
            "workflow": {"name": "Invoice QA", "id": "wf_1", "version_id": "v1"},
            "scores": {"overall": 82, "security": 90},
            "quality_gate": {"status": "FAIL", "reasons": []},
            "validation_findings": [],
            "evaluation_findings": [],
            "tests": {"total_tests": 2, "passed": 1, "failed": 1, "latest_coverage": 50},
            "cost": {"cost_per_run": 0.01, "monthly_cost": 30},
        }
    )
    assert "# WorkflowGuard Report: Invoice QA" in markdown
    assert "Quality Gate: **FAIL**" in markdown


def test_cli_check_returns_nonzero_for_broken_workflow() -> None:
    exit_code = main(["check", str(ROOT / "examples" / "json" / "orphan-node.json"), "--json"])
    assert exit_code == 1


def test_cli_report_generates_markdown(capsys) -> None:
    exit_code = main(["report", str(ROOT / "examples" / "json" / "valid-workflow.json")])
    assert exit_code == 0
    assert "WorkflowGuard Report" in capsys.readouterr().out
