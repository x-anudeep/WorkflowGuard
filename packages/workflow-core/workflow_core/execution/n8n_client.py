"""A thin client for the n8n REST API, covering exactly what a test run needs.

Shaped by what the step-0 spike found on n8n 2.38.7:

* ``POST /workflows/{id}/activate`` is **deprecated**; 2.x uses ``publish``/``unpublish``, and a
  workflow is not active until published.
* Publish returns **409** when another workflow already claims the same webhook path, which is
  why every run gets its own token.
* The API key needs ``workflow:activate`` as well as the obvious CRUD scopes; without it every
  publish fails with a bare ``403 Forbidden`` and no explanation.
* There is no "run this workflow now" endpoint. Execution is triggered by POSTing to the
  workflow's own webhook, which is why the emitter injects one.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

__all__ = ["N8nClient", "N8nError", "N8nUnavailable"]

#: n8n keeps writing an execution for a moment after the webhook responds, so a fetch straight
#: after the trigger can miss it or catch it mid-write.
_DEFAULT_POLL_INTERVAL = 0.25


class N8nError(RuntimeError):
    """The engine rejected a request, or answered in a way a run cannot continue from."""


class N8nUnavailable(N8nError):
    """The engine could not be reached at all - distinct from it refusing a request."""


class N8nClient:
    """Synchronous n8n API client.

    Synchronous on purpose: it is called from the same place the simulator used to run, inside
    a request handler that already holds a database session, and an async client there would
    mean threading an event loop through `WorkflowTestRunner` for no gain.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        *,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds

    # -- workflow lifecycle --------------------------------------------------------------

    def create_workflow(self, workflow_json: dict[str, Any]) -> str:
        """Create a workflow and return its id."""
        body = self._request("POST", "/api/v1/workflows", json=workflow_json)
        workflow_id = body.get("id")
        if not workflow_id:
            raise N8nError(f"n8n accepted the workflow but returned no id: {body!r}")
        return str(workflow_id)

    def publish(self, workflow_id: str) -> None:
        """Publish (in n8n 1.x terms, activate) so the production webhook accepts calls."""
        try:
            self._request("POST", f"/api/v1/workflows/{workflow_id}/publish")
        except N8nError as exc:
            if "409" in str(exc):
                raise N8nError(
                    "n8n refused to publish: another workflow already claims this webhook path. "
                    "Run tokens must be unique per run."
                ) from exc
            raise

    def unpublish(self, workflow_id: str) -> None:
        self._request("POST", f"/api/v1/workflows/{workflow_id}/unpublish", tolerate_failure=True)

    def delete_workflow(self, workflow_id: str) -> None:
        self._request("DELETE", f"/api/v1/workflows/{workflow_id}", tolerate_failure=True)

    def list_workflows(self, *, name_prefix: str | None = None) -> list[dict[str, Any]]:
        body = self._request("GET", "/api/v1/workflows?limit=250")
        items = body.get("data") or []
        if name_prefix:
            items = [item for item in items if str(item.get("name", "")).startswith(name_prefix)]
        return items

    def sweep(self, name_prefix: str) -> int:
        """Delete leftover workflows from runs that never cleaned up. Returns how many."""
        removed = 0
        for item in self.list_workflows(name_prefix=name_prefix):
            workflow_id = str(item.get("id") or "")
            if not workflow_id:
                continue
            self.unpublish(workflow_id)
            self.delete_workflow(workflow_id)
            removed += 1
        return removed

    # -- execution ------------------------------------------------------------------------

    def trigger(self, webhook_path: str, payload: dict[str, Any]) -> tuple[int, Any]:
        """POST to the workflow's webhook. Returns the status and body.

        The emitted webhook answers on receipt, so this returns as soon as n8n has accepted the
        run rather than when the workflow finishes; `wait_for_execution` picks it up from there.

        A non-2xx is not raised. The execution record is the authority on what happened, and a
        trigger that was accepted tells us nothing about whether the workflow succeeded.
        """
        url = f"{self.base_url}/webhook/{webhook_path.lstrip('/')}"
        try:
            response = httpx.post(url, json=payload, timeout=self.timeout_seconds)
        except httpx.RequestError as exc:
            raise N8nUnavailable(f"Could not reach the n8n webhook at {url}: {exc}") from exc
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, response.text

    def wait_for_execution(
        self, workflow_id: str, *, timeout_seconds: float = 60.0
    ) -> dict[str, Any] | None:
        """The workflow's most recent finished execution, with data. None if none appears.

        Polls because n8n finishes writing the execution slightly after the webhook responds;
        an immediate read can return nothing or a record still marked running.
        """
        deadline = time.monotonic() + timeout_seconds
        while True:
            execution = self.latest_execution(workflow_id)
            if execution is not None and execution.get("status") not in {"running", "new", "waiting"}:
                return execution
            if time.monotonic() >= deadline:
                return execution
            time.sleep(self.poll_interval_seconds)

    def delete_execution(self, execution_id: str) -> None:
        """Drop an execution once its result has been mapped.

        n8n stores every execution with its full data. We copy what we need into a
        `SimulationResult`, which is persisted in WorkflowGuard's own database, so n8n's copy is
        redundant the moment it has been read - and a test suite produces hundreds of them.
        Retention settings bound this eventually; deleting as we go bounds it immediately.
        """
        self._request("DELETE", f"/api/v1/executions/{execution_id}", tolerate_failure=True)

    def latest_execution(self, workflow_id: str) -> dict[str, Any] | None:
        body = self._request(
            "GET",
            f"/api/v1/executions?includeData=true&workflowId={workflow_id}&limit=1",
        )
        items = body.get("data") or []
        return items[0] if items else None

    def health(self) -> bool:
        try:
            response = httpx.get(f"{self.base_url}/healthz", timeout=5.0)
        except httpx.RequestError:
            return False
        return response.status_code == 200

    # -- plumbing ---------------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        tolerate_failure: bool = False,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-N8N-API-KEY"] = self.api_key
        try:
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                json=json,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except httpx.RequestError as exc:
            if tolerate_failure:
                return {}
            raise N8nUnavailable(f"Could not reach n8n at {self.base_url}: {exc}") from exc

        if response.status_code >= 400:
            if tolerate_failure:
                # Cleanup is best-effort. A failure here must never mask the real result of the
                # run, and the sweep will catch whatever is left behind.
                return {}
            raise N8nError(_explain(method, path, response))

        try:
            return response.json()
        except ValueError:
            return {}


def _explain(method: str, path: str, response: httpx.Response) -> str:
    detail = response.text[:300]
    message = f"n8n returned {response.status_code} for {method} {path}: {detail}"
    if response.status_code == 403:
        message += (
            " -- a bare 403 from this API usually means the API key is missing a scope; "
            "publishing needs 'workflow:activate'."
        )
    return message
