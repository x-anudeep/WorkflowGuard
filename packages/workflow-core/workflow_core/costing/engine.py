from __future__ import annotations

from workflow_core.canonical.models import Node, NodeType, Workflow
from workflow_core.costing.models import CostCategory, CostEstimate, CostLineItem, CostScenario, PricingEntry
from workflow_core.costing.pricing import PricingCatalog


class CostEstimator:
    def __init__(self, pricing_catalog: PricingCatalog | None = None) -> None:
        self.pricing_catalog = pricing_catalog or PricingCatalog()

    def estimate(self, workflow: Workflow, scenario: CostScenario | None = None) -> CostEstimate:
        scenario = scenario or CostScenario()
        line_items = [self._node_cost(node, scenario) for node in workflow.nodes]
        retry_multiplier = 1 + max(scenario.failure_retry_rate, 0)
        cost_per_run = round(sum(item.estimated_cost_per_run for item in line_items) * retry_multiplier, 6)
        daily = round(cost_per_run * scenario.executions_per_day, 4)
        monthly = round(cost_per_run * scenario.monthly_executions, 4)
        annual = round(monthly * 12, 4)
        return CostEstimate(
            workflow_id=workflow.id,
            workflow_version_id=None,
            scenario=scenario,
            line_items=line_items,
            cost_per_run=cost_per_run,
            daily_cost=daily,
            monthly_cost=monthly,
            annual_cost=annual,
            assumptions=[
                "Estimates use configured pricing catalog entries and canonical node metadata.",
                "Failure/retry rate is applied as a scenario-level multiplier.",
                "Provider bills may differ due to tiering, taxes, discounts, minimums, and exact tokenization.",
            ],
        )

    def _node_cost(self, node: Node, scenario: CostScenario) -> CostLineItem:
        category = _category(node)
        provider = node.provider or "generic"
        model = str(node.configuration.get("model") or node.metadata.get("model") or "") or None
        pricing = self.pricing_catalog.find(category, provider, model)
        calls = float(node.configuration.get("calls_per_execution") or 1)
        if node.type == NodeType.LLM:
            input_tokens = int(node.configuration.get("input_tokens") or scenario.average_input_tokens)
            output_tokens = int(node.configuration.get("output_tokens") or scenario.average_output_tokens)
            cost = _llm_cost(input_tokens, output_tokens, calls, pricing)
            unit_cost = (pricing.input_unit_cost + pricing.output_unit_cost) if pricing else 0
        else:
            input_tokens = output_tokens = 0
            unit_cost = pricing.call_unit_cost if pricing else 0
            cost = calls * unit_cost
        return CostLineItem(
            node_id=node.id,
            node_name=node.name,
            category=category,
            provider=provider,
            model=model,
            calls_per_execution=calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            unit_cost=unit_cost,
            estimated_cost_per_run=round(cost, 6),
            pricing_assumption=pricing.model_dump(mode="json") if pricing else {"missing_pricing": True},
            explanation=_explanation(node, category),
        )


def _llm_cost(input_tokens: int, output_tokens: int, calls: float, pricing: PricingEntry | None) -> float:
    if pricing is None:
        return 0
    return calls * (((input_tokens / 1000) * pricing.input_unit_cost) + ((output_tokens / 1000) * pricing.output_unit_cost))


def _category(node: Node) -> CostCategory:
    if node.type == NodeType.LLM:
        return CostCategory.LLM
    if node.type == NodeType.EXTERNAL_API:
        return CostCategory.EXTERNAL_API
    if node.type == NodeType.DATABASE:
        return CostCategory.DATABASE
    if node.type == NodeType.EMAIL:
        return CostCategory.EMAIL_MESSAGING
    return CostCategory.COMPUTE


def _explanation(node: Node, category: CostCategory) -> str:
    if category == CostCategory.LLM:
        return "LLM cost uses input/output token estimates and calls per execution."
    if category in {CostCategory.EXTERNAL_API, CostCategory.DATABASE, CostCategory.EMAIL_MESSAGING}:
        return "Integration cost uses configured cost per mocked/expected call."
    return "Compute cost uses the configurable per-node execution assumption."
