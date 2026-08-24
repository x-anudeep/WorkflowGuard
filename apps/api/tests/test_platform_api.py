from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "examples"


def _upload_invoice(client: TestClient) -> str:
    path = EXAMPLES / "json" / "valid-workflow.json"
    response = client.post(
        "/api/workflows/upload",
        data={
            "source_type": "ai_generated",
            "source_prompt": "Read invoices from Gmail, extract invoice fields, require manual approval for invoices over $10,000, then save approved invoices to SAP.",
        },
        files={"file": ("valid-workflow.json", path.read_bytes(), "application/json")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_platform_history_quality_gate_and_report(client: TestClient) -> None:
    workflow_id = _upload_invoice(client)
    client.post(f"/api/workflows/{workflow_id}/evaluate", json={"use_ai": False})
    client.post(f"/api/workflows/{workflow_id}/tests/generate", json={"use_ai": False, "replace_existing": True})
    client.post(f"/api/workflows/{workflow_id}/tests/run", json={})
    client.post(f"/api/workflows/{workflow_id}/cost", json={"executions_per_day": 50})

    gate = client.post(f"/api/workflows/{workflow_id}/quality-gate", json={})
    assert gate.status_code == 200, gate.text
    assert gate.json()["status"] in {"PASS", "FAIL"}
    assert gate.json()["reasons"]

    history = client.get(f"/api/workflows/{workflow_id}/history")
    assert history.status_code == 200
    events = [event["event_type"] for event in history.json()]
    assert "uploaded" in events
    assert "quality_gate_checked" in events

    report = client.get(f"/api/workflows/{workflow_id}/report?format=json")
    assert report.status_code == 200
    body = report.json()
    assert body["workflow"]["id"] == workflow_id
    assert "quality_gate" in body

    markdown = client.get(f"/api/workflows/{workflow_id}/report?format=markdown")
    assert markdown.status_code == 200
    assert "WorkflowGuard Report" in markdown.text


def test_workflow_repository_filters_and_observability(client: TestClient) -> None:
    workflow_id = _upload_invoice(client)
    filtered = client.get("/api/workflows", params={"q": "invoice", "source_type": "ai_generated"})
    assert filtered.status_code == 200
    assert any(item["id"] == workflow_id for item in filtered.json())

    ready = client.get("/api/ready")
    assert ready.status_code == 200
    assert ready.headers["X-Request-ID"]

    metrics = client.get("/api/metrics")
    assert metrics.status_code == 200
    assert "workflowguard_workflows_total" in metrics.text
