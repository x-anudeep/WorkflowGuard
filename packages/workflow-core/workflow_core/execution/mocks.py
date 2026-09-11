"""Per-run mock state for n8n executions.

When a test runs, its workflow is compiled to n8n with every integration node's URL rewritten
to point back at this process. This registry holds what those endpoints should answer with,
and records what they were actually asked.

The call log is not a debugging aid, it is a result source. Two fields of `SimulationResult`
can only come from here:

* ``external_calls`` - the request and response for each integration node. Reconstructing these
  from n8n's run data would mean re-deriving what the HTTP node sent; the mock saw it directly.
* ``retries`` - n8n reports **no** attempt count. With ``retryOnFail`` and ``maxTries: 3`` a
  failing node still produces exactly one ``taskData`` entry (verified against n8n 2.38.7).
  The mock, however, is hit once per attempt, so hits-minus-one is the retry count.

State is in-process and deliberately so: n8n calls back into whatever process serves these
endpoints. That makes the registry **incompatible with more than one worker process** - a run
opened in worker A is invisible to worker B. Guarded by ``MockRegistry.close`` in a finally,
plus an age-based sweep, so a crashed run cannot leak entries forever.

It lives here rather than in the API because it is execution-layer state, not transport: the
engine opens and closes runs against it directly, and the FastAPI router in
``workflowguard_api.api.mocks`` is only the HTTP surface over it. Keeping it here is also what
lets an integration harness serve the same registry the engine is writing to.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from workflow_core.testing.models import FailureInjection, FailureType, MockIntegration, WorkflowTest

__all__ = ["MockCall", "MockRegistry", "MockResponse", "RunMocks", "mock_registry"]

#: How a simulated failure presents over HTTP. The point is that n8n sees a *real* failure -
#: a 429 really is a 429 - so the workflow's own error handling runs for real rather than
#: being modelled.
_FAILURE_STATUS = {
    FailureType.RATE_LIMIT: 429,
    FailureType.HTTP_500: 500,
    FailureType.AUTHORIZATION: 401,
    FailureType.UNAVAILABLE: 503,
}

_FAILURE_MESSAGE = {
    FailureType.TIMEOUT: "Simulated timeout.",
    FailureType.RATE_LIMIT: "Simulated HTTP 429/rate limit.",
    FailureType.HTTP_500: "Simulated HTTP 500.",
    FailureType.AUTHORIZATION: "Simulated authorization failure.",
    FailureType.UNAVAILABLE: "Simulated dependency unavailable.",
    FailureType.MALFORMED_OUTPUT: "Simulated malformed output.",
}

#: A run left open this long is assumed abandoned. Generous, because an execution may legitimately
#: sit at a slow node, but bounded so a crash cannot leak entries for the life of the process.
_MAX_RUN_AGE_SECONDS = 3600.0

#: How long a TIMEOUT injection stalls for. It only has to outlast the caller's own request
#: timeout - the emitter gives redirected calls a short one - so this is bounded rather than
#: arbitrarily long: every retry of a timing-out node waits this out.
_TIMEOUT_DELAY_SECONDS = 10.0


@dataclass
class MockCall:
    """One request the mock actually received."""

    node_id: str
    occurrence: int
    request: dict[str, Any]
    response: Any
    status_code: int
    latency_ms: int
    error: str | None = None


@dataclass
class MockResponse:
    """What the router should send back."""

    status_code: int
    body: Any
    delay_seconds: float = 0.0
    #: When set, the body is returned as-is rather than JSON-encoded, so a malformed-output
    #: injection can send something that is genuinely not JSON.
    raw_text: str | None = None


@dataclass
class RunMocks:
    """Everything one run needs, plus what it has been asked so far."""

    run_token: str
    mocks: dict[str, MockIntegration] = field(default_factory=dict)
    failures: dict[str, list[FailureInjection]] = field(default_factory=dict)
    occurrences: dict[str, int] = field(default_factory=dict)
    calls: list[MockCall] = field(default_factory=list)
    opened_at: float = field(default_factory=time.monotonic)

    def retries_by_node(self) -> dict[str, int]:
        """Attempts beyond the first, per node - the only place this is observable."""
        counts: dict[str, int] = {}
        for call in self.calls:
            counts[call.node_id] = counts.get(call.node_id, 0) + 1
        return {node_id: count - 1 for node_id, count in counts.items() if count > 1}


class MockRegistry:
    """Thread-safe store of open runs.

    n8n executes nodes concurrently, so several requests for one run can land at once; the lock
    guards the occurrence counters, which decide whether an injected failure fires.
    """

    def __init__(self) -> None:
        self._runs: dict[str, RunMocks] = {}
        self._lock = threading.Lock()

    def open(self, run_token: str, test: WorkflowTest) -> RunMocks:
        run = RunMocks(
            run_token=run_token,
            mocks={mock.node_id: mock for mock in test.mocked_integrations},
            failures=_group_failures(test.failure_injections),
        )
        with self._lock:
            self._sweep_locked()
            self._runs[run_token] = run
        return run

    def close(self, run_token: str) -> RunMocks | None:
        with self._lock:
            return self._runs.pop(run_token, None)

    def get(self, run_token: str) -> RunMocks | None:
        with self._lock:
            return self._runs.get(run_token)

    def respond(self, run_token: str, node_id: str, request: dict[str, Any]) -> MockResponse | None:
        """Answer one call, recording it. None when the run is unknown.

        An unknown run is a real signal, not a nuisance: it means an emitted workflow outlived
        the run that created it, so the caller should 404 rather than invent a response.
        """
        with self._lock:
            run = self._runs.get(run_token)
            if run is None:
                return None
            occurrence = run.occurrences.get(node_id, 0) + 1
            run.occurrences[node_id] = occurrence
            injection = _injection_for(run, node_id, occurrence)
            mock = run.mocks.get(node_id)

        response = _build_response(injection, mock)
        with self._lock:
            run.calls.append(
                MockCall(
                    node_id=node_id,
                    occurrence=occurrence,
                    request=request,
                    response=response.raw_text if response.raw_text is not None else response.body,
                    status_code=response.status_code,
                    latency_ms=int(response.delay_seconds * 1000),
                    error=_FAILURE_MESSAGE.get(FailureType(injection.failure_type)) if injection else None,
                )
            )
        return response

    def _sweep_locked(self) -> None:
        cutoff = time.monotonic() - _MAX_RUN_AGE_SECONDS
        for token in [t for t, run in self._runs.items() if run.opened_at < cutoff]:
            del self._runs[token]


def _group_failures(injections: list[FailureInjection]) -> dict[str, list[FailureInjection]]:
    grouped: dict[str, list[FailureInjection]] = {}
    for injection in injections:
        grouped.setdefault(injection.node_id, []).append(injection)
    return grouped


def _injection_for(run: RunMocks, node_id: str, occurrence: int) -> FailureInjection | None:
    return next(
        (item for item in run.failures.get(node_id, []) if item.occurrence == occurrence),
        None,
    )


def _build_response(injection: FailureInjection | None, mock: MockIntegration | None) -> MockResponse:
    if injection is not None:
        failure_type = FailureType(injection.failure_type)
        if failure_type == FailureType.TIMEOUT:
            # Sleeping past the node's own timeout is what makes this a real timeout rather
            # than a described one: n8n's HTTP node aborts the request itself.
            return MockResponse(
                status_code=504,
                body={"error": _FAILURE_MESSAGE[failure_type]},
                delay_seconds=float(injection.metadata.get("delay_seconds") or _TIMEOUT_DELAY_SECONDS),
            )
        if failure_type == FailureType.MALFORMED_OUTPUT:
            return MockResponse(status_code=200, body=None, raw_text="{not valid json,,,")
        status = _FAILURE_STATUS.get(failure_type, 500)
        return MockResponse(status_code=status, body={"error": _FAILURE_MESSAGE[failure_type]})

    if mock is not None:
        body = mock.response if isinstance(mock.response, dict) else {"result": mock.response}
        if mock.error:
            return MockResponse(
                status_code=mock.status_code or 500,
                body={"error": mock.error},
                delay_seconds=mock.latency_ms / 1000,
            )
        return MockResponse(
            status_code=mock.status_code or 200,
            body=body,
            delay_seconds=mock.latency_ms / 1000,
        )

    # No mock configured. The simulator answered unmocked integration nodes with a bland
    # success, and matching that keeps a test written against the simulator meaningful.
    return MockResponse(status_code=200, body={"ok": True, "mocked": True})


#: Process-wide, because the router and the execution engine must see the same runs.
mock_registry = MockRegistry()
