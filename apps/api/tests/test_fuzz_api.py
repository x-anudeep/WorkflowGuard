from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from workflow_core.fuzzing.models import FuzzCase, FuzzStrategy
from workflow_core.testing.models import FailureInjection, FailureType

from workflowguard_api.ai.errors import AIProviderError
from workflowguard_api.ai.fuzzing import (
    FuzzGenerationProvider,
    StaticMockFuzzGenerationProvider,
    fuzz_provider_from_settings,
)
from workflowguard_api.core.config import Settings
from workflowguard_api.db.session import get_db
from workflowguard_api.services.fuzzing import FuzzService

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "examples"
PROMPT = (
    "Read invoices from Gmail, extract invoice information, require human approval when the amount "
    "exceeds $10,000, then save approved invoices to SAP."
)


def _upload(client: TestClient) -> dict:
    path = EXAMPLES / "json" / "valid-workflow.json"
    response = client.post(
        "/api/workflows/upload",
        data={"source_type": "ai_generated", "source_prompt": PROMPT},
        files={"file": ("valid-workflow.json", path.read_bytes(), "application/json")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_fuzz_campaign_runs_and_persists_without_an_ai_key(client: TestClient) -> None:
    workflow = _upload(client)

    response = client.post(f"/api/workflows/{workflow['id']}/fuzz", json={"use_ai": True})
    assert response.status_code == 200, response.text
    run = response.json()

    # No provider is configured, so the deterministic corpus must carry the campaign.
    assert run["ai_metadata"]["ai_status"] == "unavailable_fallback"
    assert run["generated_by"] == "SYSTEM"
    assert run["total_cases"] > 0
    assert run["cases"]
    assert 0 <= run["robustness_score"] <= 100
    verdicts = {case["verdict"] for case in run["cases"]}
    assert verdicts <= {"handled", "unhandled_crash", "silent_success", "hung", "not_triggered"}

    history = client.get(f"/api/workflows/{workflow['id']}/fuzz")
    assert history.status_code == 200
    assert len(history.json()) == 1

    latest = client.get(f"/api/workflows/{workflow['id']}/fuzz/latest")
    assert latest.status_code == 200
    assert latest.json()["id"] == run["id"]

    detail = client.get(f"/api/workflows/{workflow['id']}/fuzz/{run['id']}")
    assert detail.status_code == 200
    assert detail.json()["seed"] == run["seed"]


def test_evaluation_blends_reliability_only_after_a_campaign(client: TestClient) -> None:
    workflow = _upload(client)

    before = client.post(f"/api/workflows/{workflow['id']}/evaluate", json={"use_ai": False})
    assert before.status_code == 200, before.text
    reliability_before = _reliability(before.json())
    assert "fuzz_robustness" not in reliability_before["calculation"]

    fuzz = client.post(f"/api/workflows/{workflow['id']}/fuzz", json={"use_ai": False})
    assert fuzz.status_code == 200, fuzz.text
    robustness = fuzz.json()["robustness_score"]

    after = client.post(f"/api/workflows/{workflow['id']}/evaluate", json={"use_ai": False})
    assert after.status_code == 200, after.text
    reliability_after = _reliability(after.json())
    calculation = reliability_after["calculation"]

    assert calculation["fuzz_robustness"] == robustness
    expected = round(0.6 * calculation["penalty_score"] + 0.4 * robustness)
    assert reliability_after["score"] == expected
    # Fuzz findings also add penalties, so the findings-based term is at or below the
    # pre-campaign score - measured fragility is never allowed to raise reliability.
    assert calculation["penalty_score"] <= reliability_before["score"]
    assert reliability_after["score"] <= reliability_before["score"]


def test_fuzz_findings_reach_the_evaluation(client: TestClient) -> None:
    workflow = _upload(client)
    client.post(f"/api/workflows/{workflow['id']}/fuzz", json={"use_ai": False})

    evaluation = client.post(f"/api/workflows/{workflow['id']}/evaluate", json={"use_ai": False}).json()
    fuzz_findings = [f for f in evaluation["findings"] if f["rule_id"].startswith("WG-FUZZ-")]

    assert fuzz_findings
    assert all(finding["dimension"] == "reliability" for finding in fuzz_findings)
    # Every finding must carry the seed needed to reproduce it.
    assert all(finding["metadata"].get("fuzz_seed") is not None for finding in fuzz_findings)


def test_ai_cases_are_added_on_top_of_the_deterministic_corpus(client: TestClient) -> None:
    workflow = _upload(client)
    detail = client.get(f"/api/workflows/{workflow['id']}").json()
    node_id = detail["versions"][0]["nodes"][0]["node_id"] if detail.get("versions") else None

    mock_case = FuzzCase(
        name="AI: double charge on retry",
        description="Model-proposed attack on payment idempotency.",
        strategy=FuzzStrategy.FAILURE_INJECTION,
        input_data={"amount": 100},
        failure_injections=(
            [FailureInjection(node_id=node_id, failure_type=FailureType.TIMEOUT)] if node_id else []
        ),
        targeted_node_ids=[node_id] if node_id else [],
    )
    provider = StaticMockFuzzGenerationProvider([mock_case])

    db = next(client.app.dependency_overrides[get_db]())
    service = FuzzService(db, ai_provider=provider)
    run = service.run_campaign(_uuid(workflow["id"]), use_ai=True)

    assert run.ai_metadata["ai_status"] == "used"
    assert run.ai_metadata["ai_cases"] == "1"
    assert run.generated_by == "AI"
    names = {case.name for case in run.cases}
    assert "AI: double charge on retry" in names
    # The deterministic corpus is not replaced by the model's suggestions.
    assert len(names) > 1


def test_provider_error_falls_back_to_the_deterministic_corpus(client: TestClient) -> None:
    workflow = _upload(client)

    class ExplodingProvider(FuzzGenerationProvider):
        provider_name = "groq"
        model_name = "openai/gpt-oss-120b"

        def generate_cases(self, workflow, requirement_spec, *, max_cases):
            raise AIProviderError("Groq rate limit was reached.")

    db = next(client.app.dependency_overrides[get_db]())
    run = FuzzService(db, ai_provider=ExplodingProvider()).run_campaign(_uuid(workflow["id"]))

    assert run.ai_metadata["ai_status"] == "error_fallback"
    assert "rate limit" in run.ai_metadata["reason"]
    assert run.total_cases > 0


def test_groq_is_a_supported_provider() -> None:
    settings = Settings(ai_provider="groq", ai_api_key="test-key", ai_model="openai/gpt-oss-120b")
    provider = fuzz_provider_from_settings(settings)
    assert provider.provider_name == "groq"
    assert provider.model_name == "openai/gpt-oss-120b"


def _reliability(evaluation: dict) -> dict:
    return next(score for score in evaluation["dimension_scores"] if score["dimension"] == "reliability")


def _uuid(value: str) -> UUID:
    return UUID(value)
