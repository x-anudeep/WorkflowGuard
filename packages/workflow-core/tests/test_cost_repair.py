from __future__ import annotations

from workflow_core.canonical.models import Edge, Node, NodeType, SourceFormat, Workflow
from workflow_core.cli import main
from workflow_core.comparison import VersionComparisonEngine
from workflow_core.costing import CostEstimator, CostOptimizationEngine, CostScenario
from workflow_core.repair import DeterministicRepairEngine, RepairPatchApplier


def cost_workflow() -> Workflow:
    return Workflow(
        id="wf_cost",
        name="Cost workflow",
        source_format=SourceFormat.GENERIC_JSON,
        nodes=[
            Node(id="start", name="Start", type=NodeType.TRIGGER),
            Node(
                id="classify",
                name="Simple classification",
                type=NodeType.LLM,
                provider="openai",
                configuration={"model": "gpt-4o", "input_tokens": 2000, "output_tokens": 500},
            ),
            Node(id="erp", name="ERP call", type=NodeType.EXTERNAL_API, provider="sap", configuration={"retries": 5}),
            Node(id="end", name="End", type=NodeType.END),
        ],
        edges=[
            Edge(id="e1", source="start", target="classify"),
            Edge(id="e2", source="classify", target="erp"),
            Edge(id="e3", source="erp", target="end"),
        ],
    )


def test_cost_estimator_uses_token_and_retry_scenario() -> None:
    estimate = CostEstimator().estimate(cost_workflow(), CostScenario(executions_per_day=10, failure_retry_rate=0.1))
    llm = next(item for item in estimate.line_items if item.node_id == "classify")
    assert llm.input_tokens == 2000
    assert llm.output_tokens == 500
    assert llm.estimated_cost_per_run > 0
    assert estimate.monthly_cost == round(estimate.cost_per_run * 300, 4)
    assert any("Provider bills may differ" in assumption for assumption in estimate.assumptions)


def test_optimization_detects_expensive_model_and_excessive_retries() -> None:
    workflow = cost_workflow()
    estimate = CostEstimator().estimate(workflow)
    findings = CostOptimizationEngine().analyze(workflow, estimate)
    rule_ids = {finding.rule_id for finding in findings}
    assert "WG-COST-OPT-002" in rule_ids
    assert "WG-COST-OPT-004" in rule_ids


def test_version_comparison_detects_added_nodes_and_config_changes() -> None:
    before = cost_workflow()
    after = before.model_copy(deep=True)
    after.nodes.append(Node(id="cache", name="Cache", type=NodeType.DATABASE))
    after.nodes[1].configuration["input_tokens"] = 1000
    comparison = VersionComparisonEngine().compare(before, after, cost_before=0.02, cost_after=0.01)
    assert comparison.nodes_added == ["cache"]
    assert comparison.configuration_changed == ["classify"]
    assert comparison.estimated_cost_delta == -0.01


def test_repair_patch_applies_safely_without_new_destinations() -> None:
    workflow = cost_workflow()
    patch = DeterministicRepairEngine().propose(workflow, {"message": "ERP call missing retry handling"})
    candidate = RepairPatchApplier().apply(workflow, patch)
    erp = next(node for node in candidate.nodes if node.id == "erp")
    assert erp.configuration["timeout_seconds"] == 30
    assert erp.configuration["retries"] >= 5
    assert patch.behavior_changes == []


def test_cli_cost_and_compare_commands(capsys) -> None:
    assert main(["cost", "examples/json/valid-workflow.json", "--json"]) == 0
    assert "monthly_cost" in capsys.readouterr().out
    assert main(["compare", "examples/json/valid-workflow.json", "examples/json/orphan-node.json", "--json"]) == 0
    assert "nodes_added" in capsys.readouterr().out
