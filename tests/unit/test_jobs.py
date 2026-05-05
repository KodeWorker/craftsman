from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

TEST_USER_ID = "user-id-1"
OTHER_USER_ID = "user-id-2"


@pytest.fixture
def app(mocker):
    mock_librarian = MagicMock()
    mocker.patch("craftsman.server.Provider")
    mocker.patch("craftsman.server.Librarian", return_value=mock_librarian)
    mocker.patch(
        "craftsman.server.CraftsmanLogger"
    ).return_value.get_logger.return_value = MagicMock()

    from craftsman.router.deps import get_current_user
    from craftsman.server import Server

    server = Server(port=8080)
    server.app.dependency_overrides[get_current_user] = lambda: TEST_USER_ID
    client = TestClient(server.app, raise_server_exceptions=True)
    return client, mock_librarian


# --- /jobs/due ---


def test_get_due_returns_scheduled_and_cron(app):
    client, mock_librarian = app
    mock_librarian.structure_db.get_due_jobs.return_value = []
    mock_librarian.structure_db.list_cron_jobs.return_value = []
    resp = client.get("/jobs/due")
    assert resp.status_code == 200
    body = resp.json()
    assert "scheduled" in body
    assert "cron" in body


# --- /jobs/scheduled/{job_id}/result ---


def test_scheduled_result_success(app):
    client, mock_librarian = app
    mock_librarian.structure_db.get_scheduled_job.return_value = {
        "id": "job-1",
        "user_id": TEST_USER_ID,
    }
    resp = client.post(
        "/jobs/scheduled/job-1/result",
        json={"status": "done", "result": {"output": "ok"}},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_librarian.structure_db.update_job_status.assert_called_once()


def test_scheduled_result_not_found(app):
    client, mock_librarian = app
    mock_librarian.structure_db.get_scheduled_job.return_value = None
    resp = client.post(
        "/jobs/scheduled/bad-id/result", json={"status": "done"}
    )
    assert resp.status_code == 403


def test_scheduled_result_forbidden(app):
    client, mock_librarian = app
    mock_librarian.structure_db.get_scheduled_job.return_value = {
        "id": "job-1",
        "user_id": OTHER_USER_ID,
    }
    resp = client.post("/jobs/scheduled/job-1/result", json={"status": "done"})
    assert resp.status_code == 403


# --- /jobs/cron/{cron_id}/result ---


def test_cron_result_success(app):
    client, mock_librarian = app
    mock_librarian.structure_db.get_cron_job.return_value = {
        "id": "cron-1",
        "user_id": TEST_USER_ID,
    }
    resp = client.post(
        "/jobs/cron/cron-1/result",
        json={"result": {"output": "ok"}},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_librarian.structure_db.update_cron_last_run.assert_called_once()


def test_cron_result_not_found(app):
    client, mock_librarian = app
    mock_librarian.structure_db.get_cron_job.return_value = None
    resp = client.post("/jobs/cron/bad-id/result", json={})
    assert resp.status_code == 403


def test_cron_result_forbidden(app):
    client, mock_librarian = app
    mock_librarian.structure_db.get_cron_job.return_value = {
        "id": "cron-1",
        "user_id": OTHER_USER_ID,
    }
    resp = client.post("/jobs/cron/cron-1/result", json={})
    assert resp.status_code == 403
