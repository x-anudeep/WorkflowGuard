"""The endpoints emitted workflows call instead of their real integrations.

Mounted outside the API prefix, at ``/mock/{run_token}/{node_id}``, because n8n reaches them
directly and they are not part of the public API surface.

This is what keeps real execution safe: an emitted workflow carries no credentials and every
`EXTERNAL_API`, `DATABASE`, `EMAIL` and `LLM` node has its URL rewritten to point here, so a
test run cannot reach a real endpoint even when the uploaded workflow names one.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse

from workflowguard_api.services.mock_registry import mock_registry

router = APIRouter(tags=["mocks"])

#: A run's own responses should never be cached by anything between n8n and here - two calls to
#: the same node are meant to be distinguishable, that is how retries are counted.
_NO_STORE = {"Cache-Control": "no-store"}


@router.api_route(
    "/mock/{run_token}/{node_id}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    summary="Mocked integration endpoint for an in-flight test run",
)
async def mock_endpoint(run_token: str, node_id: str, request: Request) -> Any:
    payload = await _read_payload(request)
    response = mock_registry.respond(
        run_token,
        node_id,
        {
            "method": request.method,
            "query": dict(request.query_params),
            "body": payload,
        },
    )
    if response is None:
        # The run is closed or never existed. Answering anyway would let a leaked workflow keep
        # producing plausible results long after the run it belonged to finished.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No open test run {run_token!r}; this mock endpoint is no longer active.",
        )

    if response.delay_seconds:
        # Genuinely wait. A timeout injection only tests the workflow's timeout handling if the
        # caller actually has to wait for it.
        await asyncio.sleep(response.delay_seconds)

    if response.raw_text is not None:
        return PlainTextResponse(
            response.raw_text,
            status_code=response.status_code,
            media_type="application/json",
            headers=_NO_STORE,
        )
    return JSONResponse(response.body, status_code=response.status_code, headers=_NO_STORE)


async def _read_payload(request: Request) -> Any:
    """Best-effort body decode; a mock must never fail because of how it was called."""
    raw = await request.body()
    if not raw:
        return None
    try:
        return await request.json()
    except (ValueError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")
