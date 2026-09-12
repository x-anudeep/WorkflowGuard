"""What WG-GATE-TESTS gates on, and how it says so.

The rule claimed to check "critical tests" but counted anything HIGH *or* CRITICAL, and the
deterministic generator marked 86 of 93 tests HIGH - so it was really "no test may fail", 87 of
93 tests wide, reported as a bare number with no scale.
"""

from pathlib import Path

from workflow_core.canonical.models import SourceType
from workflow_core.parsers.registry import default_parser_registry
from workflow_core.quality import QualityGateConfig, QualityGateEngine
from workflow_core.testing.generator import DeterministicTestGenerator
from workflow_core.testing.models import TestImportance

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "examples"


def _gate_reason(**kwargs):
    result = QualityGateEngine(QualityGateConfig()).evaluate(**kwargs)
    return next(reason for reason in result.reasons if reason.rule_id == "WG-GATE-TESTS")


def test_the_reason_states_the_scale_not_a_bare_count() -> None:
    reason = _gate_reason(critical_test_failures=5, critical_test_total=33)
    assert reason.actual == "5 of 33 failed or errored"
    assert not reason.passed


def test_a_clean_run_passes() -> None:
    reason = _gate_reason(critical_test_failures=0, critical_test_total=33)
    assert reason.passed
    assert reason.actual == "0 of 33 failed or errored"


def test_importance_distinguishes_tests_again() -> None:
    """Gating on nearly every generated test made the level meaningless."""
    path = EXAMPLES / "json" / "valid-workflow.json"
    workflow = default_parser_registry().parse(
        path.name, path.read_bytes(), SourceType.UNKNOWN, None, "application/json"
    ).workflow
    tests = DeterministicTestGenerator().generate(workflow).tests

    gated = [t for t in tests if str(t.importance) in {"HIGH", "CRITICAL"}]
    assert gated, "something must still gate the release"
    assert len(gated) < len(tests) / 2, "importance carries no information if most tests are gated"

    # The happy path is the workflow's core purpose.
    happy = next(t for t in tests if t.name == "Happy path")
    assert happy.importance == TestImportance.CRITICAL

    # Failure injection is already scored by reliability and fuzzing; gating on it double-counts.
    injected = [t for t in tests if "failure_injection" in t.tags]
    assert injected
    assert all(t.importance == TestImportance.MEDIUM for t in injected)

    branch = [t for t in tests if "branch" in t.tags]
    assert all(t.importance == TestImportance.MEDIUM for t in branch)


def test_a_run_that_never_executed_does_not_report_coverage() -> None:
    """An unreachable engine must not be scored as a workflow with poor coverage.

    Coverage feeds both the quality gate and the TEST_COVERAGE evaluation dimension, so a
    number here would gate and score a workflow on a run that did not happen.
    """
    from workflow_core.canonical.models import Node, NodeType, SourceFormat, SourceType, Workflow
    from workflow_core.execution import N8nClient, N8nExecutionEngine
    from workflow_core.testing import WorkflowTest, WorkflowTestRunner

    workflow = Workflow(
        name="Unreachable engine",
        source_format=SourceFormat.GENERIC_JSON,
        source_type=SourceType.HUMAN,
        nodes=[Node(id="start", name="Start", type=NodeType.TRIGGER)],
    )
    # Nothing is listening, which is what a deployment without an engine looks like.
    engine = N8nExecutionEngine(N8nClient("http://127.0.0.1:59999"))
    run = WorkflowTestRunner(engine).run(workflow, WorkflowTest(name="t", description="d"))

    assert str(run.status) == "ERROR"
    assert run.coverage is None
    assert "Execution engine unavailable" in run.failures[0]
