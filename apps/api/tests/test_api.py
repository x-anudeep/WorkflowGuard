from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "examples"


def test_upload_generic_json_workflow(client: TestClient) -> None:
    path = EXAMPLES / "json" / "valid-workflow.json"
    response = client.post(
        "/api/workflows/upload",
        data={"source_type": "human"},
        files={"file": ("valid-workflow.json", path.read_bytes(), "application/json")},
    )
    assert response.status_code == 201, response.text
    workflow = response.json()
    assert workflow["source_format"] == "generic_json"
    assert workflow["structural_quality_score"] >= 85

    graph = client.get(f"/api/workflows/{workflow['id']}/graph")
    assert graph.status_code == 200
    assert len(graph.json()["nodes"]) == 4


def test_upload_bpmn_workflow(client: TestClient) -> None:
    path = EXAMPLES / "bpmn" / "valid-workflow.bpmn"
    response = client.post(
        "/api/workflows/upload",
        data={"source_type": "ai_generated", "source_prompt": "Create a simple approval workflow"},
        files={"file": ("valid-workflow.bpmn", path.read_bytes(), "application/xml")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["source_format"] == "bpmn"


def test_upload_n8n_workflow(client: TestClient) -> None:
    path = EXAMPLES / "n8n" / "valid-workflow.json"
    response = client.post(
        "/api/workflows/upload",
        data={"source_type": "human"},
        files={"file": ("valid-workflow.json", path.read_bytes(), "application/json")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["source_format"] == "n8n"


def test_upload_malformed_workflow_returns_400(client: TestClient) -> None:
    path = EXAMPLES / "json" / "malformed.json"
    response = client.post(
        "/api/workflows/upload",
        data={"source_type": "human"},
        files={"file": ("malformed.json", path.read_bytes(), "application/json")},
    )
    assert response.status_code == 400


def test_dashboard_uses_database_metrics(client: TestClient) -> None:
    path = EXAMPLES / "json" / "valid-workflow.json"
    client.post(
        "/api/workflows/upload",
        data={"source_type": "human"},
        files={"file": ("valid-workflow.json", path.read_bytes(), "application/json")},
    )
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    metrics = response.json()
    assert metrics["total_workflows"] == 1
    assert metrics["total_validation_runs"] == 1
    assert metrics["recent_workflows"]
