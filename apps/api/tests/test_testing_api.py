from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "examples"


def upload_workflow(client: TestClient) -> str:
    path = EXAMPLES / "json" / "valid-workflow.json"
    response = client.post(
        "/api/workflows/upload",
        data={
            "source_type": "ai_generated",
            "source_prompt": "Approve requests, then notify Slack.",
        },
        files={"file": ("valid-workflow.json", path.read_bytes(), "application/json")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_generate_tests_persists_editable_system_tests(client: TestClient) -> None:
    workflow_id = upload_workflow(client)
    response = client.post(f"/api/workflows/{workflow_id}/tests/generate", json={"use_ai": True})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["generated"] >= 5
    assert body["tests"][0]["generated_by"] == "SYSTEM"
    assert body["warnings"]

    listed = client.get(f"/api/workflows/{workflow_id}/tests")
    assert listed.status_code == 200
    assert len(listed.json()) == body["generated"]


@pytest.mark.integration
def test_create_and_run_custom_test(client: TestClient) -> None:
    workflow_id = upload_workflow(client)
    create = client.post(
        f"/api/workflows/{workflow_id}/tests",
        json={
            "name": "Manual approval smoke",
            "description": "Human-authored reusable smoke test.",
            "generated_by": "HUMAN",
            "input_data": {"approved": True},
            "assertions": [
                {"type": "node_executed", "target": "approval"},
                {"type": "approval_requested", "target": "approval"},
                {"type": "terminated_successfully"},
            ],
            "importance": "HIGH",
            "tags": ["manual"],
        },
    )
    assert create.status_code == 201, create.text
    test_id = create.json()["id"]

    run = client.post(f"/api/tests/{test_id}/run")
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["test_id"] == test_id
    assert body["status"] == "PASSED"
    assert body["coverage"]["node_coverage"] > 0


def test_run_all_tests_and_fetch_history(client: TestClient) -> None:
    workflow_id = upload_workflow(client)
    client.post(f"/api/workflows/{workflow_id}/tests/generate", json={"use_ai": False})
    run_all = client.post(f"/api/workflows/{workflow_id}/tests/run", json={})
    assert run_all.status_code == 200, run_all.text
    summary = run_all.json()
    assert summary["total_tests"] > 0
    assert summary["runs"]
    assert summary["latest_coverage"] >= 0

    history = client.get(f"/api/workflows/{workflow_id}/test-runs")
    assert history.status_code == 200
    run_id = history.json()["runs"][0]["id"]
    detail = client.get(f"/api/test-runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == run_id


def test_generating_tests_twice_does_not_duplicate_the_suite(client: TestClient) -> None:
    """Every press of "Generate Tests" used to re-persist the whole corpus."""
    path = ROOT / "examples" / "json" / "valid-workflow.json"
    workflow = client.post(
        "/api/workflows/upload",
        data={"source_type": "ai_generated", "source_prompt": "Fetch invoices and save them."},
        files={"file": ("valid-workflow.json", path.read_bytes(), "application/json")},
    ).json()

    first = client.post(f"/api/workflows/{workflow['id']}/tests/generate", json={"use_ai": False})
    assert first.status_code == 200, first.text
    after_first = client.get(f"/api/workflows/{workflow['id']}/tests").json()
    assert after_first

    second = client.post(f"/api/workflows/{workflow['id']}/tests/generate", json={"use_ai": False})
    assert second.status_code == 200, second.text
    after_second = client.get(f"/api/workflows/{workflow['id']}/tests").json()

    assert len(after_second) == len(after_first)
    assert second.json()["generated"] == 0
    names = [test["name"] for test in after_second]
    assert len(names) == len(set(names)), "generated tests must be unique by name"
    # The response still describes the whole suite, so the panel and the status card
    # cannot disagree about how many tests exist.
    assert len(second.json()["tests"]) == len(after_second)


def test_regenerating_with_replace_existing_rebuilds_the_suite(client: TestClient) -> None:
    path = ROOT / "examples" / "json" / "valid-workflow.json"
    workflow = client.post(
        "/api/workflows/upload",
        data={"source_type": "ai_generated", "source_prompt": "Fetch invoices and save them."},
        files={"file": ("valid-workflow.json", path.read_bytes(), "application/json")},
    ).json()

    client.post(f"/api/workflows/{workflow['id']}/tests/generate", json={"use_ai": False})
    baseline = client.get(f"/api/workflows/{workflow['id']}/tests").json()

    replaced = client.post(
        f"/api/workflows/{workflow['id']}/tests/generate",
        json={"use_ai": False, "replace_existing": True},
    )
    assert replaced.status_code == 200, replaced.text
    after = client.get(f"/api/workflows/{workflow['id']}/tests").json()

    assert len(after) == len(baseline)
    assert replaced.json()["generated"] == len(baseline)
