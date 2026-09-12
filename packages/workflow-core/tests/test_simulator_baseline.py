"""The recorded behaviour of every example workflow, before execution moves to n8n.

This is the differential gate. `fixtures/simulator-baseline/` holds what the in-process
simulator produced for the generated suite of each example. Once the simulator is gone, the
same workflows run through n8n and are compared against these files, and **every difference has
to be explained in writing** as either a simulator inaccuracy now fixed or an emitter bug.

That explanation is the acceptance criterion for the whole migration. Coverage feeds the
overall evaluation score, so "the numbers moved and nobody checked why" would silently restate
the quality of every workflow in the system.

The simulator is gone, so reproducing a baseline now requires a live n8n; that test is marked
`integration` and skips without one. The baseline files themselves stay exactly as recorded -
they are the thing being compared against, and regenerating them with the new engine would
destroy the comparison rather than perform it.

Never "fix" a failure here by regenerating. Read the diff, decide for each line whether it is a
simulator inaccuracy now corrected or an emitter bug, and write that down.
"""

import pytest
from baseline_support import (
    EXAMPLE_WORKFLOWS,
    baseline_path,
    diff_snapshots,
    load_baseline,
    snapshot,
)

from workflow_core.testing import WorkflowTestRunner


@pytest.mark.parametrize("example", EXAMPLE_WORKFLOWS)
def test_a_baseline_exists_for_every_example(example):
    """A missing baseline means that workflow has nothing to be compared against later."""
    assert baseline_path(example).exists(), (
        f"No baseline for {example}. Regenerate with "
        f"`python packages/workflow-core/tests/baseline_support.py`."
    )


@pytest.mark.integration
@pytest.mark.parametrize("example", EXAMPLE_WORKFLOWS)
def test_n8n_reproduces_the_baseline(example, engine):
    """The differential gate: real execution against what the simulator recorded."""
    differences = diff_snapshots(
        load_baseline(example), snapshot(example, WorkflowTestRunner(engine))
    )
    assert not differences, (
        "n8n diverged from the recorded simulator behaviour for {}.\n"
        "Each line must be explained as a simulator inaccuracy now fixed, or an emitter bug:\n  {}"
    ).format(example, "\n  ".join(differences))


def test_the_baseline_captures_the_fields_the_comparison_needs():
    """Guard on the snapshot shape itself, not on any one workflow's numbers."""
    recorded = load_baseline("examples/demo/correct-invoice-workflow.json")
    assert recorded["test_count"] > 0
    for name, run in recorded["tests"].items():
        assert set(run) == {
            "approval_requests",
            "branch_decisions",
            "coverage",
            "executed_edges",
            "execution_order",
            "failures",
            "retries",
            "status",
        }, name


def test_the_diff_reports_each_difference_separately():
    """A single failed equality assertion would be useless for a divergence review."""
    recorded = {"tests": {"a": {"status": "PASSED", "execution_order": ["x"]}}}
    actual = {"tests": {"a": {"status": "ERROR", "execution_order": ["y"]}, "b": {}}}
    differences = diff_snapshots(recorded, actual)
    assert len(differences) == 3
    assert any("b: new test" in d for d in differences)
    assert any("a.status" in d for d in differences)
