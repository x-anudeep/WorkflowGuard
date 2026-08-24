from __future__ import annotations

from collections import Counter

from workflow_core.canonical.models import NodeType, Workflow
from workflow_core.costing.models import CostCategory, CostEstimate, OptimizationFinding


class CostOptimizationEngine:
    def analyze(self, workflow: Workflow, estimate: CostEstimate) -> list[OptimizationFinding]:
        findings: list[OptimizationFinding] = []
        llm_nodes = [node for node in workflow.nodes if node.type == NodeType.LLM]
        if len(llm_nodes) > 1:
            findings.append(
                OptimizationFinding(
                    rule_id="WG-COST-OPT-001",
                    title="Repeated LLM calls",
                    message="The workflow contains multiple LLM nodes; some calls may be cacheable or mergeable.",
                    category=CostCategory.LLM,
                    estimated_monthly_savings=round(estimate.monthly_cost * 0.15, 4),
                    recommendation="Review whether repeated prompts can be cached, batched, or replaced with deterministic logic.",
                )
            )
        for node in llm_nodes:
            model = str(node.configuration.get("model") or "").lower()
            if "gpt-4o" in model and "mini" not in model and _looks_simple(node):
                findings.append(
                    OptimizationFinding(
                        rule_id="WG-COST-OPT-002",
                        title="Expensive model for simple task",
                        message=f"{node.name} appears to perform simple classification or routing with an expensive model.",
                        category=CostCategory.LLM,
                        node_id=node.id,
                        estimated_monthly_savings=round(estimate.monthly_cost * 0.2, 4),
                        recommendation="Benchmark a cheaper model or deterministic classifier before changing production behavior.",
                    )
                )
        destinations = [f"{node.provider}:{node.operation}" for node in workflow.nodes if node.type == NodeType.EXTERNAL_API]
        for destination, count in Counter(destinations).items():
            if destination != "None:None" and count > 1:
                findings.append(
                    OptimizationFinding(
                        rule_id="WG-COST-OPT-003",
                        title="Duplicated external API calls",
                        message=f"{destination} is called by {count} nodes.",
                        category=CostCategory.EXTERNAL_API,
                        estimated_monthly_savings=round(estimate.monthly_cost * 0.1, 4),
                        recommendation="Check whether calls can be consolidated or memoized within an execution.",
                    )
                )
        for node in workflow.nodes:
            retries = int(node.configuration.get("retries") or node.configuration.get("retry") or 0)
            if retries > 3:
                findings.append(
                    OptimizationFinding(
                        rule_id="WG-COST-OPT-004",
                        title="Excessive retries",
                        message=f"{node.name} is configured with {retries} retries.",
                        category=CostCategory.OTHER,
                        node_id=node.id,
                        estimated_monthly_savings=round(estimate.monthly_cost * 0.05, 4),
                        recommendation="Use bounded retries with backoff and idempotency controls.",
                    )
                )
            if node.type == NodeType.LLM and int(node.configuration.get("input_tokens") or 0) > 8000:
                findings.append(
                    OptimizationFinding(
                        rule_id="WG-COST-OPT-005",
                        title="Large context sent to model",
                        message=f"{node.name} sends a large estimated context to an LLM.",
                        category=CostCategory.LLM,
                        node_id=node.id,
                        estimated_monthly_savings=round(estimate.monthly_cost * 0.12, 4),
                        recommendation="Summarize, retrieve only relevant context, or cache stable context fragments.",
                    )
                )
        return findings


def _looks_simple(node) -> bool:
    text = f"{node.name} {node.operation} {node.configuration}".lower()
    return any(word in text for word in ["classify", "route", "yes", "no", "label", "sentiment"])
