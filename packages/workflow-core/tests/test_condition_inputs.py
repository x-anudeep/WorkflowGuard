"""Generated tests must be able to take the branches they were written to exercise.

Two defects made generated tests fail for reasons that said nothing about the workflow, and
because tests feed coverage and the quality gate, those failures were charged to its score.
"""

from workflow_core.analysis.reachability import satisfying_state
from workflow_core.canonical.models import (
    Edge,
    Node,
    NodeType,
    SourceFormat,
    SourceType,
    Workflow,
)
from workflow_core.testing.generator import DeterministicTestGenerator
from workflow_core.testing.runner import WorkflowTestRunner
from workflow_core.testing.simulator import WorkflowSimulator, evaluate_condition


def _branching_workflow() -> Workflow:
    """Start -> Check Plan -> (starter|professional) or (enterprise) -> End."""
    return Workflow(
        name="Onboarding",
        source_format=SourceFormat.GENERIC_JSON,
        source_type=SourceType.HUMAN,
        nodes=[
            Node(id="start", name="Signup", type=NodeType.TRIGGER),
            Node(id="check", name="Check Customer Plan Type", type=NodeType.CONDITION),
            Node(id="basic", name="Basic Setup", type=NodeType.ACTION),
            Node(id="ent", name="Enterprise Setup", type=NodeType.ACTION),
            Node(id="end", name="End", type=NodeType.END),
        ],
        edges=[
            Edge(id="e1", source="start", target="check"),
            Edge(
                id="e2",
                source="check",
                target="basic",
                condition='signupPayload.plan == "starter" || signupPayload.plan == "professional"',
            ),
            Edge(id="e3", source="check", target="ent", condition='signupPayload.plan == "enterprise"'),
            Edge(id="e4", source="basic", target="end"),
            Edge(id="e5", source="ent", target="end"),
        ],
    )


def test_or_conditions_evaluate() -> None:
    """The regression that mattered most.

    Without splitting on `||` first, the `==` split read `"starter" || plan == "professional"`
    as the right-hand literal, so every OR branch was false and the run dead-ended at the
    gateway - taking all downstream assertions down with it.
    """
    condition = 'signupPayload.plan == "starter" || signupPayload.plan == "professional"'
    assert evaluate_condition(condition, {"plan": "starter"}) is True
    assert evaluate_condition(condition, {"plan": "professional"}) is True
    assert evaluate_condition(condition, {"plan": "enterprise"}) is False


def test_and_conditions_evaluate() -> None:
    assert evaluate_condition("amount > 50 && amount < 200", {"amount": 100}) is True
    assert evaluate_condition("amount > 50 && amount < 200", {"amount": 400}) is False


def test_branch_inputs_come_from_the_condition_not_a_fixed_vocabulary() -> None:
    """The generator used to emit {"approved": True, "amount": 100} for every domain."""
    workflow = _branching_workflow()
    tests = DeterministicTestGenerator().generate(workflow).tests
    branch = [t for t in tests if t.name.startswith("Branch:")]
    assert branch

    values = {value for test in branch for value in test.input_data.values()}
    assert {"starter", "enterprise"} & values


def test_generated_branch_tests_actually_reach_their_branch() -> None:
    workflow = _branching_workflow()
    tests = DeterministicTestGenerator().generate(workflow).tests
    simulator = WorkflowSimulator()

    for test in (t for t in tests if t.name.startswith("Branch:")):
        executed = {e.node_id for e in simulator.simulate(workflow, test).node_executions}
        assert set(test.expected_path) <= executed, f"{test.name} never reached its branch"


def test_happy_path_walks_the_path_it_asserts() -> None:
    """The input has to satisfy the conditions on the edges `_primary_path` chose."""
    workflow = _branching_workflow()
    tests = DeterministicTestGenerator().generate(workflow).tests
    happy = next(t for t in tests if t.name == "Happy path")

    result = WorkflowTestRunner().run(workflow, happy)
    assert str(result.status) == "PASSED", result.failures


def test_satisfying_state_reads_the_field_names_the_simulator_reads() -> None:
    """Simulator state is flat - it resolves `a.b.c` by its last segment."""
    state = satisfying_state('signupPayload.plan == "enterprise"')
    assert evaluate_condition('signupPayload.plan == "enterprise"', state) is True
