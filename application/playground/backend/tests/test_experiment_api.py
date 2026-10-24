"""API-surface tests for the experiments endpoints."""

from __future__ import annotations

EXPERIMENT_TASK = "experiments/tasks/web-compare-options"


def test_list_experiments_ok(client):
    resp = client.get("/api/experiments")
    assert resp.status_code == 200
    assert "experiments" in resp.json()


def test_list_experiment_tasks_ok(client):
    resp = client.get("/api/experiments/tasks")
    assert resp.status_code == 200
    tasks = resp.json()["tasks"]
    assert any(t["task"] == EXPERIMENT_TASK for t in tasks)


def test_preview_returns_cells(client):
    resp = client.post(
        "/api/experiments/preview",
        json={"taskPath": EXPERIMENT_TASK, "designType": "full_factorial"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["appType"] == "web"
    assert len(body["design"]["cells"]) == 2
    assert "instructionMarkdown" in body


def test_preview_rejects_bad_design(client):
    resp = client.post(
        "/api/experiments/preview",
        json={"taskPath": EXPERIMENT_TASK, "designType": "nonsense"},
    )
    assert resp.status_code == 422


def test_preview_unknown_task_is_400(client):
    resp = client.post(
        "/api/experiments/preview",
        json={"taskPath": "experiments/tasks/does-not-exist", "designType": "ab_n"},
    )
    assert resp.status_code == 400


def test_get_missing_experiment_is_404(client):
    resp = client.get("/api/experiments/exp-nope-00000000")
    assert resp.status_code == 404


def test_delete_missing_experiment_is_404(client):
    resp = client.delete("/api/experiments/exp-nope-00000000")
    assert resp.status_code == 404
