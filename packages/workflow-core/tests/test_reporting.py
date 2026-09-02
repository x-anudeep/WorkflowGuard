"""The HTML report has to be HTML, not markdown in a <p>.

The previous converter wrapped every line in <p>, turned each blank line into an empty <h1>
(any falsy line took the heading branch), collapsed every heading level to h1, left list
markers and backticks as literal text, and interpolated finding messages without escaping.
"""

from workflow_core.reporting import markdown_to_html, render_html_report, render_markdown_report

REPORT = {
    "workflow": {"id": "wf-1", "name": "C02", "version_id": "v-1", "source_format": "qubi"},
    "quality_gate": {
        "status": "FAIL",
        "reasons": [
            {"passed": False, "rule_id": "WG-GATE-SECURITY", "title": "Security score", "actual": "78.0", "expected": ">= 85.0"}
        ],
    },
    "scores": {"overall": 89.0, "security": 78.0},
    "validation_findings": [],
    "evaluation_findings": [
        {"severity": "WARNING", "rule_id": "WG-SEC-004", "title": "Missing auth", "message": "Node 'A & B' <needs> auth"}
    ],
    "tests": {"total_tests": 96, "passed": 48, "failed": 33, "error": 15, "skipped": 0, "latest_coverage": 68.3},
    "requirement_documents": [{"kind": "brd", "filename": "C02_brd.md", "clause_count": 31}],
    "fuzz": {
        "robustness_score": 9, "total_cases": 70, "exercised_cases": 55, "handled": 5,
        "unhandled_crash": 40, "silent_success": 10, "hung": 0, "not_triggered": 15, "seed": 1337,
    },
    "limitations": ["Requirement matching ran without an AI provider."],
    "ai": {"provider": "groq", "model": "openai/gpt-oss-120b",
           "metadata": {"ai_status": "used", "match_status": "unavailable_fallback"},
           "evaluator_version": "part2-deterministic-v2"},
    "cost": {"cost_per_run": 0.01, "monthly_cost": 3.0},
    "optimization_findings": [],
}


def test_headings_keep_their_level() -> None:
    out = markdown_to_html("# Title\n\n## Section\n\n### Subsection")
    assert "<h1>Title</h1>" in out
    assert "<h2>Section</h2>" in out
    assert "<h3>Subsection</h3>" in out


def test_blank_lines_do_not_become_empty_headings() -> None:
    """The specific bug: `if line and not line.startswith('#')` sent '' to the heading branch."""
    out = markdown_to_html("# Title\n\n\nsome text\n")
    assert "<h1></h1>" not in out
    assert "<p></p>" not in out


def test_bullets_become_a_real_list() -> None:
    out = markdown_to_html("- one\n- two\n")
    assert out.count("<ul>") == 1 and out.count("</ul>") == 1
    assert "<li>one</li>" in out and "<li>two</li>" in out
    assert "<p>- one</p>" not in out


def test_inline_markers_are_converted_not_shown() -> None:
    out = markdown_to_html("- Gate: **FAIL** `WG-GATE-SECURITY`")
    assert "<strong>FAIL</strong>" in out
    assert "<code>WG-GATE-SECURITY</code>" in out
    assert "**" not in out and "`" not in out


def test_content_is_escaped() -> None:
    """Report text carries uploaded names and finding messages; it must not inject markup."""
    out = markdown_to_html("- Node '<script>alert(1)</script>' & co")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "&amp;" in out


def test_full_report_renders_a_standalone_document() -> None:
    out = render_html_report(REPORT)
    assert out.startswith("<!doctype html>")
    assert "<title>WorkflowGuard Report: C02</title>" in out
    assert "<h2>Scores</h2>" in out
    assert "<h2>Quality Gate Reasons</h2>" in out
    # the finding message contained markup characters
    assert "&lt;needs&gt;" in out
    assert "<script" not in out.lower()


def test_markdown_report_is_unchanged() -> None:
    """Regression guard: only the HTML path was broken."""
    markdown = render_markdown_report(REPORT)
    assert markdown.startswith("# WorkflowGuard Report: C02")
    assert "- Quality Gate: **FAIL**" in markdown


def test_errored_tests_are_reported_not_silently_dropped() -> None:
    """The bug: 48 passed + 33 failed against a total of 96 lost 15 errored tests.

    A test that errored could not run at all, which is worse than one that failed, so omitting
    it made the suite look healthier than it was and the arithmetic impossible to check.
    """
    markdown = render_markdown_report(REPORT)
    line = next(line for line in markdown.splitlines() if line.startswith("- Total:"))
    assert "Errored: 15" in line
    assert "Skipped: 0" in line

    numbers = {"Passed": 48, "Failed": 33, "Errored": 15, "Skipped": 0}
    assert sum(numbers.values()) == REPORT["tests"]["total_tests"]
    assert "not accounted for" not in markdown


def test_unaccounted_tests_are_called_out() -> None:
    report = {**REPORT, "tests": {"total_tests": 10, "passed": 3, "failed": 1, "error": 0, "skipped": 0}}
    assert "6 test(s) are not accounted for" in render_markdown_report(report)


def test_requirement_documents_section() -> None:
    markdown = render_markdown_report(REPORT)
    assert "## Requirement Documents" in markdown
    assert "C02_brd.md" in markdown and "31 requirement(s)" in markdown


def test_fuzz_section_reports_the_campaign_behind_reliability() -> None:
    markdown = render_markdown_report(REPORT)
    assert "## Fuzz & Error Handling" in markdown
    assert "Robustness: 9" in markdown
    assert "Unhandled crash: 40" in markdown


def test_missing_fuzz_campaign_says_so() -> None:
    markdown = render_markdown_report({**REPORT, "fuzz": None})
    assert "No fuzz campaign has been run" in markdown


def test_provenance_and_limitations_are_kept() -> None:
    """Dropping these made the report read more certain than the analysis actually is."""
    markdown = render_markdown_report(REPORT)
    assert "## Analysis Provenance" in markdown
    assert "part2-deterministic-v2" in markdown
    assert "Requirement matching: unavailable_fallback" in markdown
    assert "## Limitations" in markdown
    assert "without an AI provider" in markdown


def test_a_campaign_newer_than_the_evaluation_is_flagged() -> None:
    """Otherwise the report prints a robustness figure above 'no campaign has been run'."""
    report = {**REPORT, "fuzz": {**REPORT["fuzz"], "reflected_in_scores": False}}
    markdown = render_markdown_report(report)
    assert "does not include it yet" in markdown

    reflected = {**REPORT, "fuzz": {**REPORT["fuzz"], "reflected_in_scores": True}}
    assert "does not include it yet" not in render_markdown_report(reflected)
