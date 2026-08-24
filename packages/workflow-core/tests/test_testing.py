from __future__ import annotations

from pathlib import Path

from workflow_core.canonical.models import Edge, Node, NodeType, SourceFormat, Workflow
from workflow_core.cli import main
from workflow_core.evaluation.requirements import DeterministicRequirementExtractor
from workflow_core.testing import (
    AssertionEngine,
    AssertionType,
    CoverageCalculator,
    DeterministicTestGenerator,
    FailureInjection,
    FailureType,
    WorkflowAssertion,
    WorkflowSimulator,
    WorkflowTest,
    WorkflowTestRunner,
)

ROOT = Path(__file__).resolve().parents[3]


def branching_workflow() -> Workflow:
    return Workflow(
        id="wf_test",
        name="Invoice approval",
        source_format=SourceFormat.GENERIC_JSON,
        source_prompt="Approve invoices over $10,000 before saving to SAP.",
        nodes=[
            Node(id="start", name="Invoice received", type=NodeType.TRIGGER),
            Node(id="check", name="Amount check", type=NodeType.CONDITION),
            Node(id="approval", name="Human approval", type=NodeType.HUMAN_APPROVAL),
            Node(id="sap", name="Save to SAP", type=NodeType.EXTERNAL_API, provider="sap", configuration={"retries": 2}),
            Node(id="end", name="Done", type=NodeType.END),
        ],
        edges=[
            Edge(id="e1", source="start", target="check"),
            Edge(id="e2", source="check", target="approval", condition="amount > 10000"),
            Edge(id="e3", source="check", target="sap", label="default"),
            Edge(id="e4", source="approval", target="sap", condition="approved == true"),
            Edge(id="e5", source="sap", target="end"),
        ],
    )


def test_simulator_follows_condition_branch_and_requests_approval() -> None:
    workflow = branching_workflow()
    test = WorkflowTest(
        name="High amount approval",
        description="High amount invoices require approval.",
        input_data={"amount": 15000, "approved": True},
        assertions=[
            WorkflowAssertion(type=AssertionType.NODE_EXECUTED, target="approval"),
            WorkflowAssertion(type=AssertionType.APPROVAL_REQUESTED, target="approval"),
        ],
    )
    result = WorkflowSimulator().simulate(workflow, test)
    assertions = AssertionEngine().evaluate(test, result)
    assert result.execution_order == ["start", "check", "approval", "sap", "end"]
    assert result.approval_requests == ["approval"]
    assert all(item.passed for item in assertions)


def test_failure_injection_records_retries_and_failure() -> None:
    workflow = branching_workflow()
    test = WorkflowTest(
        name="SAP timeout",
        description="SAP timeout is injected.",
        input_data={"amount": 100, "approved": True},
        failure_injections=[FailureInjection(node_id="sap", failure_type=FailureType.TIMEOUT)],
        assertions=[
            WorkflowAssertion(type=AssertionType.ERROR_OCCURRED, expected=True),
            WorkflowAssertion(type=AssertionType.RETRY_COUNT, target="sap", expected=2),
        ],
    )
    run = WorkflowTestRunner().run(workflow, test)
    assert run.status == "ERROR"
    assert run.simulation.retries["sap"] == 2
    assert any("timeout" in failure.lower() for failure in run.failures)


def test_generation_creates_branch_edge_case_failure_and_requirement_tests() -> None:
    workflow = branching_workflow()
    spec = DeterministicRequirementExtractor().extract(workflow.source_prompt or "")
    result = DeterministicTestGenerator().generate(workflow, spec)
    names = {test.name for test in result.tests}
    tags = {tag for test in result.tests for tag in test.tags}
    assert "Happy path" in names
    assert "Branch: check to approval" in names
    assert "Boundary values" in names
    assert "failure_injection" in tags
    assert any(test.linked_requirement_id for test in result.tests)


def test_workflow_coverage_is_not_source_code_coverage() -> None:
    workflow = branching_workflow()
    tests = DeterministicTestGenerator().generate(workflow).tests[:2]
    runner = WorkflowTestRunner()
    runs = []
    for test in tests:
        runs.append(runner.run(workflow, test, all_tests=tests, prior_runs=runs))
    coverage = CoverageCalculator().calculate(workflow, runs, tests)
    assert coverage.node_coverage > 0
    assert coverage.edge_coverage > 0
    assert "nodes" in coverage.calculation


def test_cli_validate_and_test_commands_emit_exit_codes(capsys) -> None:
    valid = ROOT / "examples" / "json" / "valid-workflow.json"
    malformed = ROOT / "examples" / "json" / "malformed.json"
    assert main(["validate", str(valid)]) == 0
    assert "structural_quality_score" in capsys.readouterr().out
    assert main(["validate", str(malformed)]) == 2
    assert main(["test", str(valid), "--json"]) == 1
