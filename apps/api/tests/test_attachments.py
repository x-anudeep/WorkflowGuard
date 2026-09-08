from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from workflow_core.evaluation.models import Confidence, RequirementMatch

from workflowguard_api.ai.alignment import AlignmentProvider, StaticMockAlignmentProvider
from workflowguard_api.db.session import get_db
from workflowguard_api.models.db import RequirementSpecificationRecord
from workflowguard_api.services.evaluations import EvaluationService

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "examples"
CORPUS = ROOT / "references" / "documents"
BRD = CORPUS / "C02_customer_onboarding_brd.md"
PROMPT = "Read invoices from Gmail, extract invoice information, then save approved invoices to SAP."


def _upload(client: TestClient, *, prompt: str | None = PROMPT) -> dict:
    path = EXAMPLES / "json" / "valid-workflow.json"
    data = {"source_type": "ai_generated"}
    if prompt:
        data["source_prompt"] = prompt
    response = client.post(
        "/api/workflows/upload",
        data=data,
        files={"file": ("valid-workflow.json", path.read_bytes(), "application/json")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _attach(client: TestClient, workflow_id: str, *, name: str = "brd.md", body: bytes | None = None) -> dict:
    body = body if body is not None else BRD.read_bytes()
    response = client.post(
        f"/api/workflows/{workflow_id}/attachments",
        files={"file": (name, body, "text/markdown")},
    )
    assert response.status_code == 201, response.text
    return response.json()


pytestmark = pytest.mark.skipif(not BRD.is_file(), reason="reference corpus not checked out")


def test_attachment_is_parsed_on_upload(client: TestClient) -> None:
    workflow = _upload(client)
    attachment = _attach(client, workflow["id"], name="C02_customer_onboarding_brd.md")

    assert attachment["kind"] == "brd"
    assert attachment["clause_count"] > 0
    assert attachment["size_bytes"] == BRD.stat().st_size

    listed = client.get(f"/api/workflows/{workflow['id']}/attachments")
    assert [item["id"] for item in listed.json()] == [attachment["id"]]

    detail = client.get(f"/api/attachments/{attachment['id']}").json()
    assert detail["raw_content"].startswith("# Business Requirements Document")
    assert detail["clauses"]
    assert any(section["anchor"] == "BR-1" for section in detail["sections"])


def test_unsupported_format_is_rejected(client: TestClient) -> None:
    workflow = _upload(client)
    response = client.post(
        f"/api/workflows/{workflow['id']}/attachments",
        files={"file": ("spec.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert response.status_code == 400
    assert ".md" in response.json()["detail"]


def test_attachment_on_missing_workflow_is_404(client: TestClient) -> None:
    response = client.post(
        "/api/workflows/00000000-0000-0000-0000-000000000000/attachments",
        files={"file": ("brd.md", b"# Requirements", "text/markdown")},
    )
    assert response.status_code == 404


def test_evaluation_without_attachments_is_unaffected(client: TestClient) -> None:
    """The optional path: a workflow with no documents scores exactly as it did before."""
    workflow = _upload(client)
    before = client.post(f"/api/workflows/{workflow['id']}/evaluate", json={"use_ai": False}).json()

    assert all(match.get("match_method", "deterministic") == "deterministic" for match in before["requirement_matches"])
    assert "match_status" not in before["ai_metadata"]


def test_document_requirements_reach_the_match_score(client: TestClient) -> None:
    workflow = _upload(client)
    baseline = client.post(f"/api/workflows/{workflow['id']}/evaluate", json={"use_ai": False}).json()
    baseline_count = len(baseline["requirement_matches"])

    _attach(client, workflow["id"], name="C02_customer_onboarding_brd.md")
    after = client.post(f"/api/workflows/{workflow['id']}/evaluate", json={"use_ai": False}).json()

    assert len(after["requirement_matches"]) > baseline_count
    db = next(client.app.dependency_overrides[get_db]())
    spec = db.get(RequirementSpecificationRecord, UUID(after["requirement_spec_id"]))
    assert spec.spec_json["metadata"]["sources"]["documents"][0]["kind"] == "brd"
    assert "C02_customer_onboarding_brd.md" in spec.source_prompt
    assert any(item["source"] == "document" for item in spec.spec_json["requirements"])

    # Without an AI matcher the document misses must not be scored as hard errors.
    alignment = next(s for s in after["dimension_scores"] if s["dimension"] == "prompt_alignment")
    assert alignment["calculation"]["findings"]["WARNING"] > 0
    assert any("without an AI provider" in limitation for limitation in after["limitations"])


def test_ai_matcher_verdicts_are_used(client: TestClient) -> None:
    workflow = _upload(client)
    _attach(client, workflow["id"], name="C02_customer_onboarding_brd.md")

    captured: dict[str, object] = {}

    class _Recording(AlignmentProvider):
        provider_name = "mock"
        model_name = "mock-alignment"

        def match_requirements(self, spec, workflow):  # noqa: ANN001
            captured["spec"] = spec
            return [
                RequirementMatch(
                    requirement_id=item.id,
                    requirement_text=item.text,
                    status="matched",
                    matched_node_ids=[workflow.nodes[0].id],
                    evidence="Mock matched everything.",
                    confidence=Confidence.HIGH,
                    match_method="ai:mock",
                )
                for item in spec.requirements
            ]

    db = next(client.app.dependency_overrides[get_db]())
    run = EvaluationService(db, alignment_provider=_Recording()).evaluate(UUID(workflow["id"]), use_ai=True)

    assert run.ai_metadata["match_status"] == "used"
    assert all(match["match_method"] == "ai:mock" for match in run.requirement_matches)
    assert all(match["status"] == "matched" for match in run.requirement_matches)
    assert any(item.source == "document" for item in captured["spec"].requirements)


def test_deleting_an_attachment_removes_its_requirements(client: TestClient) -> None:
    workflow = _upload(client)
    attachment = _attach(client, workflow["id"], name="C02_customer_onboarding_brd.md")
    with_document = client.post(f"/api/workflows/{workflow['id']}/evaluate", json={"use_ai": False}).json()

    assert client.delete(f"/api/attachments/{attachment['id']}").status_code == 204

    after = client.post(f"/api/workflows/{workflow['id']}/evaluate", json={"use_ai": False}).json()
    assert len(after["requirement_matches"]) < len(with_document["requirement_matches"])
    assert client.get(f"/api/workflows/{workflow['id']}/attachments").json() == []


def test_document_only_workflow_is_evaluated(client: TestClient) -> None:
    """A workflow with no prompt still gets an alignment score once a BRD is attached."""
    workflow = _upload(client, prompt=None)
    before = client.post(f"/api/workflows/{workflow['id']}/evaluate", json={"use_ai": False}).json()
    assert before["ai_metadata"]["ai_status"] == "skipped_no_requirements"
    assert before["requirement_matches"] == []

    _attach(client, workflow["id"], name="C02_customer_onboarding_brd.md")
    after = client.post(f"/api/workflows/{workflow['id']}/evaluate", json={"use_ai": False}).json()
    assert after["ai_metadata"]["ai_status"] == "documents_only"
    assert after["requirement_matches"]


def test_mock_provider_shape() -> None:
    provider = StaticMockAlignmentProvider([])
    assert provider.provider_name == "mock"


def test_match_method_survives_the_response_schema(client: TestClient) -> None:
    """The API response model must carry provenance, or the UI silently reports keyword matches."""
    workflow = _upload(client)
    _attach(client, workflow["id"], name="C02_customer_onboarding_brd.md")
    evaluated = client.post(f"/api/workflows/{workflow['id']}/evaluate", json={"use_ai": False}).json()

    assert evaluated["requirement_matches"]
    assert all("match_method" in match for match in evaluated["requirement_matches"])

    listed = client.get(f"/api/workflows/{workflow['id']}/evaluations").json()
    assert all("match_method" in match for match in listed[0]["requirement_matches"])
