from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

from workflow_core.canonical.models import SourceType
from workflow_core.comparison import VersionComparisonEngine
from workflow_core.costing import CostEstimator, CostOptimizationEngine, CostScenario
from workflow_core.emitters.n8n import N8nEmitter
from workflow_core.evaluation import SemanticEvaluationEngine
from workflow_core.execution import N8nClient, N8nExecutionEngine, serve_mocks
from workflow_core.fuzzing import DEFAULT_MAX_CASES, DEFAULT_SEED, FuzzEngine
from workflow_core.parsers.errors import WorkflowParseError
from workflow_core.parsers.registry import default_parser_registry
from workflow_core.quality import QualityGateEngine
from workflow_core.reporting import render_markdown_report
from workflow_core.testing import DeterministicTestGenerator, WorkflowTestRunner
from workflow_core.validation.engine import ValidationEngine


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="workflowguard",
        description=(
            "WorkflowGuard workflow QA CLI. `test`, `fuzz`, `check` and `report` execute the "
            "workflow in n8n, so they need WORKFLOWGUARD_N8N_BASE_URL to point at a reachable "
            "instance and WORKFLOWGUARD_N8N_API_KEY to hold a key with the workflow:activate "
            "scope. Integration calls are redirected to mock endpoints this command serves "
            "itself, so nothing reaches a real service. `validate`, `evaluate`, `cost` and "
            "`compare` execute nothing and need no engine."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "evaluate", "fuzz", "test", "cost", "check", "report"):
        command_parser = subcommands.add_parser(command)
        command_parser.add_argument("file", type=Path)
        command_parser.add_argument("--prompt", default=None)
        command_parser.add_argument("--source-type", default=SourceType.UNKNOWN.value)
        command_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
        if command == "cost":
            command_parser.add_argument("--executions-day", type=int, default=100)
            command_parser.add_argument("--input-tokens", type=int, default=1000)
            command_parser.add_argument("--output-tokens", type=int, default=300)
            command_parser.add_argument("--retry-rate", type=float, default=0.05)
        if command == "fuzz":
            command_parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
            command_parser.add_argument("--max-cases", type=int, default=DEFAULT_MAX_CASES)
            command_parser.add_argument(
                "--min-robustness",
                type=int,
                default=70,
                help="Exit non-zero when measured robustness falls below this score.",
            )
        if command == "report":
            command_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    compare_parser = subcommands.add_parser("compare")
    compare_parser.add_argument("file_a", type=Path)
    compare_parser.add_argument("file_b", type=Path)
    compare_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    if args.command == "compare":
        try:
            before = _parse_file(args.file_a)
            after = _parse_file(args.file_b)
        except (OSError, WorkflowParseError, ValueError) as exc:
            _emit(args.json, {"status": "ERROR", "error": str(exc)})
            return 2
        before_cost = CostEstimator().estimate(before)
        after_cost = CostEstimator().estimate(after)
        comparison = VersionComparisonEngine().compare(
            before,
            after,
            cost_before=before_cost.cost_per_run,
            cost_after=after_cost.cost_per_run,
        )
        _emit(args.json, {"status": "completed", **comparison.model_dump(mode="json")})
        return 0

    try:
        parsed = default_parser_registry().parse(args.file.name, args.file.read_bytes(), SourceType(args.source_type), args.prompt, None)
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

    if args.command == "fuzz":
        with _engine(propagate_failures=True) as engine:
            report = FuzzEngine(engine).run(workflow, seed=args.seed, max_cases=args.max_cases)
        payload = {
            "robustness_score": report.robustness_score,
            "exercised_cases": report.exercised_cases,
            "total_cases": len(report.results),
            "seed": report.seed,
            "counts": report.counts,
            "findings": [finding.model_dump(mode="json") for finding in report.findings],
            "limitations": report.limitations,
        }
        _emit(args.json, payload)
        if report.exercised_cases == 0:
            # Nothing was measured. Failing the gate here would punish a workflow with no
            # external dependencies; passing it silently would hide a disconnected graph.
            # Report and let `validate` be the gate on graph structure.
            return 0
        return 1 if report.robustness_score < args.min_robustness else 0

    if args.command == "cost":
        scenario = CostScenario(
            executions_per_day=args.executions_day,
            average_input_tokens=args.input_tokens,
            average_output_tokens=args.output_tokens,
            failure_retry_rate=args.retry_rate,
        )
        estimate = CostEstimator().estimate(workflow, scenario)
        findings = CostOptimizationEngine().analyze(workflow, estimate)
        payload = {
            "status": "completed",
            "estimate": estimate.model_dump(mode="json"),
            "optimization_findings": [finding.model_dump(mode="json") for finding in findings],
        }
        _emit(args.json, payload)
        return 0

    generation = DeterministicTestGenerator().generate(workflow, None)
    runs = []
    with _engine() as engine:
        runner = WorkflowTestRunner(engine)
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
    if args.command in {"check", "report"}:
        evaluation = SemanticEvaluationEngine().evaluate(
            workflow,
            structural_score=round(validation.structural_quality_score),
            validation_findings=validation.findings,
        )
        dimensions = {str(score.dimension): score.score for score in evaluation.dimension_scores}
        estimate = CostEstimator().estimate(workflow)
        quality_gate = QualityGateEngine().evaluate(
            structural_score=validation.structural_quality_score,
            prompt_alignment_score=dimensions.get("prompt_alignment"),
            security_score=dimensions.get("security"),
            reliability_score=dimensions.get("reliability"),
            maintainability_score=dimensions.get("maintainability"),
            test_coverage=coverage.overall_coverage if coverage else 0,
            critical_test_failures=sum(1 for run in runs if run.status in {"FAILED", "ERROR"}),
            critical_security_findings=sum(
                1 for finding in evaluation.findings if str(finding.dimension) == "security" and str(finding.severity) == "CRITICAL"
            ),
        )
        report = {
            "workflow": {
                "id": workflow.id,
                "name": workflow.name,
                "version_id": workflow.metadata.get("version_id"),
                "source_format": str(workflow.source_format),
                "source_type": str(workflow.source_type),
            },
            "scores": {
                "overall": evaluation.overall_score,
                "structural": validation.structural_quality_score,
                "prompt_alignment": dimensions.get("prompt_alignment"),
                "security": dimensions.get("security"),
                "reliability": dimensions.get("reliability"),
                "maintainability": dimensions.get("maintainability"),
                "test_coverage": coverage.overall_coverage if coverage else 0,
            },
            "quality_gate": quality_gate.model_dump(mode="json"),
            "validation_findings": [finding.model_dump(mode="json") for finding in validation.findings],
            "evaluation_findings": [finding.model_dump(mode="json") for finding in evaluation.findings],
            "tests": payload,
            "cost": estimate.model_dump(mode="json"),
            "optimization_findings": [
                finding.model_dump(mode="json") for finding in CostOptimizationEngine().analyze(workflow, estimate)
            ],
        }
        if args.command == "report":
            if args.format == "json" or args.json:
                print(json.dumps(report, indent=2))
            else:
                print(render_markdown_report(report), end="")
            return 0
        _emit(args.json, {"status": quality_gate.status, "quality_gate": quality_gate.model_dump(mode="json"), **payload})
        return 0 if quality_gate.status == "PASS" else 1
    _emit(args.json, payload)
    return 1 if failed else 0


def _has_errors(findings) -> bool:
    return any(str(finding.severity) in {"ERROR", "CRITICAL"} for finding in findings)


@contextmanager
def _engine(*, propagate_failures: bool = False):
    """The execution engine, with its own mock endpoints, for the duration of the block.

    The CLI is the CI entry point, so it reads the same n8n variables the API does. It cannot
    reuse the API's mock endpoints, though: those live in a running FastAPI process, and there
    is not one here. Pointing emitted workflows at a URL with nothing behind it is how every
    integration call quietly failed to connect.

    Running tests now needs a reachable n8n. There is no in-process fallback, because reporting
    invented coverage to a pipeline is worse than failing loudly.
    """
    with serve_mocks() as (registry, mock_base_url):
        yield N8nExecutionEngine(
            N8nClient(
                os.environ.get("WORKFLOWGUARD_N8N_BASE_URL", "http://localhost:5678"),
                os.environ.get("WORKFLOWGUARD_N8N_API_KEY"),
            ),
            emitter=N8nEmitter(
                mock_base_url=os.environ.get("WORKFLOWGUARD_MOCK_BASE_URL") or mock_base_url
            ),
            mocks=registry,
            propagate_failures=propagate_failures,
        )


def _emit(as_json: bool, payload: dict) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Status: {payload.get('status')}")
        for key in (
            "structural_quality_score",
            "overall_score",
            "cost_per_run",
            "monthly_cost",
            "tests",
            "passed",
            "failed",
            "overall_coverage",
            "estimated_cost_delta",
        ):
            if key in payload:
                print(f"{key}: {payload[key]}")
        if "estimate" in payload:
            print(f"cost_per_run: {payload['estimate']['cost_per_run']}")
            print(f"monthly_cost: {payload['estimate']['monthly_cost']}")
        if payload.get("error"):
            print(f"error: {payload['error']}")


def _parse_file(path: Path):
    return default_parser_registry().parse(path.name, path.read_bytes(), SourceType.UNKNOWN, None, None).workflow


if __name__ == "__main__":
    sys.exit(main())
