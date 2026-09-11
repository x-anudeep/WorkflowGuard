"""The mock endpoints emitted workflows call instead of their real integrations.

Two things here are load-bearing beyond "the mock answers":

* An injected failure must present as a *real* HTTP failure, so the workflow's own error
  handling runs for real rather than being modelled.
* The call log is the only source for `SimulationResult.retries` - n8n reports no attempt
  count at all (verified against 2.38.7), but the mock is hit once per attempt.
"""

import json
import time

import pytest
from workflow_core.execution.mocks import MockRegistry, mock_registry
from workflow_core.testing.models import (
    FailureInjection,
    FailureType,
    MockIntegration,
    WorkflowTest,
)


def _test(mocks=None, failures=None) -> WorkflowTest:
    return WorkflowTest(
        name="t",
        description="d",
        mocked_integrations=mocks or [],
        failure_injections=failures or [],
    )


@pytest.fixture()
def registry() -> MockRegistry:
    return MockRegistry()


class TestMockedResponses:
    def test_configured_response_is_returned(self, registry):
        registry.open("run1", _test(mocks=[MockIntegration(node_id="api", response={"id": 7})]))
        response = registry.respond("run1", "api", {})
        assert response.status_code == 200
        assert response.body == {"id": 7}

    def test_non_dict_response_is_wrapped(self, registry):
        registry.open("run1", _test(mocks=[MockIntegration(node_id="api", response="hello")]))
        assert registry.respond("run1", "api", {}).body == {"result": "hello"}

    def test_unmocked_node_gets_a_bland_success(self, registry):
        """Matches what the simulator returned, so simulator-era tests stay meaningful."""
        registry.open("run1", _test())
        response = registry.respond("run1", "api", {})
        assert response.status_code == 200
        assert response.body == {"ok": True, "mocked": True}

    def test_latency_becomes_a_real_delay(self, registry):
        registry.open("run1", _test(mocks=[MockIntegration(node_id="api", latency_ms=250)]))
        assert registry.respond("run1", "api", {}).delay_seconds == pytest.approx(0.25)


class TestFailureInjection:
    @pytest.mark.parametrize(
        ("failure_type", "expected_status"),
        [
            (FailureType.RATE_LIMIT, 429),
            (FailureType.HTTP_500, 500),
            (FailureType.AUTHORIZATION, 401),
            (FailureType.UNAVAILABLE, 503),
        ],
    )
    def test_each_failure_presents_as_its_real_status(self, registry, failure_type, expected_status):
        registry.open("run1", _test(failures=[FailureInjection(node_id="api", failure_type=failure_type)]))
        assert registry.respond("run1", "api", {}).status_code == expected_status

    def test_timeout_actually_waits(self, registry):
        """A timeout only tests timeout handling if the caller has to wait for it.

        It only has to outlast the caller's own request timeout, which the emitter keeps short
        for these redirected calls, so the stall is bounded - every retry waits it out.
        """
        registry.open(
            "run1",
            _test(failures=[FailureInjection(node_id="api", failure_type=FailureType.TIMEOUT)]),
        )
        delay = registry.respond("run1", "api", {}).delay_seconds
        assert delay >= 5.0

    def test_timeout_delay_is_configurable(self, registry):
        registry.open(
            "run1",
            _test(
                failures=[
                    FailureInjection(
                        node_id="api",
                        failure_type=FailureType.TIMEOUT,
                        metadata={"delay_seconds": 0.01},
                    )
                ]
            ),
        )
        assert registry.respond("run1", "api", {}).delay_seconds == pytest.approx(0.01)

    def test_malformed_output_returns_genuinely_invalid_json(self, registry):
        registry.open(
            "run1",
            _test(failures=[FailureInjection(node_id="api", failure_type=FailureType.MALFORMED_OUTPUT)]),
        )
        response = registry.respond("run1", "api", {})
        assert response.raw_text is not None
        with pytest.raises(ValueError):
            json.loads(response.raw_text)

    def test_injection_fires_only_on_its_declared_occurrence(self, registry):
        """`occurrence` is what makes "fail the second call, succeed the third" expressible."""
        registry.open(
            "run1",
            _test(
                mocks=[MockIntegration(node_id="api", response={"ok": 1})],
                failures=[
                    FailureInjection(node_id="api", failure_type=FailureType.HTTP_500, occurrence=2)
                ],
            ),
        )
        assert registry.respond("run1", "api", {}).status_code == 200
        assert registry.respond("run1", "api", {}).status_code == 500
        assert registry.respond("run1", "api", {}).status_code == 200

    def test_occurrences_are_counted_per_node(self, registry):
        registry.open(
            "run1",
            _test(failures=[FailureInjection(node_id="b", failure_type=FailureType.HTTP_500, occurrence=1)]),
        )
        assert registry.respond("run1", "a", {}).status_code == 200
        assert registry.respond("run1", "b", {}).status_code == 500


class TestCallLog:
    def test_retries_are_attempts_beyond_the_first(self, registry):
        """The only place retry counts exist - n8n's execution data has none."""
        run = registry.open("run1", _test())
        for _ in range(3):
            registry.respond("run1", "api", {})
        registry.respond("run1", "other", {})
        assert run.retries_by_node() == {"api": 2}

    def test_a_node_called_once_reports_no_retries(self, registry):
        run = registry.open("run1", _test())
        registry.respond("run1", "api", {})
        assert run.retries_by_node() == {}

    def test_the_log_records_what_external_calls_needs(self, registry):
        run = registry.open("run1", _test(mocks=[MockIntegration(node_id="api", response={"v": 1})]))
        registry.respond("run1", "api", {"method": "POST", "body": {"x": 2}})
        call = run.calls[0]
        assert call.node_id == "api"
        assert call.occurrence == 1
        assert call.request == {"method": "POST", "body": {"x": 2}}
        assert call.response == {"v": 1}
        assert call.status_code == 200

    def test_an_injected_failure_is_recorded_with_its_message(self, registry):
        run = registry.open(
            "run1",
            _test(failures=[FailureInjection(node_id="api", failure_type=FailureType.RATE_LIMIT)]),
        )
        registry.respond("run1", "api", {})
        assert "429" in run.calls[0].error


class TestRunLifecycle:
    def test_an_unknown_run_is_not_answered(self, registry):
        """A leaked workflow must not keep producing plausible results after its run ended."""
        assert registry.respond("ghost", "api", {}) is None

    def test_close_removes_the_run(self, registry):
        registry.open("run1", _test())
        assert registry.close("run1") is not None
        assert registry.respond("run1", "api", {}) is None

    def test_runs_are_isolated_from_each_other(self, registry):
        registry.open("a", _test(mocks=[MockIntegration(node_id="api", response={"from": "a"})]))
        registry.open("b", _test(mocks=[MockIntegration(node_id="api", response={"from": "b"})]))
        assert registry.respond("a", "api", {}).body == {"from": "a"}
        assert registry.respond("b", "api", {}).body == {"from": "b"}

    def test_abandoned_runs_are_swept(self, registry):
        registry.open("old", _test())
        registry.get("old").opened_at = time.monotonic() - 7200
        registry.open("new", _test())  # opening sweeps
        assert registry.get("old") is None
        assert registry.get("new") is not None


class TestRouter:
    def test_endpoint_answers_an_open_run(self, client):
        mock_registry.open("rt1", _test(mocks=[MockIntegration(node_id="api", response={"id": 9})]))
        try:
            response = client.post("/mock/rt1/api", json={"amount": 10})
            assert response.status_code == 200
            assert response.json() == {"id": 9}
        finally:
            mock_registry.close("rt1")

    def test_endpoint_404s_for_a_closed_run(self, client):
        assert client.post("/mock/nope/api", json={}).status_code == 404

    def test_request_body_reaches_the_call_log(self, client):
        run = mock_registry.open("rt2", _test())
        try:
            client.post("/mock/rt2/api", json={"amount": 10})
            assert run.calls[0].request["body"] == {"amount": 10}
            assert run.calls[0].request["method"] == "POST"
        finally:
            mock_registry.close("rt2")

    def test_injected_status_reaches_the_caller(self, client):
        mock_registry.open(
            "rt3",
            _test(failures=[FailureInjection(node_id="api", failure_type=FailureType.RATE_LIMIT)]),
        )
        try:
            assert client.post("/mock/rt3/api", json={}).status_code == 429
        finally:
            mock_registry.close("rt3")
