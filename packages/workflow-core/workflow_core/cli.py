from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from workflow_core.canonical.models import SourceType
from workflow_core.evaluation import SemanticEvaluationEngine
from workflow_core.parsers.errors import WorkflowParseError
from workflow_core.parsers.registry import default_parser_registry
from workflow_core.testing import DeterministicTestGenerator, WorkflowTestRunner
from workflow_core.validation.engine import ValidationEngine


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="workflowguard", description="WorkflowGuard workflow QA CLI")
    subcommands = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "evaluate", "test"):
        command_parser = subcommands.add_parser(command)
        command_parser.add_argument("file", type=Path)
        command_parser.add_argument("--prompt", default=None)
        command_parser.add_argument("--source-type", default=SourceType.UNKNOWN.value)
        command_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    try:
        parsed = default_parser_registry().parse(
            args.file.name,
            args.file.read_bytes(),
            SourceType(args.source_type),
            args.prompt,
            None,
        )
    except (OSError, WorkflowParseError, ValueError) as exc:
        _emit(args.json, {"status": "ERROR", "error": str(exc)})
        return 2

    workflow = parsed.workflow
    validation = ValidationEngine().validate(workflow)
    if args.command == "validate":
        payload = {
            "status": "PASSED" if not _has_errors(validation.findings) else "FAILED",
            "structural_quality_score": validation.structural_quality_score,
            "findings": [finding.model_dump(mode="json") for finding in validation.findings],
        }
        _emit(args.json, payload)
        return 1 if _has_errors(validation.findings) else 0

    if args.command == "evaluate":
        result = SemanticEvaluationEngine().evaluate(
            workflow,
            structural_score=round(validation.structural_quality_score),
            validation_findings=validation.findings,
        )
        payload = {
            "status": result.status,
            "overall_score": result.overall_score,
            "dimension_scores": [score.model_dump(mode="json") for score in result.dimension_scores],
            "findings": [finding.model_dump(mode="json") for finding in result.findings],
        }
        _emit(args.json, payload)
        return 1 if result.overall_score < 70 else 0

    generation = DeterministicTestGenerator().generate(workflow, None)
    runner = WorkflowTestRunner()
    runs = []
    for test in generation.tests:
        run = runner.run(workflow, test, all_tests=generation.tests, prior_runs=runs)
        runs.append(run)
    failed = [run for run in runs if run.status != "PASSED"]
    coverage = runs[-1].coverage if runs else None
    payload = {
        "status": "PASSED" if not failed else "FAILED",
        "tests": len(runs),
        "passed": len(runs) - len(failed),
        "failed": len(failed),
        "overall_coverage": coverage.overall_coverage if coverage else 0,
        "runs": [run.model_dump(mode="json") for run in runs],
    }
    _emit(args.json, payload)
    return 1 if failed else 0


def _has_errors(findings) -> bool:
    return any(str(finding.severity) in {"ERROR", "CRITICAL"} for finding in findings)


def _emit(as_json: bool, payload: dict) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Status: {payload.get('status')}")
        for key in ("structural_quality_score", "overall_score", "tests", "passed", "failed", "overall_coverage"):
            if key in payload:
                print(f"{key}: {payload[key]}")
        if payload.get("error"):
            print(f"error: {payload['error']}")


if __name__ == "__main__":
    sys.exit(main())
