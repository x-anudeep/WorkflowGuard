from __future__ import annotations

import html
import re
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
    passed = tests.get("passed", 0)
    failed = tests.get("failed", 0)
    # Errored and skipped tests were omitted, so the line did not add up to the total and a
    # reader either did the arithmetic and lost 15 tests, or did not and overrated the suite.
    # An errored test could not run at all, which is worse than a failing one, not incidental.
    errored = tests.get("error", 0)
    skipped = tests.get("skipped", 0)
    coverage = tests.get("latest_coverage", tests.get("overall_coverage", 0))
    lines.append(
        f"- Total: {total_tests}; Passed: {passed}; Failed: {failed}; "
        f"Errored: {errored}; Skipped: {skipped}; Coverage: {coverage}%"
    )
    accounted = passed + failed + errored + skipped
    if total_tests and accounted != total_tests:
        lines.append(f"- Note: {total_tests - accounted} test(s) are not accounted for by any status.")
    documents = report.get("requirement_documents") or []
    if documents:
        lines.extend(["", "## Requirement Documents"])
        lines.extend(
            f"- `{document.get('kind', 'doc')}` {document.get('filename')}: "
            f"{document.get('clause_count', 0)} requirement(s)"
            for document in documents
        )

    fuzz = report.get("fuzz")
    lines.extend(["", "## Fuzz & Error Handling"])
    if not fuzz:
        lines.append("- No fuzz campaign has been run, so reliability reflects declared error handling only.")
    else:
        lines.append(
            f"- Robustness: {fuzz.get('robustness_score')} from {fuzz.get('exercised_cases', 0)} "
            f"exercised case(s) of {fuzz.get('total_cases', 0)} (seed `{fuzz.get('seed')}`)"
        )
        lines.append(
            f"- Handled: {fuzz.get('handled', 0)}; Unhandled crash: {fuzz.get('unhandled_crash', 0)}; "
            f"Silent success: {fuzz.get('silent_success', 0)}; Hung: {fuzz.get('hung', 0)}; "
            f"Not triggered: {fuzz.get('not_triggered', 0)}"
        )
        if fuzz.get("reflected_in_scores") is False:
            lines.append(
                "- Note: this campaign ran after the evaluation above, so the reliability score "
                "does not include it yet. Re-run the evaluation to fold it in."
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

    ai = report.get("ai") or {}
    metadata = ai.get("metadata") or {}
    if ai.get("provider") or metadata or ai.get("evaluator_version"):
        lines.extend(["", "## Analysis Provenance"])
        lines.append(f"- Evaluator: `{ai.get('evaluator_version', 'unknown')}`")
        lines.append(
            f"- AI provider: {ai.get('provider') or 'none'}"
            + (f" (`{ai['model']}`)" if ai.get("model") else "")
        )
        if metadata.get("ai_status"):
            lines.append(f"- Requirement extraction: {metadata['ai_status']}")
        if metadata.get("match_status"):
            lines.append(f"- Requirement matching: {metadata['match_status']}")

    limitations = report.get("limitations") or []
    if limitations:
        # These qualify every number above; dropping them made the report read more certain
        # than the analysis actually is.
        lines.extend(["", "## Limitations"])
        lines.extend(f"- {limitation}" for limitation in limitations)

    return "\n".join(lines) + "\n"


def _append_findings(lines: list[str], findings: list[dict[str, Any]]) -> None:
    if not findings:
        lines.append("- None recorded.")
        return
    lines.extend(
        f"- {finding.get('severity', 'INFO')} `{finding.get('rule_id')}` {finding.get('title')}: {finding.get('message')}"
        for finding in findings
    )


#: `**bold**` and `` `code` ``, applied after escaping so the markers survive but content does not
#: get to inject markup. Report text includes uploaded workflow names and finding messages, so
#: escaping is a correctness *and* safety requirement.
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`]+)`")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^[-*]\s+(.*)$")

_STYLE = """
  :root { color-scheme: light dark; }
  body { font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         margin: 0 auto; padding: 2rem 1.25rem; max-width: 60rem; }
  h1 { font-size: 1.6rem; margin: 0 0 1rem; }
  h2 { font-size: 1.2rem; margin: 2rem 0 .5rem; padding-bottom: .3rem;
       border-bottom: 1px solid currentColor; }
  h3 { font-size: 1.03rem; margin: 1.4rem 0 .4rem; }
  ul { margin: .4rem 0 .9rem; padding-left: 1.3rem; }
  li { margin: .18rem 0; }
  code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .88em;
         padding: .1em .35em; border: 1px solid rgba(128,128,128,.35); border-radius: 3px; }
  @media print { body { max-width: none; padding: 0; } h2 { break-after: avoid; } }
"""


def render_html_report(report: dict[str, Any]) -> str:
    """Render the report as standalone HTML.

    The previous one-liner wrapped every markdown line in ``<p>`` and turned anything falsy
    into ``<h1></h1>``, so blank lines became empty headings, every ``##`` collapsed to ``h1``,
    list items kept their literal ``-``, and backticks and ``**`` were shown as typed. It also
    interpolated finding text straight into markup without escaping.
    """
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{html.escape(_title(report))}</title>\n"
        f"<style>{_STYLE}</style>\n"
        "</head>\n<body>\n"
        f"{markdown_to_html(render_markdown_report(report))}\n"
        "</body>\n</html>\n"
    )


def markdown_to_html(markdown: str) -> str:
    """Convert the subset of markdown this report actually emits.

    Deliberately not a general markdown implementation - headings, bullet lists, bold and
    inline code are the whole vocabulary of `render_markdown_report`, and a dependency for
    that would be disproportionate.
    """
    out: list[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if not line.strip():
            close_list()
            continue

        heading = _HEADING.match(line)
        if heading:
            close_list()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue

        bullet = _BULLET.match(line)
        if bullet:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(bullet.group(1))}</li>")
            continue

        close_list()
        out.append(f"<p>{_inline(line)}</p>")

    close_list()
    return "\n".join(out)


def _inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = _CODE.sub(r"<code>\1</code>", escaped)
    return _BOLD.sub(r"<strong>\1</strong>", escaped)


def _title(report: dict[str, Any]) -> str:
    name = (report.get("workflow") or {}).get("name") or "Workflow"
    return f"WorkflowGuard Report: {name}"
