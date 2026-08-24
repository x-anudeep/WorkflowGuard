from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from workflow_core.evaluation import DeterministicRequirementExtractor, RequirementSpec

from workflowguard_api.ai.providers import AIProviderError, MalformedAIResponse, StaticMockAIProvider
from workflowguard_api.services.evaluations import EvaluationService

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "examples"
PROMPT = (
    "Read invoices from Gmail, extract invoice information, require human approval when the amount exceeds $10,000, "
    "then save approved invoices to SAP."
)


def _upload_with_prompt(client: TestClient) -> dict:
    path = EXAMPLES / "json" / "valid-workflow.json"
    response = client.post(
        "/api/workflows/upload",
        data={"source_type": "ai_generated", "source_prompt": PROMPT},
        files={"file": ("valid-workflow.json", path.read_bytes(), "application/json")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_evaluate_endpoint_works_without_ai_key(client: TestClient) -> None:
    workflow = _upload_with_prompt(client)
    response = client.post(f"/api/workflows/{workflow['id']}/evaluate", json={"use_ai": True})
    assert response.status_code == 200, response.text
    evaluation = response.json()
    assert evaluation["ai_metadata"]["ai_status"] == "unavailable_fallback"
    assert evaluation["requirement_spec"]
    assert evaluation["dimension_scores"]

    history = client.get(f"/api/workflows/{workflow['id']}/evaluations")
    assert history.status_code == 200
    assert len(history.json()) == 1

    requirements = client.get(f"/api/workflows/{workflow['id']}/requirements")
    assert requirements.status_code == 200
    assert requirements.json()["spec"]["source_prompt"] == PROMPT


def test_evaluation_history_is_preserved(client: TestClient) -> None:
    workflow = _upload_with_prompt(client)
    first = client.post(f"/api/workflows/{workflow['id']}/evaluate", json={"use_ai": False})
    second = client.post(f"/api/workflows/{workflow['id']}/evaluate", json={"use_ai": False})
    assert first.status_code == 200
    assert second.status_code == 200
    history = client.get(f"/api/workflows/{workflow['id']}/evaluations").json()
    assert len(history) == 2
    assert history[0]["id"] != history[1]["id"]


def test_evaluation_service_accepts_mock_ai_provider(client: TestClient) -> None:
    workflow = _upload_with_prompt(client)
    spec = DeterministicRequirementExtractor().extract(PROMPT)
    db_generator = next(iter(client.app.dependency_overrides.values()))()
    db = next(db_generator)
    try:
        run = EvaluationService(db, ai_provider=StaticMockAIProvider(spec)).evaluate(UUID(workflow["id"]), use_ai=True)
        assert run.ai_provider == "mock"
        assert run.requirement_spec is not None
    finally:
        db_generator.close()


class BrokenProvider(StaticMockAIProvider):
    provider_name = "broken"

    def extract_requirements(self, prompt: str) -> RequirementSpec:
        raise MalformedAIResponse("not valid json")


class RateLimitedProvider(StaticMockAIProvider):
    provider_name = "limited"

    def extract_requirements(self, prompt: str) -> RequirementSpec:
        raise AIProviderError("rate limit")


def test_malformed_ai_output_falls_back_to_deterministic(client: TestClient) -> None:
    workflow = _upload_with_prompt(client)
    spec = DeterministicRequirementExtractor().extract(PROMPT)
    db_generator = next(iter(client.app.dependency_overrides.values()))()
    db = next(db_generator)
    try:
        run = EvaluationService(db, ai_provider=BrokenProvider(spec)).evaluate(UUID(workflow["id"]), use_ai=True)
        assert run.ai_metadata["ai_status"] == "error_fallback"
    finally:
        db_generator.close()


def test_ai_provider_error_falls_back_to_deterministic(client: TestClient) -> None:
    workflow = _upload_with_prompt(client)
    spec = DeterministicRequirementExtractor().extract(PROMPT)
    db_generator = next(iter(client.app.dependency_overrides.values()))()
    db = next(db_generator)
    try:
        run = EvaluationService(db, ai_provider=RateLimitedProvider(spec)).evaluate(UUID(workflow["id"]), use_ai=True)
        assert run.ai_metadata["ai_status"] == "error_fallback"
    finally:
        db_generator.close()
