"""Per-format node mappings.

The mappings decide what a canonical node actually *becomes* in n8n. Two properties matter more
than any individual mapping being pretty:

* **A request's destination is never reproduced.** Method, headers and body are faithful so the
  recorded call shows what the workflow would have sent; the URL is always the mock, so an
  emitted workflow cannot reach a real service whatever the uploaded file asked for.
* **An approximation says so.** A node compiled as something other than what it is carries a
  warning naming itself, or a run implies it exercised work it did not.
"""

from pathlib import Path

import pytest

from workflow_core.canonical.models import Node, NodeType, SourceFormat
from workflow_core.emitters.n8n import N8nEmitter
from workflow_core.emitters.n8n.mapping import map_node
from workflow_core.emitters.n8n.mapping.models import MAX_REQUEST_TIMEOUT_MS
from workflow_core.parsers.registry import default_parser_registry

MOCK = "http://mock.test/mock/token/node"

QUBI_SAMPLES = sorted(Path("references/workflows").glob("*.json"))


def _qubi(subtype: str, **configuration) -> Node:
    return Node(
        id="n1", name="N", type=NodeType.ACTION, subtype=subtype, configuration=configuration
    )


class TestOutboundCallsCannotEscape:
    """The property that keeps real execution safe."""

    @pytest.mark.parametrize(
        "node",
        [
            _qubi("Http", method="GET", url="https://real.example.com/v1/pay"),
            _qubi("Agent", agentId="a1", userMessage="hello"),
            _qubi("RPA", automationId="r1"),
        ],
    )
    def test_qubi_outbound_nodes_point_at_the_mock(self, node):
        mapped = map_node(node, SourceFormat.QUBI.value, MOCK)
        assert mapped.parameters["url"] == MOCK
        assert mapped.mocked is True

    def test_the_intended_destination_is_recorded_not_used(self):
        """A report should be able to say what the workflow meant to call."""
        node = _qubi("Http", method="POST", url="https://real.example.com/v1/pay")
        mapped = map_node(node, SourceFormat.QUBI.value, MOCK)
        assert "real.example.com" not in mapped.parameters["url"]
        assert "real.example.com" in mapped.parameters["jsonBody"]

    def test_generic_integration_nodes_point_at_the_mock(self):
        node = Node(
            id="api",
            name="Api",
            type=NodeType.EXTERNAL_API,
            configuration={"endpoint": "https://real.example.com/hook", "method": "PUT"},
        )
        mapped = map_node(node, SourceFormat.GENERIC_JSON.value, MOCK)
        assert mapped.parameters["url"] == MOCK
        assert mapped.parameters["method"] == "PUT"
        assert "real.example.com" in mapped.parameters["jsonBody"]


class TestRequestFidelity:
    def test_method_is_taken_from_the_node(self):
        mapped = map_node(_qubi("Http", method="delete"), SourceFormat.QUBI.value, MOCK)
        assert mapped.parameters["method"] == "DELETE"

    def test_headers_are_reproduced(self):
        node = _qubi("Http", method="POST", headers={"X-Api-Version": "2", "Accept": "json"})
        mapped = map_node(node, SourceFormat.QUBI.value, MOCK)
        names = [p["name"] for p in mapped.parameters["headerParameters"]["parameters"]]
        assert names == ["X-Api-Version", "Accept"]

    def test_the_body_is_merged_with_the_item_not_replacing_it(self):
        """Canonical state is flat and accumulates; a node must not drop what reached it."""
        mapped = map_node(_qubi("Http", body={"amount": 1}), SourceFormat.QUBI.value, MOCK)
        assert "Object.assign({}, $json" in mapped.parameters["jsonBody"]

    def test_a_declared_timeout_is_honoured(self):
        node = Node(
            id="api", name="Api", type=NodeType.EXTERNAL_API, configuration={"timeout_seconds": 5}
        )
        mapped = map_node(node, SourceFormat.GENERIC_JSON.value, MOCK)
        assert mapped.parameters["options"]["timeout"] == 5000

    def test_a_timeout_longer_than_the_run_is_capped(self):
        """A per-request timeout past the run's own deadline could never fire on its own terms."""
        node = Node(
            id="api", name="Api", type=NodeType.EXTERNAL_API, configuration={"timeout_seconds": 300}
        )
        mapped = map_node(node, SourceFormat.GENERIC_JSON.value, MOCK)
        assert mapped.parameters["options"]["timeout"] == MAX_REQUEST_TIMEOUT_MS

    def test_a_node_without_a_timeout_still_gets_one(self):
        """Without it an injected TIMEOUT hangs the run instead of failing the node."""
        mapped = map_node(_qubi("Http", method="GET"), SourceFormat.QUBI.value, MOCK)
        assert mapped.parameters["options"]["timeout"] > 0


class TestTransforms:
    def test_qubi_assign_becomes_a_set_node(self):
        node = _qubi("Assign", assignments=[{"variable": "greeting", "value": "hi"}])
        mapped = map_node(node, SourceFormat.QUBI.value, MOCK)
        assert mapped.type == "n8n-nodes-base.set"
        entries = mapped.parameters["assignments"]["assignments"]
        assert [e["name"] for e in entries] == ["greeting"]

    def test_a_template_value_becomes_an_n8n_expression(self):
        node = _qubi("Assign", assignments=[{"variable": "msg", "value": "Hello {{ name }}"}])
        mapped = map_node(node, SourceFormat.QUBI.value, MOCK)
        assert mapped.parameters["assignments"]["assignments"][0]["value"].startswith("=")

    def test_upstream_fields_survive_a_set_node(self):
        node = _qubi("Assign", assignments=[{"variable": "x", "value": "1"}])
        mapped = map_node(node, SourceFormat.QUBI.value, MOCK)
        assert mapped.parameters["includeOtherFields"] is True


class TestUploadedLogicIsNotExecuted:
    """WorkflowGuard has never run the contents of an uploaded file, and still does not."""

    @pytest.mark.parametrize("subtype", ["Code", "JsonParser", "TextParser"])
    def test_qubi_logic_nodes_are_not_run(self, subtype):
        mapped = map_node(_qubi(subtype, language="javascript", code="x"), SourceFormat.QUBI.value, MOCK)
        assert mapped.type == "n8n-nodes-base.noOp"
        assert mapped.warning

    def test_bpmn_script_tasks_are_not_run(self):
        node = Node(id="s", name="S", type=NodeType.ACTION, subtype="scriptTask")
        mapped = map_node(node, SourceFormat.BPMN.value, MOCK)
        assert mapped.type == "n8n-nodes-base.noOp"
        assert "not executed" in mapped.warning

    def test_an_llm_call_says_the_model_was_not_consulted(self):
        mapped = map_node(_qubi("Agent", agentId="a"), SourceFormat.QUBI.value, MOCK)
        assert "mocked" in mapped.warning


class TestUnknownNodes:
    def test_an_unrecognised_subtype_falls_through(self):
        assert map_node(_qubi("SomethingNew"), SourceFormat.QUBI.value, MOCK) is None

    def test_bpmn_carries_no_parameters_to_map(self):
        """Not an omission: the BPMN parser extracts no implementation detail to reproduce."""
        node = Node(id="t", name="T", type=NodeType.EXTERNAL_API, subtype="serviceTask")
        assert map_node(node, SourceFormat.BPMN.value, MOCK) is None


@pytest.mark.skipif(not QUBI_SAMPLES, reason="no local qubi samples")
class TestRealQubiWorkflows:
    """Against the 30 real exports the mapping table was derived from."""

    def test_every_sample_emits_with_no_outbound_call_escaping(self):
        registry = default_parser_registry()
        emitter = N8nEmitter(mock_base_url="http://mock.test/mock")
        checked = 0
        for path in QUBI_SAMPLES:
            try:
                workflow = registry.parse(path.name, path.read_bytes()).workflow
            except Exception:  # noqa: BLE001 - not every sample is a qubi export
                continue
            if str(workflow.source_format) != SourceFormat.QUBI.value:
                continue
            checked += 1
            emitted = emitter.emit(workflow, run_token="t")
            for node in emitted.workflow_json["nodes"]:
                url = node.get("parameters", {}).get("url")
                if url:
                    assert url.startswith("http://mock.test/mock"), (path.name, node["name"], url)
        assert checked, "no qubi samples parsed"
