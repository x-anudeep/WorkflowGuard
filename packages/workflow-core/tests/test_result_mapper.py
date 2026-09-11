"""Reading an n8n execution back as a `SimulationResult`.

Two kinds of test here, and both are needed.

*Synthetic* cases drive the mapper with payloads assembled by hand, so each rule can be
isolated. *Recorded* cases run it against real n8n 2.38.7 output captured in
`tests/fixtures/n8n/`, which is what stops the synthetic payloads from drifting into a shape n8n
never actually produces - the failure mode that would make every other test here meaningless.
"""

import json
from pathlib import Path

import pytest

from workflow_core.canonical.models import Edge, Node, NodeType, SourceFormat, SourceType, Workflow
from workflow_core.emitters.n8n import N8nEmitter
from workflow_core.execution.result_mapper import map_execution
from workflow_core.testing.models import SimulatedCall, TestRunStatus, WorkflowTest

FIXTURES = Path(__file__).parent / "fixtures" / "n8n"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _test() -> WorkflowTest:
    return WorkflowTest(name="t", description="d")


def _task(*, index, outputs=None, error=None, source=None, execution_time=5, status="success"):
    """A `taskData` entry shaped exactly as n8n emits one."""
    task = {
        "executionIndex": index,
        "executionStatus": status,
        "executionTime": execution_time,
        "startTime": 1_700_000_000_000 + index,
        "source": source or [],
        "hints": [],
    }
    if error is not None:
        task["error"] = error
    else:
        task["data"] = {"main": outputs if outputs is not None else [[{"json": {}}]]}
    return task


def _execution(run_data, *, status="success", finished=True, error=None):
    result_data = {"runData": run_data, "lastNodeExecuted": None}
    if error:
        result_data["error"] = error
    return {"status": status, "finished": finished, "data": {"resultData": result_data}}


def _branching_workflow() -> Workflow:
    return Workflow(
        name="Branching",
        source_format=SourceFormat.GENERIC_JSON,
        source_type=SourceType.HUMAN,
        nodes=[
            Node(id="start", name="Start", type=NodeType.TRIGGER),
            Node(id="gate", name="Gate", type=NodeType.CONDITION),
            Node(id="high", name="High", type=NodeType.ACTION),
            Node(id="low", name="Low", type=NodeType.ACTION),
        ],
        edges=[
            Edge(id="e_start", source="start", target="gate"),
            Edge(id="e_high", source="gate", target="high", condition="amount > 1000", label="high"),
            Edge(id="e_low", source="gate", target="low", condition="amount <= 1000", label="low"),
        ],
    )


@pytest.fixture()
def emitted():
    return N8nEmitter(mock_base_url="http://mock.test/mock").emit(
        _branching_workflow(), run_token="t"
    )


class TestIdentityTranslation:
    def test_execution_order_is_canonical_ids(self, emitted):
        execution = _execution(
            {
                "__wg_trigger__": [_task(index=0)],
                "__wg_input__": [_task(index=1)],
                "Start": [_task(index=2)],
                "Gate": [_task(index=3, outputs=[[{"json": {}}], []])],
                "High": [_task(index=4)],
            }
        )
        result = map_execution(execution, emitted, _test(), workflow_id="w1")
        assert result.execution_order == ["start", "gate", "high"]

    def test_synthetic_nodes_are_excluded(self, emitted):
        """Counting them would push node coverage past 100%, which now moves the overall score."""
        execution = _execution({"__wg_trigger__": [_task(index=0)], "Start": [_task(index=1)]})
        result = map_execution(execution, emitted, _test(), workflow_id="w1")
        assert result.execution_order == ["start"]

    def test_order_follows_execution_index_not_dict_order(self, emitted):
        """Nodes finish in sub-millisecond times when integrations are mocked, so startTime ties."""
        execution = _execution(
            {
                "High": [_task(index=9, execution_time=0)],
                "Start": [_task(index=1, execution_time=0)],
                "Gate": [_task(index=5, execution_time=0, outputs=[[{"json": {}}], []])],
            }
        )
        result = map_execution(execution, emitted, _test(), workflow_id="w1")
        assert result.execution_order == ["start", "gate", "high"]

    def test_executed_edges_come_from_source_back_references(self, emitted):
        execution = _execution(
            {
                "Start": [_task(index=0)],
                "Gate": [
                    _task(
                        index=1,
                        outputs=[[{"json": {}}], []],
                        source=[{"previousNode": "Start", "previousNodeOutput": 0}],
                    )
                ],
                "High": [
                    _task(index=2, source=[{"previousNode": "Gate", "previousNodeOutput": 0}])
                ],
            }
        )
        result = map_execution(execution, emitted, _test(), workflow_id="w1")
        assert result.executed_edges == ["e_start", "e_high"]

    def test_the_untaken_branch_is_not_reported_as_covered(self, emitted):
        execution = _execution(
            {
                "Gate": [_task(index=0, outputs=[[{"json": {}}], []])],
                "High": [_task(index=1, source=[{"previousNode": "Gate", "previousNodeOutput": 0}])],
            }
        )
        result = map_execution(execution, emitted, _test(), workflow_id="w1")
        assert "e_low" not in result.executed_edges


class TestBranchDecisions:
    """`branch_decisions` holds the edge's label, not its id.

    That is the shape the simulator always produced and the UI renders directly, so the n8n
    mapper has to match it or every stored run changes meaning.
    """

    def test_the_taken_output_is_recorded(self, emitted):
        execution = _execution({"Gate": [_task(index=0, outputs=[[{"json": {}}], []])]})
        result = map_execution(execution, emitted, _test(), workflow_id="w1")
        assert result.branch_decisions["gate"] == "high"

    def test_the_second_output_is_recorded_when_it_is_the_one_taken(self, emitted):
        execution = _execution({"Gate": [_task(index=0, outputs=[[], [{"json": {}}]])]})
        result = map_execution(execution, emitted, _test(), workflow_id="w1")
        assert result.branch_decisions["gate"] == "low"

    def test_a_router_files_its_decision_under_the_canonical_node(self):
        """The router exists only because that node could not hold its own outputs."""
        workflow = Workflow(
            name="Approval",
            source_format=SourceFormat.GENERIC_JSON,
            source_type=SourceType.HUMAN,
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
        emitted = N8nEmitter().emit(workflow, run_token="t")
        router = next(iter(emitted.nodes.routers))
        execution = _execution({router: [_task(index=0, outputs=[[{"json": {}}], []])]})
        result = map_execution(execution, emitted, _test(), workflow_id="w1")
        # No label on that edge, so the condition describes the branch - exactly the
        # `label or condition or target` fallback the simulator used.
        assert result.branch_decisions == {"approve": "approved == true"}


class TestFailureDetection:
    def test_stop_on_error_is_read_from_task_error(self, emitted):
        execution = _execution(
            {"High": [_task(index=0, error={"message": "boom"}, status="error")]},
            status="error",
            finished=False,
        )
        result = map_execution(execution, emitted, _test(), workflow_id="w1")
        assert result.status == TestRunStatus.ERROR
        assert any("boom" in f for f in result.failures)

    def test_a_node_that_reports_success_but_errored_is_still_a_failure(self):
        """The trap in n8n's data model.

        Under `onError: continueErrorOutput` the failing node's `executionStatus` is "success"
        and it carries no `error` key. Reading status alone would report a workflow that
        swallowed every error as entirely healthy.
        """
        workflow = Workflow(
            name="Failing",
            source_format=SourceFormat.GENERIC_JSON,
            source_type=SourceType.HUMAN,
            nodes=[
                Node(id="start", name="Start", type=NodeType.TRIGGER),
                Node(id="call", name="Call", type=NodeType.EXTERNAL_API),
                Node(id="recover", name="Recover", type=NodeType.ACTION),
            ],
            edges=[
                Edge(id="e0", source="start", target="call"),
                Edge(id="e_fail", source="call", target="recover", label="failure path"),
            ],
        )
        emitted = N8nEmitter().emit(workflow, run_token="t")
        execution = _execution(
            {
                "Call": [
                    _task(
                        index=0,
                        status="success",
                        outputs=[[], [{"json": {"error": {"message": "ECONNREFUSED"}}}]],
                    )
                ]
            },
            status="success",
            finished=True,
        )
        result = map_execution(execution, emitted, _test(), workflow_id="w1")
        assert result.status == TestRunStatus.ERROR
        assert any("ECONNREFUSED" in f for f in result.failures)

    def test_workflow_level_error_is_captured_once(self, emitted):
        execution = _execution(
            {"High": [_task(index=0, error={"message": "boom"}, status="error")]},
            status="error",
            finished=False,
            error={"message": "boom"},
        )
        result = map_execution(execution, emitted, _test(), workflow_id="w1")
        assert len([f for f in result.failures if "boom" in f]) == 1

    def test_a_clean_run_passes(self, emitted):
        execution = _execution({"Start": [_task(index=0)]})
        assert map_execution(execution, emitted, _test(), workflow_id="w1").status == TestRunStatus.PASSED


class TestDataFromTheMockServer:
    def test_retries_come_from_the_caller_not_from_n8n(self, emitted):
        """n8n reports no attempt count; the mock is hit once per attempt."""
        execution = _execution({"High": [_task(index=0)]})
        result = map_execution(
            execution, emitted, _test(), workflow_id="w1", retries={"high": 2}
        )
        assert result.retries == {"high": 2}

    def test_external_calls_are_passed_through(self, emitted):
        call = SimulatedCall(node_id="high", status_code=200, response={"ok": True})
        result = map_execution(
            _execution({"High": [_task(index=0)]}),
            emitted,
            _test(),
            workflow_id="w1",
            external_calls=[call],
        )
        assert result.external_calls == [call]

    def test_emitter_warnings_reach_the_result(self, emitted):
        result = map_execution(_execution({}), emitted, _test(), workflow_id="w1")
        assert result.warnings == emitted.warnings


class TestApprovals:
    def test_approval_nodes_that_ran_are_reported(self):
        workflow = Workflow(
            name="Approval",
            source_format=SourceFormat.GENERIC_JSON,
            source_type=SourceType.HUMAN,
            nodes=[
                Node(id="start", name="Start", type=NodeType.TRIGGER),
                Node(id="approve", name="Approve", type=NodeType.HUMAN_APPROVAL),
            ],
            edges=[Edge(id="e0", source="start", target="approve")],
        )
        emitted = N8nEmitter().emit(workflow, run_token="t")
        execution = _execution({"Start": [_task(index=0)], "Approve": [_task(index=1)]})
        result = map_execution(execution, emitted, _test(), workflow_id="w1")
        assert result.approval_requests == ["approve"]


class TestRecordedExecutions:
    """Against real n8n 2.38.7 output, so the synthetic payloads above cannot drift."""

    def test_branching_fixture_has_the_fields_the_mapper_relies_on(self):
        execution = _load("execution-branching.json")
        run_data = execution["data"]["resultData"]["runData"]
        downstream = run_data["IF Amount"][0]
        assert downstream["source"][0]["previousNode"] == "Webhook"
        assert downstream["source"][0]["previousNodeOutput"] == 0
        assert "executionIndex" in downstream
        assert "Low Path" not in run_data, "the untaken branch must be absent from runData"

    def test_error_output_fixture_shows_the_success_reporting_trap(self):
        execution = _load("execution-error-output.json")
        task = execution["data"]["resultData"]["runData"]["Flaky Call"][0]
        assert task["executionStatus"] == "success"
        assert "error" not in task
        assert task["data"]["main"][1][0]["json"]["error"]["message"]

    def test_stop_on_error_fixture_carries_a_task_error(self):
        execution = _load("execution-stop-on-error.json")
        task = execution["data"]["resultData"]["runData"]["Flaky Call"][0]
        assert task["executionStatus"] == "error"
        assert task["error"]["message"]
        assert execution["status"] == "error"
        assert execution["finished"] is False

    def test_no_fixture_reports_a_retry_count(self):
        """All three ran with maxTries: 3; a single taskData each is why retries come from the mock."""
        for name in ("execution-error-output.json", "execution-stop-on-error.json"):
            run_data = _load(name)["data"]["resultData"]["runData"]
            assert len(run_data["Flaky Call"]) == 1

    def test_mapper_runs_against_recorded_output_without_crashing(self):
        """The mapper must tolerate a workflow it did not emit - every node reads as unknown."""
        emitted = N8nEmitter().emit(_branching_workflow(), run_token="t")
        result = map_execution(_load("execution-branching.json"), emitted, _test(), workflow_id="w1")
        assert result.execution_order == []
        assert result.status == TestRunStatus.PASSED
