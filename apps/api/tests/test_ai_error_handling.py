"""A provider that answers with an error code must contribute no tests.

Generated tests feed coverage and the quality gate, so a half-built or crashed AI batch would
be charged to the workflow's score. On any provider failure the deterministic suite is kept
and nothing from the AI is added.
"""

from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from workflow_core.canonical.models import Workflow
from workflow_core.evaluation.models import RequirementSpec

from workflowguard_api.ai.errors import AIProviderError, MalformedAIResponse
from workflowguard_api.ai.groq_client import (
    AIRateLimited,
    _is_rate_limit,
    _rate_limited,
    response_json,
)
from workflowguard_api.ai.test_generation import TestGenerationProvider
from workflowguard_api.db.session import get_db
from workflowguard_api.services.testing import WorkflowTestingService

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "examples"


class _FailingProvider(TestGenerationProvider):
    provider_name = "groq"
    model_name = "openai/gpt-oss-120b"

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def generate_tests(self, workflow: Workflow, requirement_spec: RequirementSpec | None):
        raise self.exc


def _upload(client: TestClient) -> dict:
    path = EXAMPLES / "json" / "valid-workflow.json"
    response = client.post(
        "/api/workflows/upload",
        data={"source_type": "human"},
        files={"file": ("valid-workflow.json", path.read_bytes(), "application/json")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_non_json_error_body_is_a_provider_error_not_a_crash() -> None:
    """A gateway returning 413 sends HTML, not JSON. Parsing it must not escape the boundary."""
    response = httpx.Response(413, text="<html><body>Request Entity Too Large</body></html>")
    with pytest.raises(MalformedAIResponse):
        response_json(response)


@pytest.mark.parametrize(
    "exc",
    [
        AIProviderError("Groq returned HTTP 413."),
        AIProviderError("Groq rate limit was reached."),
        MalformedAIResponse("AI provider returned a non-JSON response body."),
        RuntimeError("provider blew up in an unexpected way"),
    ],
)
def test_failing_provider_adds_no_tests_and_keeps_the_deterministic_suite(
    client: TestClient, exc: Exception
) -> None:
    workflow = _upload(client)
    db = next(client.app.dependency_overrides[get_db]())
    service = WorkflowTestingService(db, ai_provider=_FailingProvider(exc))

    result, records = service.generate_tests(UUID(workflow["id"]), use_ai=True, replace_existing=True)

    assert records, "the deterministic suite must survive a provider failure"
    assert all(str(record.generated_by) != "AI" for record in records)
    assert any("deterministic tests were kept" in warning for warning in result.warnings)


def test_the_http_status_reaches_the_warning(client: TestClient) -> None:
    """Whoever reads the warning needs to know it was a 413, not a generic failure."""
    workflow = _upload(client)
    db = next(client.app.dependency_overrides[get_db]())
    service = WorkflowTestingService(db, ai_provider=_FailingProvider(AIProviderError("Groq returned HTTP 413.")))

    result, _records = service.generate_tests(UUID(workflow["id"]), use_ai=True, replace_existing=True)
    assert any("413" in warning for warning in result.warnings)


def _groq_response(status: int, body: dict, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        json=body,
        headers=headers or {},
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )


def test_groq_reports_its_token_rate_limit_as_413_not_429() -> None:
    """The bug this guards.

    Groq answers a tokens-per-minute overage with HTTP 413 and code `rate_limit_exceeded`.
    Reading 413 as "payload too large" sent everyone looking at request size when the cause
    was a rate limit - and vice versa, so both have to be distinguishable.
    """
    body = {
        "error": {
            "message": (
                "Request too large for model `openai/gpt-oss-120b` in organization `org_x` "
                "service tier `on_demand` on tokens per minute (TPM): Limit 8000, "
                "Requested 9596, please reduce your message size and try again."
            ),
            "type": "tokens",
            "code": "rate_limit_exceeded",
        }
    }
    response = _groq_response(413, body, {"retry-after": "12"})

    error = None
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        assert _is_rate_limit(exc.response)
        error = _rate_limited(exc.response, "Groq token-per-minute limit was reached.")
        assert isinstance(error, AIRateLimited)

    assert error is not None
    assert error.retry_after == 12
    # A single request larger than the whole per-minute budget can never succeed by waiting.
    assert error.fits_limit is False
    assert "9596" in str(error) and "8000" in str(error)


def test_a_genuine_size_rejection_is_not_called_a_rate_limit() -> None:
    response = _groq_response(413, {"error": {"message": "Payload too large", "type": "invalid_request_error"}})
    assert _is_rate_limit(response) is False


def test_ai_rate_limit_is_still_a_provider_error_so_callers_fall_back() -> None:
    assert issubclass(AIRateLimited, AIProviderError)
