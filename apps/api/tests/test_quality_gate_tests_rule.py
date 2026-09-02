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
