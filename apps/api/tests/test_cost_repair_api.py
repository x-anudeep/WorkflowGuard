from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "examples"


def upload_workflow(client: TestClient) -> str:
    path = EXAMPLES / "json" / "valid-workflow.json"
    response = client.post(
        "/api/workflows/upload",
        data={"source_type": "ai_generated", "source_prompt": "Approve requests, then notify Slack."},
        files={"file": ("valid-workflow.json", path.read_bytes(), "application/json")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_pricing_and_cost_estimate_api(client: TestClient) -> None:
    workflow_id = upload_workflow(client)
    pricing = client.get("/api/pricing")
    assert pricing.status_code == 200
    assert pricing.json()

    estimate = client.post(
        f"/api/workflows/{workflow_id}/cost",
        json={"executions_per_day": 50, "average_input_tokens": 1000, "average_output_tokens": 250, "failure_retry_rate": 0.1},
    )
    assert estimate.status_code == 200, estimate.text
    body = estimate.json()
    assert body["monthly_cost"] == round(body["cost_per_run"] * 1500, 4)
    assert body["assumptions"]
    assert "line_items" in body


def test_repair_preview_reject_and_accept_creates_new_version(client: TestClient) -> None:
    workflow_id = upload_workflow(client)
    repair = client.post(
        f"/api/workflows/{workflow_id}/repairs/generate",
        json={"finding": {"rule_id": "WG-REL-001", "message": "Notify requester is missing retry handling."}},
    )
    assert repair.status_code == 200, repair.text
    proposal = repair.json()
    assert proposal["status"] == "proposed"
    assert "validation" in proposal["preview"]

    reject = client.post(f"/api/repairs/{proposal['id']}/reject", json={"reason": "Not desired"})
    assert reject.status_code == 200
    assert reject.json()["status"] == "rejected"

    second = client.post(f"/api/workflows/{workflow_id}/repairs/generate", json={"finding": {"message": "retry"}}).json()
    accept = client.post(f"/api/repairs/{second['id']}/accept")
    assert accept.status_code == 200, accept.text
    accepted = accept.json()
    assert accepted["status"] == "accepted"
    assert accepted["accepted_version_id"]

    versions = client.get(f"/api/workflows/{workflow_id}/versions")
    assert len(versions.json()) == 2


def test_version_compare_endpoint(client: TestClient) -> None:
    workflow_id = upload_workflow(client)
    proposal = client.post(f"/api/workflows/{workflow_id}/repairs/generate", json={"finding": {"message": "retry"}}).json()
    client.post(f"/api/repairs/{proposal['id']}/accept")
    compare = client.get(f"/api/workflows/{workflow_id}/versions/compare")
    assert compare.status_code == 200
    assert "configuration_changed" in compare.json()
