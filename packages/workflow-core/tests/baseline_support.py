"""Building a comparable snapshot of how a workflow behaves when its tests are run.

This exists for the switch from the in-process simulator to real execution in n8n. Before the
simulator is deleted, every example workflow is run through it and the result recorded. After
the switch, the same workflows are run through n8n and compared against those recordings, and
**every difference has to be explained in writing** as either a simulator inaccuracy now fixed
or an emitter bug. Without the recording that comparison is impossible, because the simulator
will no longer exist to produce it.

What is recorded is deliberately control flow rather than payloads. Node and edge coverage,
which branch was taken, whether a run passed - these mean the same thing in both engines and
are what feeds `CoverageCalculator` and, since `ceb974b`, the overall evaluation score. Node
*outputs* do not compare meaningfully: the simulator invented `{"ok": true}` for an unmocked
integration where n8n returns whatever the mock server actually sent.

Test **names** key the snapshot, not ids - `WorkflowTest.id` defaults to a fresh uuid4, so ids
differ between two runs of the same generator while names are stable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from workflow_core.evaluation import DeterministicRequirementExtractor
from workflow_core.parsers.registry import default_parser_registry
from workflow_core.testing import DeterministicTestGenerator, WorkflowTestRunner

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE_DIR = Path(__file__).parent / "fixtures" / "simulator-baseline"

#: Every example that parses. The malformed ones are fixtures for parser errors and never
#: produce a workflow to run.
EXAMPLE_WORKFLOWS = [
    "examples/bpmn/cycle.bpmn",
    "examples/bpmn/invalid-connection.bpmn",
    "examples/bpmn/missing-terminal-node.bpmn",
    "examples/bpmn/orphan-node.bpmn",
    "examples/bpmn/valid-workflow.bpmn",
    "examples/demo/broken-ai-invoice-workflow.json",
    "examples/demo/correct-invoice-workflow.json",
    "examples/json/cycle.json",
    "examples/json/invalid-connection.json",
    "examples/json/missing-terminal-node.json",
    "examples/json/orphan-node.json",
    "examples/json/valid-workflow.json",
    "examples/n8n/cycle.json",
    "examples/n8n/invalid-connection.json",
    "examples/n8n/missing-terminal-node.json",
    "examples/n8n/orphan-node.json",
    "examples/n8n/valid-workflow.json",
]


def slug(example_path: str) -> str:
    """`examples/bpmn/valid-workflow.bpmn` -> `bpmn__valid-workflow`."""
    path = Path(example_path)
    return f"{path.parent.name}__{path.stem}"


def load_workflow(example_path: str):
    source = REPO_ROOT / example_path
    return default_parser_registry().parse(source.name, source.read_bytes()).workflow


def snapshot(example_path: str, runner: WorkflowTestRunner | None = None) -> dict[str, Any]:
    """Run the generated suite for one example and record how it behaved.

    `runner` is injectable so the same snapshot can later be produced by the n8n-backed runner
    and diffed against the recorded one.
    """
    workflow = load_workflow(example_path)
    generated = DeterministicTestGenerator().generate(
        workflow,
        DeterministicRequirementExtractor().extract(workflow.source_prompt)
        if workflow.source_prompt
        else None,
    )
    runner = runner or WorkflowTestRunner()

    prior: list[Any] = []
    results: dict[str, Any] = {}
    for test in generated.tests:
        run = runner.run(workflow, test, all_tests=generated.tests, prior_runs=prior)
        prior.append(run)
        results[test.name] = _run_snapshot(run)

    return {
        "example": example_path,
        "workflow": {
            "name": workflow.name,
            "source_format": str(workflow.source_format),
            "node_count": len(workflow.nodes),
            "edge_count": len(workflow.edges),
            "node_ids": sorted(node.id for node in workflow.nodes),
            "edge_ids": sorted(edge.id for edge in workflow.edges),
        },
        "test_count": len(generated.tests),
        "tests": results,
    }


def _run_snapshot(run) -> dict[str, Any]:
    simulation = run.simulation
    return {
        "status": str(run.status),
        # Order matters: a different order is a different traversal, not a cosmetic difference.
        "execution_order": list(simulation.execution_order),
        # Sorted: these feed coverage, which is a set operation, so ordering is noise here.
        "executed_edges": sorted(set(simulation.executed_edges)),
        "branch_decisions": dict(sorted(simulation.branch_decisions.items())),
        "approval_requests": sorted(set(simulation.approval_requests)),
        "retries": dict(sorted(simulation.retries.items())),
        # Text, not just a count: the wording differs between engines, but *which* node failed
        # and how many did is exactly what a divergence review needs to see.
        "failures": list(simulation.failures),
        "coverage": _coverage_snapshot(run.coverage),
    }


def _coverage_snapshot(coverage) -> dict[str, float] | None:
    if coverage is None:
        return None
    return {
        "node": coverage.node_coverage,
        "edge": coverage.edge_coverage,
        "branch": coverage.branch_coverage,
        "requirement": coverage.requirement_coverage,
        "overall": coverage.overall_coverage,
    }


def baseline_path(example_path: str) -> Path:
    return BASELINE_DIR / f"{slug(example_path)}.json"


def load_baseline(example_path: str) -> dict[str, Any]:
    return json.loads(baseline_path(example_path).read_text())


def write_baseline(example_path: str, data: dict[str, Any]) -> Path:
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    path = baseline_path(example_path)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return path


def diff_snapshots(recorded: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    """Human-readable differences between two snapshots of the same example.

    Returns one line per difference, so a divergence review has something to work through
    rather than a single failed equality assertion.
    """
    recorded_tests, actual_tests = recorded.get("tests", {}), actual.get("tests", {})

    differences = [
        f"{name}: present in baseline, missing now"
        for name in sorted(set(recorded_tests) - set(actual_tests))
    ]
    differences += [
        f"{name}: new test, not in baseline"
        for name in sorted(set(actual_tests) - set(recorded_tests))
    ]
    differences += [
        f"{name}.{field}: {recorded_tests[name].get(field)!r} -> {actual_tests[name].get(field)!r}"
        for name in sorted(set(recorded_tests) & set(actual_tests))
        for field in sorted(set(recorded_tests[name]) | set(actual_tests[name]))
        if recorded_tests[name].get(field) != actual_tests[name].get(field)
    ]
    return differences


def regenerate_all() -> list[Path]:
    """Rewrite every baseline file. Run deliberately, never as part of the suite."""
    return [write_baseline(example, snapshot(example)) for example in EXAMPLE_WORKFLOWS]


if __name__ == "__main__":
    for written in regenerate_all():
        print(f"wrote {written.relative_to(REPO_ROOT)}")
