"""What the emitter hands back: the n8n workflow, and the maps that make it readable again.

The maps are the reason the rest of WorkflowGuard survives the switch to real execution.
Assertions target canonical node and edge ids (`AssertionType.NODE_EXECUTED`,
`EDGE_EXECUTED`), `CoverageCalculator` divides by canonical node and edge counts, and
`expected_path` is a list of canonical ids. n8n knows none of that - it reports node *names*
and output *indices*. These maps translate back.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class NodeMap(BaseModel):
    """Correspondence between canonical node ids and n8n node names."""

    canonical_to_n8n: dict[str, str] = Field(default_factory=dict)
    n8n_to_canonical: dict[str, str] = Field(default_factory=dict)

    #: n8n nodes with no canonical origin - the injected webhook trigger, routers synthesised
    #: for nodes that cannot branch on their own. They must be dropped from `execution_order`:
    #: counting them would push node coverage above 100%, and since `ceb974b` coverage feeds
    #: the overall evaluation score, that is a scoring bug rather than a cosmetic one.
    synthetic: set[str] = Field(default_factory=set)

    #: Canonical ids compiled as approval shims, so `approval_requests` can be rebuilt.
    approval_nodes: set[str] = Field(default_factory=set)

    #: Synthetic router name -> the canonical node it branches for. A router owns the outputs
    #: its canonical node could not, so a branch taken at a router is a decision made *by* that
    #: node, and `branch_decisions` has to be filed under the canonical id rather than lost.
    routers: dict[str, str] = Field(default_factory=dict)

    def canonical(self, n8n_name: str) -> str | None:
        """The canonical id behind an n8n node name, or None if it is synthetic."""
        return self.n8n_to_canonical.get(n8n_name)

    def is_synthetic(self, n8n_name: str) -> bool:
        return n8n_name in self.synthetic

    def decider(self, n8n_name: str) -> str | None:
        """The canonical node whose branch this n8n node decides - itself, or the one it routes for."""
        return self.n8n_to_canonical.get(n8n_name) or self.routers.get(n8n_name)


class EdgeMap(BaseModel):
    """Which canonical edge an n8n connection represents.

    Keyed by the n8n node that *emits* the output and the output index, because that is
    exactly what a downstream `taskData.source[]` entry reports:
    `{previousNode, previousNodeOutput}`. Verified against n8n 2.38.7 in the step-0 spike.

    The emitting node is not always the canonical source node: a node that cannot branch on
    its own gets a synthetic router, and the router is what owns the outputs.
    """

    #: "<n8n node name>::<output index>" -> canonical edge id. A flat string key rather than a
    #: tuple so the model round-trips through JSON unchanged.
    by_output: dict[str, str] = Field(default_factory=dict)

    @staticmethod
    def key(n8n_name: str, output_index: int) -> str:
        return f"{n8n_name}::{output_index}"

    def record(self, n8n_name: str, output_index: int, canonical_edge_id: str) -> None:
        self.by_output[self.key(n8n_name, output_index)] = canonical_edge_id

    def edge_for(self, n8n_name: str, output_index: int) -> str | None:
        return self.by_output.get(self.key(n8n_name, output_index))


class EmittedWorkflow(BaseModel):
    """An n8n workflow ready to POST, plus everything needed to read its execution back."""

    workflow_json: dict[str, Any]
    nodes: NodeMap = Field(default_factory=NodeMap)
    edges: EdgeMap = Field(default_factory=EdgeMap)

    #: Where fidelity was lost. Surfaced on the test run rather than raised, so a workflow
    #: using a construct n8n cannot express still gets executed and still reports coverage -
    #: it just says plainly which part of the result is an approximation.
    warnings: list[str] = Field(default_factory=list)

    #: Canonical ids of nodes whose calls were redirected to the mock server, and the error
    #: output index for nodes that have one. The result mapper needs the latter to tell a
    #: failed node from a successful one: under `onError: continueErrorOutput` a failing node
    #: still reports `executionStatus: "success"` (verified in the step-0 spike), so failure is
    #: only detectable as "this node put an item on its error output".
    mocked_nodes: set[str] = Field(default_factory=set)
    error_output_index: dict[str, int] = Field(default_factory=dict)

    #: The webhook path this workflow listens on. Unique per run: n8n returns 409 on publish
    #: when two workflows claim the same path.
    webhook_path: str = ""
