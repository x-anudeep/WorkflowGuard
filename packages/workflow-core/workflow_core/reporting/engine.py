from __future__ import annotations

from typing import Any


def render_markdown_report(report: dict[str, Any]) -> str:
    workflow = report.get("workflow", {})
    gate = report.get("quality_gate", {})
    lines = [
        f"# WorkflowGuard Report: {workflow.get('name', 'Workflow')}",
        "",
        f"- Workflow ID: `{workflow.get('id', 'unknown')}`",
        f"- Version: `{workflow.get('version_id', 'unknown')}`",
        f"- Source: {workflow.get('source_format', 'unknown')} / {workflow.get('source_type', 'unknown')}",
        f"- Quality Gate: **{gate.get('status', 'UNKNOWN')}**",
        "",
        "## Scores",
    ]
    for key, value in (report.get("scores") or {}).items():
        lines.append(f"- {key.replace('_', ' ').title()}: {value if value is not None else 'Not measured'}")
    lines.extend(["", "## Quality Gate Reasons"])
    for reason in gate.get("reasons", []):
        mark = "PASS" if reason.get("passed") else "FAIL"
        lines.append(f"- {mark} `{reason.get('rule_id')}` {reason.get('title')}: {reason.get('actual')} expected {reason.get('expected')}")
    lines.extend(["", "## Validation Findings"])
    _append_findings(lines, report.get("validation_findings") or [])
    lines.extend(["", "## Evaluation Findings"])
    _append_findings(lines, report.get("evaluation_findings") or [])
    lines.extend(["", "## Test Results"])
    tests = report.get("tests") or {}
    total_tests = tests.get("total_tests", tests.get("tests", 0))
    lines.append(
        f"- Total: {total_tests}; Passed: {tests.get('passed', 0)}; Failed: {tests.get('failed', 0)}; Coverage: {tests.get('latest_coverage', tests.get('overall_coverage', 0))}%"
    )
    lines.extend(["", "## Cost"])
    cost = report.get("cost") or {}
    lines.append(f"- Cost/run: ${float(cost.get('cost_per_run') or 0):.4f}")
    lines.append(f"- Monthly: ${float(cost.get('monthly_cost') or 0):.2f}")
    lines.extend(["", "## Optimization Opportunities"])
    lines.extend(
        f"- `{finding.get('rule_id')}` {finding.get('title')}: {finding.get('recommendation')}"
        for finding in report.get("optimization_findings") or []
    )
    return "\n".join(lines) + "\n"


def _append_findings(lines: list[str], findings: list[dict[str, Any]]) -> None:
    if not findings:
        lines.append("- None recorded.")
        return
    lines.extend(
        f"- {finding.get('severity', 'INFO')} `{finding.get('rule_id')}` {finding.get('title')}: {finding.get('message')}"
        for finding in findings
    )
