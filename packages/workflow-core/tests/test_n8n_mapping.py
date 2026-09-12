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


class TestExpressionsCannotNest:
    """The invariant that would have caught this without needing a workflow to trip over it.

    Source formats have `{{ name }}` templates of their own. Embedding one inside an n8n
    `={{ ... }}` expression nests braces, n8n fails to parse the node, and *every* test of that
    workflow fails with "invalid syntax" - a whole-workflow outage from one templated URL.
    """

    @staticmethod
    def _nested(value) -> bool:
        """Whether an emitted expression contains a `{{` inside another `{{ }}`."""
        text = str(value)
        if not text.startswith("={{"):
            return False
        return "{{" in text[3:]

    def _assert_no_nesting(self, node):
        for key, value in (node.get("parameters") or {}).items():
            if isinstance(value, str):
                assert not self._nested(value), (node.get("name"), key, value[:160])
            elif isinstance(value, dict):
                for inner in value.values():
                    if isinstance(inner, str):
                        assert not self._nested(inner), (node.get("name"), key, inner[:160])

    @pytest.mark.parametrize(
        "configuration",
        [
            {"method": "GET", "url": "https://api.example.com/w?appid={{apiKey}}"},
            {"method": "POST", "url": "https://x.test", "body": {"q": "{{location}}"}},
            {"method": "POST", "url": "https://x.test", "body": {"deep": {"q": "{{location}}"}}},
            {"method": "POST", "url": "https://x.test", "body": {"list": ["{{a}}", "b"]}},
        ],
    )
    def test_a_templated_http_value_never_nests(self, configuration):
        node = Node(
            id="n", name="N", type=NodeType.EXTERNAL_API, subtype="Http", configuration=configuration
        )
        mapped = map_node(node, SourceFormat.QUBI.value, MOCK)
        assert "{{" not in mapped.parameters["jsonBody"][3:]

    def test_a_templated_prompt_never_nests(self):
        node = _qubi("Agent", agentId="a", userMessage="Report {{temperature}} and {{description}}")
        mapped = map_node(node, SourceFormat.QUBI.value, MOCK)
        assert "{{" not in mapped.parameters["jsonBody"][3:]

    def test_a_template_resolves_to_the_variable_rather_than_being_escaped(self):
        """Escaping would fix the parse and lose the meaning; a template names a variable."""
        node = _qubi("Http", method="GET", url="https://x.test/?k={{apiKey}}")
        body = map_node(node, SourceFormat.QUBI.value, MOCK).parameters["jsonBody"]
        assert '$json["apiKey"]' in body

    def test_an_unresolved_variable_does_not_interpolate_undefined(self):
        """"undefined" spliced into a URL is wrong and very hard to spot afterwards."""
        node = _qubi("Http", method="GET", url="https://x.test/?k={{missing}}")
        assert '?? ""' in map_node(node, SourceFormat.QUBI.value, MOCK).parameters["jsonBody"]

    @pytest.mark.skipif(not QUBI_SAMPLES, reason="no local qubi samples")
    def test_no_emitted_node_in_any_real_workflow_nests_an_expression(self):
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
            for node in emitter.emit(workflow, run_token="t").workflow_json["nodes"]:
                self._assert_no_nesting(node)
        assert checked, "no qubi samples parsed"


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


class TestCodeExecution:
    """A Branch downstream of a Code node is only trustworthy if the code actually ran."""

    def test_javascript_is_compiled_to_a_code_node(self):
        node = _qubi("Code", language="javascript", code="return { total: 1 };")
        mapped = map_node(node, SourceFormat.QUBI.value, MOCK)
        assert mapped.type == "n8n-nodes-base.code"
        assert "return { total: 1 };" in mapped.parameters["jsCode"]

    def test_workflow_variables_are_bound_as_locals(self):
        """Qubi snippets read variables by bare name; n8n exposes them only as `$json`."""
        node = _qubi("Code", language="javascript", code="return { t: price * qty };")
        mapped = map_node(node, SourceFormat.QUBI.value, MOCK)
        assert "Object.keys($wgScope)" in mapped.parameters["jsCode"]

    def test_the_result_is_merged_over_the_item_not_replacing_it(self):
        """Canonical state accumulates; a node returning one field must not erase the rest."""
        node = _qubi("Code", language="javascript", code="return { t: 1 };")
        mapped = map_node(node, SourceFormat.QUBI.value, MOCK)
        assert "Object.assign(" in mapped.parameters["jsCode"]

    def test_save_output_as_names_the_result(self):
        node = _qubi("Code", language="javascript", code="return { t: 1 };", saveOutputAs="calc")
        mapped = map_node(node, SourceFormat.QUBI.value, MOCK)
        assert '"calc"' in mapped.parameters["jsCode"]

    def test_an_empty_code_node_is_not_run(self):
        mapped = map_node(_qubi("Code", language="javascript", code="  "), SourceFormat.QUBI.value, MOCK)
        assert mapped.type == "n8n-nodes-base.noOp"

    def test_the_declared_input_mapping_is_bound(self):
        """Found by live-testing a real workflow: snippets read `input.x`, not just bare `x`.

        A qubi Code node declares `input: {"poRecord": "{{poRecord}}"}` and its body uses both
        forms. Binding only the bare names left `input` undefined, so every test of that
        workflow failed with "input is not defined" - including the happy path.
        """
        node = _qubi(
            "Code",
            language="javascript",
            input={"poRecord": "{{poRecord}}", "totalAmount": "{{totalAmount}}"},
            code="return { ok: input.poRecord.amount === totalAmount };",
        )
        mapped = map_node(node, SourceFormat.QUBI.value, MOCK)
        code = mapped.parameters["jsCode"]
        assert '"poRecord": "poRecord"' in code
        assert "input: $wgInput" in code

    def test_a_dotted_input_reference_resolves_by_its_last_segment(self):
        """Flat state, as everywhere else in the canonical model."""
        node = _qubi(
            "Code", language="javascript", input={"amount": "{{invoice.amount}}"}, code="return {};"
        )
        code = map_node(node, SourceFormat.QUBI.value, MOCK).parameters["jsCode"]
        assert '"amount": "amount"' in code

    def test_a_non_template_input_value_is_passed_through_as_a_constant(self):
        node = _qubi("Code", language="javascript", input={"limit": 50}, code="return {};")
        code = map_node(node, SourceFormat.QUBI.value, MOCK).parameters["jsCode"]
        assert '{"limit": 50}' in code

    def test_state_keys_that_are_not_identifiers_cannot_break_the_wrapper(self):
        """A key like `content-type` as a function parameter would be a syntax error."""
        node = _qubi("Code", language="javascript", code="return {};")
        code = map_node(node, SourceFormat.QUBI.value, MOCK).parameters["jsCode"]
        assert "A-Za-z_$" in code

    def test_input_falls_back_to_the_whole_state_when_no_mapping_is_declared(self):
        """Found by live-testing: `return { isHigh: input.price > 100 }` with no mapping.

        Binding an empty object makes every `input.x` read undefined, which is worse than
        failing: the code still runs, computes a confidently wrong answer, and the branch that
        tests it takes the wrong path with nothing reported.
        """
        node = _qubi("Code", language="javascript", code="return { ok: input.price > 100 };")
        code = map_node(node, SourceFormat.QUBI.value, MOCK).parameters["jsCode"]
        assert "$wgHasMapping" in code
        assert "Object.assign({}, $wgItem)" in code

    def test_python_is_not_executed_and_says_so(self):
        """n8n runs Python through Pyodide, which does not offer the same variable binding."""
        mapped = map_node(_qubi("Code", language="python", code="x=1"), SourceFormat.QUBI.value, MOCK)
        assert mapped.type == "n8n-nodes-base.noOp"
        assert "Python" in mapped.warning


class TestUploadedLogicIsNotExecuted:
    """What remains unexecuted still has to say so rather than pass silently."""

    @pytest.mark.parametrize("subtype", ["JsonParser", "TextParser"])
    def test_qubi_parser_nodes_are_not_run(self, subtype):
        mapped = map_node(_qubi(subtype), SourceFormat.QUBI.value, MOCK)
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
