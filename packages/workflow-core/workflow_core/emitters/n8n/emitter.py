"""Compiling a canonical workflow into an n8n workflow that can actually be executed.

The shape of the problem is routing, not node bodies. A canonical `Edge` carries its own
condition, so any node may branch; an n8n node branches only if it is one of the few types
with multiple outputs. So every canonical node becomes one n8n node, and wherever a node
needs to branch but cannot, a **router** (IF or Switch) is synthesised behind it and owns the
outputs instead.

Failure edges are the exception, and they map onto n8n natively: `onError:
continueErrorOutput` gives any node a second output that carries the item when it throws.

Node *bodies* are deliberately shallow here - pass-through nodes become NoOp and every
integration node becomes an HTTP Request pointed at the mock server. Per-format parameter
fidelity is a separate step; each shallow node records a warning naming itself, so a run never
silently reports an approximation as a measurement.

**Never emit `n8n-nodes-base.evaluation` or `evaluationTrigger`.** n8n's Community licence sets
the `workflowsHavingEvaluations` quota to 0, so a workflow containing either fails to publish.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict, deque
from typing import Any

from workflow_core.analysis.failure_paths import is_failure_edge
from workflow_core.canonical.models import Edge, Node, NodeType, Workflow
from workflow_core.conditions import parse_condition
from workflow_core.emitters.n8n.conditions import render_if_parameters
from workflow_core.emitters.n8n.models import EdgeMap, EmittedWorkflow, NodeMap

__all__ = ["INPUT_NODE_NAME", "N8nEmitter", "TRIGGER_NODE_NAME"]

#: The injected webhook. Synthetic, so it is excluded from `execution_order` and coverage.
TRIGGER_NODE_NAME = "__wg_trigger__"

#: Lifts the webhook's request body to the item root. The webhook node emits
#: ``{headers, params, query, body, webhookUrl, ...}``, so without this every downstream
#: ``$json.<field>`` reads undefined and every condition silently evaluates false - the whole
#: graph runs but no branch is ever taken. Synthetic, like the trigger.
INPUT_NODE_NAME = "__wg_input__"

#: Node types whose calls leave the process and must be redirected at the mock server.
_INTEGRATION_TYPES = frozenset(
    {NodeType.EXTERNAL_API, NodeType.DATABASE, NodeType.EMAIL, NodeType.LLM}
)

#: Edge labels that mark the default branch of a gateway, matching the simulator's reading.
_FALLBACK_LABELS = frozenset({"else", "default", "false", "no"})

_SAFE_NAME = re.compile(r"[^A-Za-z0-9 _.\-]")

_COLUMN_WIDTH = 220
_ROW_HEIGHT = 140


class N8nEmitter:
    """Canonical workflow -> n8n workflow JSON, plus the maps to read its execution back."""

    def __init__(self, *, mock_base_url: str = "http://api:8000/mock") -> None:
        self.mock_base_url = mock_base_url.rstrip("/")

    def emit(
        self,
        workflow: Workflow,
        *,
        run_token: str,
        propagate_failures: bool = False,
    ) -> EmittedWorkflow:
        """Compile ``workflow``.

        Args:
            run_token: unique per run. It becomes the webhook path, because n8n rejects a
                publish with 409 when two workflows claim the same path, and it namespaces the
                mock endpoints so concurrent runs cannot read each other's responses.
            propagate_failures: when True, a node with no failure edge of its own continues
                down its normal output after throwing rather than aborting the run. This is
                what the fuzz engine needs to observe behaviour *past* the point of failure,
                and in n8n it is native - `onError: continueRegularOutput`.
        """
        builder = _Builder(workflow, self, run_token=run_token, propagate_failures=propagate_failures)
        return builder.build()


class _Builder:
    """One emission. Holds the mutable state so `N8nEmitter` itself stays reusable."""

    def __init__(
        self, workflow: Workflow, emitter: N8nEmitter, *, run_token: str, propagate_failures: bool
    ) -> None:
        self.workflow = workflow
        self.emitter = emitter
        self.run_token = run_token
        self.propagate_failures = propagate_failures

        self.nodes: list[dict[str, Any]] = []
        self.connections: dict[str, dict[str, list[list[dict[str, Any]]]]] = {}
        self.node_map = NodeMap()
        self.edge_map = EdgeMap()
        self.warnings: list[str] = []
        self.mocked: set[str] = set()
        self.error_output: dict[str, int] = {}

        self._used_names: set[str] = {TRIGGER_NODE_NAME, INPUT_NODE_NAME}
        self._outgoing: dict[str, list[Edge]] = defaultdict(list)
        for edge in workflow.edges:
            self._outgoing[edge.source].append(edge)
        self._depths = self._compute_depths()

    # -- top level ---------------------------------------------------------------------

    def build(self) -> EmittedWorkflow:
        webhook_path = f"wg-{self.run_token}"
        self._add_trigger(webhook_path)

        for node in self.workflow.nodes:
            self._add_node(node)

        for node in self.workflow.nodes:
            self._wire(node)

        self._connect_trigger()
        self._apply_failure_propagation()

        return EmittedWorkflow(
            workflow_json={
                "name": f"wg-{self.run_token}-{_safe(self.workflow.name)}"[:120],
                "nodes": self.nodes,
                "connections": self.connections,
                "settings": {"executionOrder": "v1"},
            },
            nodes=self.node_map,
            edges=self.edge_map,
            warnings=self.warnings,
            mocked_nodes=self.mocked,
            error_output_index=self.error_output,
            webhook_path=webhook_path,
        )

    def _apply_failure_propagation(self) -> None:
        """Let failures travel downstream on nodes that declare no error path of their own.

        The fuzz engine measures how a workflow behaves *past* the point of failure, so a run
        that halts at the first throw tells it nothing. The simulator did this with a
        `propagate_failures` flag; in n8n it is `onError: continueRegularOutput`, which sends
        the item down the normal output instead of aborting the execution.
        """
        if not self.propagate_failures:
            return
        for node_id, name in self.node_map.canonical_to_n8n.items():
            if node_id in self.error_output:
                continue  # already has a real error path; that one wins
            emitted = self._find(name)
            if emitted["name"] in {TRIGGER_NODE_NAME, INPUT_NODE_NAME}:
                continue
            emitted["onError"] = "continueRegularOutput"

    # -- nodes -------------------------------------------------------------------------

    def _add_trigger(self, webhook_path: str) -> None:
        self.nodes.append(
            {
                "id": _uuid_like("trigger"),
                "name": TRIGGER_NODE_NAME,
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 2,
                "position": [0, 0],
                "parameters": {
                    "httpMethod": "POST",
                    "path": webhook_path,
                    "responseMode": "lastNode",
                },
            }
        )
        self.node_map.synthetic.add(TRIGGER_NODE_NAME)

        self.nodes.append(
            {
                "id": _uuid_like("input"),
                "name": INPUT_NODE_NAME,
                "type": "n8n-nodes-base.set",
                "typeVersion": 3.4,
                "position": [_COLUMN_WIDTH // 2, 0],
                "parameters": {
                    "mode": "raw",
                    "jsonOutput": "={{ JSON.stringify($json.body ?? {}) }}",
                    "options": {},
                },
            }
        )
        self.node_map.synthetic.add(INPUT_NODE_NAME)
        self._connect_raw(TRIGGER_NODE_NAME, 0, INPUT_NODE_NAME)

    def _add_node(self, node: Node) -> None:
        name = self._claim_name(node)
        self.node_map.canonical_to_n8n[node.id] = name
        self.node_map.n8n_to_canonical[name] = node.id

        spec = self._node_spec(node)
        emitted: dict[str, Any] = {
            "id": _uuid_like(node.id),
            "name": name,
            "type": spec["type"],
            "typeVersion": spec["typeVersion"],
            "position": self._position(node.id),
            "parameters": spec["parameters"],
        }

        retries = _retry_count(node)
        if retries:
            emitted["retryOnFail"] = True
            emitted["maxTries"] = min(max(retries + 1, 2), 5)
            emitted["waitBetweenTries"] = 100

        self.nodes.append(emitted)

    def _node_spec(self, node: Node) -> dict[str, Any]:
        """The n8n node type and parameters for a canonical node.

        A condition node is handled by `_wire`, which turns it into the IF/Switch that owns its
        outputs; here it is a placeholder so that it still appears in `execution_order`.
        """
        if node.type in _INTEGRATION_TYPES:
            self.mocked.add(node.id)
            return {
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 4.2,
                "parameters": {
                    "method": "POST",
                    "url": f"{self.emitter.mock_base_url}/{self.run_token}/{node.id}",
                    "sendBody": True,
                    "specifyBody": "json",
                    "jsonBody": "={{ JSON.stringify($json) }}",
                    "options": {"response": {"response": {"neverError": False}}},
                },
            }

        if node.type == NodeType.HUMAN_APPROVAL:
            # n8n's Wait and Form nodes block; a test run cannot. The shim answers from the
            # run's input, defaulting to approved, matching the simulator's semantics.
            self.node_map.approval_nodes.add(node.id)
            self.warnings.append(
                f"Node {node.id!r} is a human approval; it was auto-answered from the test "
                f"input (default: approved) because n8n's approval nodes block execution."
            )
            return {
                "type": "n8n-nodes-base.set",
                "typeVersion": 3.4,
                "parameters": {
                    "assignments": {
                        "assignments": [
                            {
                                "id": "approved",
                                "name": "approved",
                                "type": "boolean",
                                "value": "={{ $json.approved === undefined ? true : $json.approved }}",
                            },
                            {
                                "id": "approval_requested",
                                "name": "approval_requested",
                                "type": "boolean",
                                "value": True,
                            },
                        ]
                    },
                    "includeOtherFields": True,
                    "options": {},
                },
            }

        if node.type not in {NodeType.CONDITION, NodeType.TRIGGER, NodeType.EVENT, NodeType.END}:
            # Structure is right, body is not modelled yet. Say so rather than let the run
            # imply the node's real work was exercised.
            self.warnings.append(
                f"Node {node.id!r} ({node.type}) compiled as a pass-through; its parameters "
                f"are not yet modelled for source format {self.workflow.source_format}."
            )

        return {"type": "n8n-nodes-base.noOp", "typeVersion": 1, "parameters": {}}

    # -- wiring ------------------------------------------------------------------------

    def _wire(self, node: Node) -> None:
        outgoing = self._outgoing.get(node.id, [])
        if not outgoing:
            return
        name = self.node_map.canonical_to_n8n[node.id]

        failure_edges = [e for e in outgoing if is_failure_edge(e)]
        branch_edges = [e for e in outgoing if not is_failure_edge(e)]

        if node.type == NodeType.CONDITION and failure_edges:
            # A gateway with an error path as well as branches: n8n cannot give a Switch both
            # without a second router, and the combination has not been seen in practice.
            self.warnings.append(
                f"Condition node {node.id!r} has both conditional branches and a failure edge; "
                f"the failure edge was treated as an ordinary branch."
            )
            branch_edges, failure_edges = outgoing, []

        if failure_edges:
            self._wire_failure(node, name, failure_edges)

        if not branch_edges:
            return

        conditional = [e for e in branch_edges if e.condition]
        if not conditional:
            self._wire_direct(name, branch_edges)
        elif node.type == NodeType.CONDITION:
            self._wire_router(node.id, name, branch_edges, replace_in_place=True)
        else:
            self._wire_router(node.id, name, branch_edges, replace_in_place=False)

    def _wire_failure(self, node: Node, name: str, failure_edges: list[Edge]) -> None:
        """Give the node an error output and hang its failure edges off it."""
        emitted = self._find(name)
        emitted["onError"] = "continueErrorOutput"
        error_index = 1
        self.error_output[node.id] = error_index
        for edge in failure_edges:
            self._connect(name, error_index, edge)
        if len(failure_edges) > 1:
            self.warnings.append(
                f"Node {node.id!r} has {len(failure_edges)} failure edges; n8n has a single "
                f"error output, so all of them fan out from it."
            )

    def _wire_direct(self, name: str, edges: list[Edge]) -> None:
        """Unconditional edges all hang off main output 0.

        n8n fans out: every connected node runs. The simulator followed only the first edge
        (`_select_edges` returned `edges[:1]`), so a node with several unconditional successors
        is one place where real execution and the old simulation legitimately differ.
        """
        for edge in edges:
            self._connect(name, 0, edge)
        if len(edges) > 1:
            self.warnings.append(
                f"Node {self.node_map.n8n_to_canonical[name]!r} has {len(edges)} unconditional "
                f"successors; all of them execute in n8n, where the simulator followed only the first."
            )

    def _wire_router(
        self, canonical_id: str, name: str, edges: list[Edge], *, replace_in_place: bool
    ) -> None:
        """Build the IF/Switch that owns this node's branch outputs.

        When the canonical node *is* a gateway the router replaces it in place, so the canonical
        node keeps its identity in `execution_order`. Otherwise a synthetic router is appended
        behind it, because an ordinary n8n node has nowhere to put a second output.
        """
        conditional = [e for e in edges if e.condition]
        fallback = [e for e in edges if not e.condition or str(e.label).lower() in _FALLBACK_LABELS]
        fallback = [e for e in fallback if e not in conditional]

        if replace_in_place:
            router_name = name
        else:
            router_name = self._claim_literal(f"{name} Router")
            self.nodes.append(
                {
                    "id": _uuid_like(f"{canonical_id}:router"),
                    "name": router_name,
                    "type": "n8n-nodes-base.noOp",
                    "typeVersion": 1,
                    "position": self._position(canonical_id, offset=1),
                    "parameters": {},
                }
            )
            self.node_map.synthetic.add(router_name)
            self.node_map.routers[router_name] = canonical_id
            self._connect_raw(name, 0, router_name)

        emitted = self._find(router_name)
        if len(conditional) == 1:
            self._make_if(emitted, conditional[0])
            self._connect(router_name, 0, conditional[0])
            for edge in fallback:
                self._connect(router_name, 1, edge)
        else:
            self._make_switch(emitted, conditional, with_fallback=bool(fallback))
            for index, edge in enumerate(conditional):
                self._connect(router_name, index, edge)
            for edge in fallback:
                self._connect(router_name, len(conditional), edge)

        if len(fallback) > 1:
            self.warnings.append(
                f"Node {canonical_id!r} has {len(fallback)} default branches; all of them "
                f"execute from the router's fallback output."
            )

    def _make_if(self, emitted: dict[str, Any], edge: Edge) -> None:
        emitted["type"] = "n8n-nodes-base.if"
        emitted["typeVersion"] = 2.2
        emitted["parameters"] = render_if_parameters(parse_condition(edge.condition))

    def _make_switch(self, emitted: dict[str, Any], edges: list[Edge], *, with_fallback: bool) -> None:
        emitted["type"] = "n8n-nodes-base.switch"
        emitted["typeVersion"] = 3.2
        rules = []
        for index, edge in enumerate(edges):
            params = render_if_parameters(parse_condition(edge.condition))
            rules.append(
                {
                    "conditions": params["conditions"],
                    "renameOutput": True,
                    "outputKey": (edge.label or edge.condition or f"branch{index}")[:60],
                }
            )
        emitted["parameters"] = {
            "rules": {"values": rules},
            "options": {"fallbackOutput": "extra"} if with_fallback else {},
        }

    # -- connection plumbing -------------------------------------------------------------

    def _connect(self, source_name: str, output_index: int, edge: Edge) -> None:
        target = self.node_map.canonical_to_n8n.get(edge.target)
        if target is None:
            # A dangling edge. The validation rules already report it; emitting a connection to
            # a node that does not exist would make n8n refuse the whole workflow.
            self.warnings.append(
                f"Edge {edge.id!r} points at unknown node {edge.target!r} and was not emitted."
            )
            return
        self._connect_raw(source_name, output_index, target)
        self.edge_map.record(source_name, output_index, edge.id)

    def _connect_raw(self, source_name: str, output_index: int, target_name: str) -> None:
        main = self.connections.setdefault(source_name, {}).setdefault("main", [])
        while len(main) <= output_index:
            main.append([])
        main[output_index].append({"node": target_name, "type": "main", "index": 0})

    def _connect_trigger(self) -> None:
        starts = sorted(self.workflow.start_node_ids)
        for start in starts:
            target = self.node_map.canonical_to_n8n.get(start)
            if target:
                self._connect_raw(INPUT_NODE_NAME, 0, target)
        if len(starts) > 1:
            self.warnings.append(
                f"Workflow has {len(starts)} start nodes; the injected trigger fans out to all "
                f"of them, so they run in parallel."
            )

    # -- naming, layout, lookup ------------------------------------------------------------

    def _claim_name(self, node: Node) -> str:
        return self._claim_literal(_safe(node.name) or node.id)

    def _claim_literal(self, preferred: str) -> str:
        candidate = preferred or "node"
        suffix = 2
        while candidate in self._used_names:
            candidate = f"{preferred} {suffix}"
            suffix += 1
        self._used_names.add(candidate)
        return candidate

    def _find(self, name: str) -> dict[str, Any]:
        for emitted in self.nodes:
            if emitted["name"] == name:
                return emitted
        raise KeyError(name)

    def _compute_depths(self) -> dict[str, int]:
        depths: dict[str, int] = {}
        queue: deque[tuple[str, int]] = deque(
            (start, 0) for start in sorted(self.workflow.start_node_ids)
        )
        while queue:
            node_id, depth = queue.popleft()
            if node_id in depths:
                continue
            depths[node_id] = depth
            for edge in self._outgoing.get(node_id, []):
                if edge.target not in depths:
                    queue.append((edge.target, depth + 1))
        for index, node in enumerate(self.workflow.nodes):
            depths.setdefault(node.id, index)
        return depths

    def _position(self, node_id: str, *, offset: int = 0) -> list[int]:
        depth = self._depths.get(node_id, 0) + offset
        siblings = [n for n, d in sorted(self._depths.items()) if d == depth - offset]
        row = siblings.index(node_id) if node_id in siblings else 0
        return [(depth + 1) * _COLUMN_WIDTH, row * _ROW_HEIGHT]


def _retry_count(node: Node) -> int:
    raw = node.configuration.get("retries") or node.configuration.get("retry") or 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _safe(text: str) -> str:
    return _SAFE_NAME.sub("", str(text)).strip()[:80]


def _uuid_like(seed: str) -> str:
    """A stable pseudo-UUID from the canonical id, so emission is deterministic.

    Golden-file tests depend on this: a random uuid4 per node would make every emitted
    workflow differ from the last for no reason.
    """
    digest = hashlib.sha1(seed.encode(), usedforsecurity=False).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-4{digest[13:16]}-8{digest[17:20]}-{digest[20:32]}"
