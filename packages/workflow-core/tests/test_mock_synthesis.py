"""Mocks that the workflow downstream of them can actually compute on.

The workflow in `_stock_alert` is the one that exposed this: a real upload whose `HighPriceAlert`
test could never pass, because the generated mock had no `price` for the code to read. It is kept
here as the acceptance test for the whole idea.
"""

import pytest

from workflow_core.canonical.models import (
    Edge,
    Node,
    NodeType,
    SourceFormat,
    SourceType,
    Workflow,
)
from workflow_core.testing import DeterministicTestGenerator
from workflow_core.testing.mock_synthesis import (
    code_derivations,
    required_fields,
    synthesise_mocks,
)


def _stock_alert() -> Workflow:
    """Get price -> compute isHigh from it -> branch on isHigh."""
    return Workflow(
        name="Stock alert",
        source_format=SourceFormat.QUBI,
        source_type=SourceType.HUMAN,
        nodes=[
            Node(id="start", name="Start", type=NodeType.TRIGGER, subtype="Start"),
            Node(id="price", name="Get Stock Price", type=NodeType.EXTERNAL_API, subtype="Http"),
            Node(
                id="check",
                name="Check Price Threshold",
                type=NodeType.ACTION,
                subtype="Code",
                configuration={
                    "language": "javascript",
                    "saveOutputAs": "priceCheck",
                    "code": "return { isHigh: input.price > 100 };",
                },
            ),
            Node(id="gate", name="Branch", type=NodeType.CONDITION, subtype="Branch"),
            Node(id="alert", name="Send Alert", type=NodeType.EXTERNAL_API, subtype="Http"),
            Node(id="quiet", name="No Alert", type=NodeType.ACTION, subtype="Assign"),
        ],
        edges=[
            Edge(id="e0", source="start", target="price"),
            Edge(id="e1", source="price", target="check"),
            Edge(id="e2", source="check", target="gate"),
            Edge(id="hi", source="gate", target="alert", condition="priceCheck.isHigh == true"),
            Edge(id="lo", source="gate", target="quiet", condition="priceCheck.isHigh == false"),
        ],
    )


def _mock_for(mocks, node_id):
    return next(m.response for m in mocks if m.node_id == node_id)


class TestReadingWhatTheWorkflowNeeds:
    def test_a_code_nodes_input_reads_are_required_of_the_upstream_mock(self):
        requirements = required_fields(_stock_alert())
        assert "price" in requirements["price"]

    def test_a_derivation_is_read_out_of_the_code(self):
        workflow = _stock_alert()
        node = next(n for n in workflow.nodes if n.id == "check")
        derivation = code_derivations(node)[0]
        assert derivation.produced_field == "isHigh"
        assert derivation.source_field == "price"
        assert derivation.operator == ">"

    def test_an_unreadable_body_yields_no_derivation_rather_than_a_wrong_one(self):
        node = Node(
            id="c",
            name="C",
            type=NodeType.ACTION,
            subtype="Code",
            configuration={"code": "const x = compute(items); return buildResult(x);"},
        )
        assert code_derivations(node) == []


class TestSteeringABranch:
    """The indirection that a bland mock could never satisfy."""

    def test_the_mock_is_solved_for_the_field_the_code_reads(self):
        """Solving the condition itself gives `isHigh`, which the code immediately overwrites."""
        workflow = _stock_alert()
        high = next(e for e in workflow.edges if e.id == "hi")
        mocks, warnings = synthesise_mocks(workflow, target_edge=high)
        assert _mock_for(mocks, "price")["price"] > 100
        assert not warnings

    def test_complementary_branches_get_different_mocks(self):
        """One shared response cannot satisfy both sides; that is the original bug."""
        workflow = _stock_alert()
        high = next(e for e in workflow.edges if e.id == "hi")
        low = next(e for e in workflow.edges if e.id == "lo")
        high_price = _mock_for(synthesise_mocks(workflow, target_edge=high)[0], "price")["price"]
        low_price = _mock_for(synthesise_mocks(workflow, target_edge=low)[0], "price")["price"]
        assert high_price > 100
        assert low_price <= 100

    def test_a_computed_field_is_never_supplied_by_the_mock(self):
        """Supplying it would mask whether the computation ran at all."""
        workflow = _stock_alert()
        high = next(e for e in workflow.edges if e.id == "hi")
        mocks, _ = synthesise_mocks(workflow, target_edge=high)
        assert "isHigh" not in _mock_for(mocks, "price")

    def test_a_condition_on_a_field_the_integration_supplies_is_solved_directly(self):
        workflow = Workflow(
            name="Direct",
            source_format=SourceFormat.GENERIC_JSON,
            source_type=SourceType.HUMAN,
            nodes=[
                Node(id="start", name="Start", type=NodeType.TRIGGER),
                Node(id="api", name="Api", type=NodeType.EXTERNAL_API),
                Node(id="gate", name="Gate", type=NodeType.CONDITION),
                Node(id="done", name="Done", type=NodeType.END),
            ],
            edges=[
                Edge(id="e0", source="start", target="api"),
                Edge(id="e1", source="api", target="gate"),
                Edge(id="e2", source="gate", target="done", condition="total > 500"),
            ],
        )
        edge = next(e for e in workflow.edges if e.id == "e2")
        mocks, _ = synthesise_mocks(workflow, target_edge=edge)
        assert _mock_for(mocks, "api")["total"] > 500


class TestUnsteerableBranches:
    """A branch whose field is computed in a way the generator cannot read."""

    @staticmethod
    def _opaque() -> Workflow:
        return Workflow(
            name="Opaque",
            source_format=SourceFormat.QUBI,
            source_type=SourceType.HUMAN,
            nodes=[
                Node(id="start", name="Start", type=NodeType.TRIGGER),
                Node(
                    id="calc",
                    name="Calc",
                    type=NodeType.ACTION,
                    subtype="Code",
                    configuration={
                        "language": "javascript",
                        # Produces `flag`, but nothing here says what decides it.
                        "code": "return { flag: classify(items) };",
                    },
                ),
                Node(id="gate", name="Gate", type=NodeType.CONDITION),
                Node(id="done", name="Done", type=NodeType.END),
            ],
            edges=[
                Edge(id="e0", source="start", target="calc"),
                Edge(id="e1", source="calc", target="gate"),
                Edge(id="e2", source="gate", target="done", condition="flag == true"),
            ],
        )

    def test_it_is_reported_rather_than_left_to_fail(self):
        workflow = self._opaque()
        edge = next(e for e in workflow.edges if e.id == "e2")
        _mocks, warnings = synthesise_mocks(workflow, target_edge=edge)
        assert warnings and "could not be steered" in warnings[0]

    def test_the_mock_does_not_pretend_to_supply_the_computed_field(self):
        """Supplying `flag` would look like steering while the code overwrites it."""
        workflow = self._opaque()
        edge = next(e for e in workflow.edges if e.id == "e2")
        mocks, _ = synthesise_mocks(workflow, target_edge=edge)
        assert all("flag" not in m.response for m in mocks)

    def test_such_a_test_is_generated_disabled_with_its_reason(self):
        """A red test nobody can make green trains people to ignore the suite."""
        result = DeterministicTestGenerator().generate(self._opaque())
        branch = next(t for t in result.tests if t.name.startswith("Branch:"))
        assert branch.enabled is False
        assert "could not be steered" in (branch.rationale or "")
        assert result.warnings


class TestTheWorkflowThatExposedThis:
    """`HighPriceAlert` must pass with a generated mock and no hand editing."""

    def test_both_branch_tests_are_generated_enabled_with_usable_mocks(self):
        result = DeterministicTestGenerator().generate(_stock_alert())
        branches = [t for t in result.tests if t.name.startswith("Branch:")]
        assert len(branches) == 2
        assert all(t.enabled for t in branches)
        prices = sorted(_mock_for(t.mocked_integrations, "price")["price"] for t in branches)
        assert prices[0] <= 100 < prices[1]

    @pytest.mark.parametrize("test_name", ["Happy path"])
    def test_non_branch_tests_also_get_the_fields_the_code_reads(self, test_name):
        result = DeterministicTestGenerator().generate(_stock_alert())
        test = next(t for t in result.tests if t.name == test_name)
        assert "price" in _mock_for(test.mocked_integrations, "price")
