"""Compiling canonical workflows to n8n.

These run offline against the emitted JSON. They are the guard on the two things the rest of
WorkflowGuard depends on after execution moves to n8n: that every canonical node and edge can
be recovered from what n8n reports, and that anything n8n cannot express faithfully says so
rather than passing silently as a measurement.

The emitted JSON was validated against a live n8n 2.38.7 during step 3 - every example in
`examples/` created, published, executed and read back with no unmapped nodes.
"""

from pathlib import Path

import pytest

from workflow_core.canonical.models import (
    Edge,
    Node,
    NodeType,
    SourceFormat,
    SourceType,
    Workflow,
)
from workflow_core.emitters.n8n import N8nEmitter
from workflow_core.emitters.n8n.emitter import INPUT_NODE_NAME, TRIGGER_NODE_NAME
from workflow_core.parsers.registry import default_parser_registry


def _workflow(nodes, edges, name="Test") -> Workflow:
    return Workflow(
        name=name,
        source_format=SourceFormat.GENERIC_JSON,
        source_type=SourceType.HUMAN,
        nodes=nodes,
        edges=edges,
    )


def _emit(workflow, **kwargs):
    return N8nEmitter(mock_base_url="http://mock.test/mock").emit(workflow, run_token="t", **kwargs)


def _node_named(emitted, name):
    return next(n for n in emitted.workflow_json["nodes"] if n["name"] == name)


def _branching() -> Workflow:
    """start -> gate -> (high | normal), gate is a canonical CONDITION node."""
    return _workflow(
        nodes=[
            Node(id="start", name="Start", type=NodeType.TRIGGER),
            Node(id="gate", name="Gate", type=NodeType.CONDITION),
            Node(id="high", name="High", type=NodeType.ACTION),
            Node(id="normal", name="Normal", type=NodeType.ACTION),
        ],
        edges=[
            Edge(id="e_start", source="start", target="gate"),
            Edge(id="e_high", source="gate", target="high", condition="amount > 1000", label="high"),
            Edge(id="e_normal", source="gate", target="normal", condition="amount <= 1000", label="normal"),
        ],
    )


class TestIdentityIsRecoverable:
    """Everything must translate back, or coverage and assertions break."""

    def test_every_canonical_node_maps_to_an_n8n_node(self):
        workflow = _branching()
        emitted = _emit(workflow)
        for node in workflow.nodes:
            n8n_name = emitted.nodes.canonical_to_n8n[node.id]
            assert emitted.nodes.canonical(n8n_name) == node.id

    def test_injected_nodes_are_marked_synthetic(self):
        """They have no canonical origin; counting them would push node coverage over 100%."""
        emitted = _emit(_branching())
        assert emitted.nodes.is_synthetic(TRIGGER_NODE_NAME)
        assert emitted.nodes.is_synthetic(INPUT_NODE_NAME)
        assert emitted.nodes.canonical(TRIGGER_NODE_NAME) is None

    def test_every_emitted_n8n_node_is_either_canonical_or_synthetic(self):
        emitted = _emit(_branching())
        for node in emitted.workflow_json["nodes"]:
            name = node["name"]
            assert emitted.nodes.canonical(name) or emitted.nodes.is_synthetic(name), name

    def test_each_branch_output_resolves_to_its_canonical_edge(self):
        emitted = _emit(_branching())
        gate = emitted.nodes.canonical_to_n8n["gate"]
        recovered = {emitted.edges.edge_for(gate, 0), emitted.edges.edge_for(gate, 1)}
        assert recovered == {"e_high", "e_normal"}

    def test_emission_is_deterministic(self):
        """Golden-file tests and diffing two runs both depend on this."""
        workflow = _branching()
        assert _emit(workflow).workflow_json == _emit(workflow).workflow_json


class TestRouting:
    def test_single_condition_becomes_an_if(self):
        workflow = _workflow(
            nodes=[
                Node(id="start", name="Start", type=NodeType.TRIGGER),
                Node(id="gate", name="Gate", type=NodeType.CONDITION),
                Node(id="yes", name="Yes", type=NodeType.ACTION),
                Node(id="no", name="No", type=NodeType.ACTION),
            ],
            edges=[
                Edge(id="e0", source="start", target="gate"),
                Edge(id="e_yes", source="gate", target="yes", condition="amount > 10"),
                Edge(id="e_no", source="gate", target="no", label="else"),
            ],
        )
        emitted = _emit(workflow)
        assert _node_named(emitted, "Gate")["type"] == "n8n-nodes-base.if"
        assert emitted.edges.edge_for("Gate", 0) == "e_yes"
        assert emitted.edges.edge_for("Gate", 1) == "e_no"

    def test_multiple_conditions_become_a_switch(self):
        emitted = _emit(_branching())
        assert _node_named(emitted, "Gate")["type"] == "n8n-nodes-base.switch"

    def test_a_non_gateway_that_must_branch_gets_a_synthetic_router(self):
        """An ordinary n8n node has one output, so the branch needs somewhere else to live."""
        workflow = _workflow(
            nodes=[
                Node(id="start", name="Start", type=NodeType.TRIGGER),
                Node(id="approve", name="Approve", type=NodeType.HUMAN_APPROVAL),
                Node(id="after", name="After", type=NodeType.ACTION),
            ],
            edges=[
                Edge(id="e0", source="start", target="approve"),
                Edge(id="e1", source="approve", target="after", condition="approved == true"),
            ],
        )
        emitted = _emit(workflow)
        routers = [n for n in emitted.nodes.synthetic if "Router" in n]
        assert len(routers) == 1
        assert _node_named(emitted, routers[0])["type"] == "n8n-nodes-base.if"
        assert emitted.edges.edge_for(routers[0], 0) == "e1"

    def test_the_canonical_node_keeps_its_identity_when_it_is_the_gateway(self):
        """A CONDITION node becomes the IF in place, so it still appears in execution_order."""
        emitted = _emit(_branching())
        assert emitted.nodes.canonical("Gate") == "gate"
        assert not emitted.nodes.is_synthetic("Gate")

    def test_start_nodes_hang_off_the_input_lift_not_the_webhook(self):
        """The webhook nests the payload under $json.body; the lift flattens it.

        Without it every `$json.<field>` reads undefined and every condition is silently false.
        """
        emitted = _emit(_branching())
        main = emitted.workflow_json["connections"][INPUT_NODE_NAME]["main"][0]
        assert [t["node"] for t in main] == ["Start"]


class TestFailureHandling:
    def _with_failure_edge(self) -> Workflow:
        return _workflow(
            nodes=[
                Node(id="start", name="Start", type=NodeType.TRIGGER),
                Node(id="call", name="Call", type=NodeType.EXTERNAL_API),
                Node(id="ok", name="Ok", type=NodeType.ACTION),
                Node(id="recover", name="Recover", type=NodeType.ACTION),
            ],
            edges=[
                Edge(id="e0", source="start", target="call"),
                Edge(id="e_ok", source="call", target="ok", label="success"),
                Edge(id="e_fail", source="call", target="recover", label="failure path"),
            ],
        )

    def test_failure_edge_becomes_the_error_output(self):
        emitted = _emit(self._with_failure_edge())
        assert _node_named(emitted, "Call")["onError"] == "continueErrorOutput"
        assert emitted.error_output_index["call"] == 1
        assert emitted.edges.edge_for("Call", 1) == "e_fail"
        assert emitted.edges.edge_for("Call", 0) == "e_ok"

    def test_error_output_index_is_recorded_for_the_result_mapper(self):
        """Failure is only detectable as an item on the error output.

        Under `continueErrorOutput` a failing node still reports `executionStatus: "success"`,
        verified against n8n 2.38.7 - so the mapper needs to know which output means failure.
        """
        emitted = _emit(self._with_failure_edge())
        assert emitted.error_output_index == {"call": 1}

    def test_propagate_failures_keeps_the_run_going(self):
        emitted = _emit(_branching(), propagate_failures=True)
        assert _node_named(emitted, "High")["onError"] == "continueRegularOutput"

    def test_a_declared_error_path_wins_over_propagation(self):
        emitted = _emit(self._with_failure_edge(), propagate_failures=True)
        assert _node_named(emitted, "Call")["onError"] == "continueErrorOutput"

    def test_propagation_is_off_by_default(self):
        emitted = _emit(_branching())
        assert "onError" not in _node_named(emitted, "High")


class TestNodeBodies:
    def test_integration_nodes_are_redirected_at_the_mock_server(self):
        workflow = _workflow(
            nodes=[
                Node(id="start", name="Start", type=NodeType.TRIGGER),
                Node(id="db", name="Db", type=NodeType.DATABASE),
            ],
            edges=[Edge(id="e0", source="start", target="db")],
        )
        emitted = _emit(workflow)
        node = _node_named(emitted, "Db")
        assert node["type"] == "n8n-nodes-base.httpRequest"
        assert node["parameters"]["url"] == "http://mock.test/mock/t/db"
        assert emitted.mocked_nodes == {"db"}

    def test_approval_is_shimmed_and_declared(self):
        workflow = _workflow(
            nodes=[
                Node(id="start", name="Start", type=NodeType.TRIGGER),
                Node(id="ap", name="Ap", type=NodeType.HUMAN_APPROVAL),
            ],
            edges=[Edge(id="e0", source="start", target="ap")],
        )
        emitted = _emit(workflow)
        assert emitted.nodes.approval_nodes == {"ap"}
        assert any("auto-answered" in w for w in emitted.warnings)

    def test_unmodelled_node_bodies_warn_rather_than_pass_silently(self):
        workflow = _workflow(
            nodes=[
                Node(id="start", name="Start", type=NodeType.TRIGGER),
                Node(id="act", name="Act", type=NodeType.ACTION, configuration={"fields": ["a"]}),
            ],
            edges=[Edge(id="e0", source="start", target="act")],
        )
        emitted = _emit(workflow)
        assert any("'act'" in w and "pass-through" in w for w in emitted.warnings)

    def test_canonical_retries_become_n8n_retries(self):
        workflow = _workflow(
            nodes=[
                Node(id="start", name="Start", type=NodeType.TRIGGER),
                Node(id="api", name="Api", type=NodeType.EXTERNAL_API, configuration={"retry": 2}),
            ],
            edges=[Edge(id="e0", source="start", target="api")],
        )
        node = _node_named(_emit(workflow), "Api")
        assert node["retryOnFail"] is True
        assert node["maxTries"] == 3


class TestSafety:
    def test_never_emits_evaluation_nodes(self):
        """n8n Community caps `workflowsHavingEvaluations` at 0; either node fails publish."""
        emitted = _emit(_branching())
        types = {n["type"] for n in emitted.workflow_json["nodes"]}
        assert not {t for t in types if "evaluation" in t.lower()}

    def test_dangling_edge_is_warned_and_dropped(self):
        """n8n rejects a whole workflow that references a node that does not exist."""
        workflow = _workflow(
            nodes=[Node(id="start", name="Start", type=NodeType.TRIGGER)],
            edges=[Edge(id="e_bad", source="start", target="ghost")],
        )
        emitted = _emit(workflow)
        assert any("ghost" in w for w in emitted.warnings)
        targets = [
            target["node"]
            for conn in emitted.workflow_json["connections"].values()
            for output in conn["main"]
            for target in output
        ]
        assert "ghost" not in targets

    def test_node_names_are_unique_even_when_canonical_names_collide(self):
        workflow = _workflow(
            nodes=[
                Node(id="a", name="Same", type=NodeType.ACTION),
                Node(id="b", name="Same", type=NodeType.ACTION),
            ],
            edges=[],
        )
        emitted = _emit(workflow)
        names = [n["name"] for n in emitted.workflow_json["nodes"]]
        assert len(names) == len(set(names))
        assert emitted.nodes.canonical_to_n8n["a"] != emitted.nodes.canonical_to_n8n["b"]

    def test_webhook_path_is_namespaced_by_run_token(self):
        """n8n returns 409 on publish when two workflows claim the same path."""
        emitted = _emit(_branching())
        assert emitted.webhook_path == "wg-t"
        assert _node_named(emitted, TRIGGER_NODE_NAME)["parameters"]["path"] == "wg-t"


class TestRealExamples:
    @pytest.mark.parametrize(
        "path",
        [
            "examples/demo/correct-invoice-workflow.json",
            "examples/json/valid-workflow.json",
            "examples/bpmn/valid-workflow.bpmn",
            "examples/n8n/valid-workflow.json",
        ],
    )
    def test_examples_emit_with_complete_maps(self, path):
        source = Path(path)
        workflow = default_parser_registry().parse(source.name, source.read_bytes()).workflow
        emitted = _emit(workflow)

        assert set(emitted.nodes.canonical_to_n8n) == {n.id for n in workflow.nodes}
        for node in emitted.workflow_json["nodes"]:
            assert emitted.nodes.canonical(node["name"]) or emitted.nodes.is_synthetic(node["name"])

        emitted_edges = set(emitted.edges.by_output.values())
        reachable = {e.id for e in workflow.edges if e.target in {n.id for n in workflow.nodes}}
        assert emitted_edges <= reachable
