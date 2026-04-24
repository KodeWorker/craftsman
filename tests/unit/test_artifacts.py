from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

TEST_USER_ID = "user-id-1"


@pytest.fixture
def app(mocker, tmp_path):
    mock_librarian = MagicMock()
    mock_librarian.structure_db.get_session.return_value = {
        "user_id": TEST_USER_ID
    }
    mock_librarian.structure_db.get_project.return_value = {
        "user_id": TEST_USER_ID
    }
    mocker.patch("craftsman.server.Provider")
    mocker.patch("craftsman.server.Librarian", return_value=mock_librarian)
    mocker.patch(
        "craftsman.server.CraftsmanLogger"
    ).return_value.get_logger.return_value = MagicMock()
    mocker.patch(
        "craftsman.router.artifacts.get_config",
        return_value={"workspace": {"artifacts": str(tmp_path)}},
    )

    from craftsman.router.deps import get_current_user
    from craftsman.server import Server

    server = Server(port=8080)
    server.app.dependency_overrides[get_current_user] = lambda: TEST_USER_ID
    client = TestClient(server.app, raise_server_exceptions=True)
    return client, mock_librarian, tmp_path


# --- upload ---


def test_upload_artifact_returns_artifact_id(app):
    client, mock_librarian, _ = app
    mock_librarian.structure_db.add_artifact.return_value = "artifact-test-id"
    resp = client.post(
        "/artifacts/",
        files={"file": ("photo.jpg", b"fake image data", "image/jpeg")},
        data={"session_id": "s1"},
    )
    assert resp.status_code == 200
    assert resp.json()["artifact_id"] == "artifact-test-id"


def test_upload_artifact_writes_file(app):
    client, mock_librarian, tmp_path = app
    mock_librarian.structure_db.add_artifact.return_value = "artifact-test-id"
    client.post(
        "/artifacts/",
        files={"file": ("photo.jpg", b"hello world", "image/jpeg")},
    )
    assert (tmp_path / "artifact-test-id.jpg").read_bytes() == b"hello world"


def test_upload_artifact_calls_update_with_size(app):
    client, mock_librarian, tmp_path = app
    mock_librarian.structure_db.add_artifact.return_value = "artifact-test-id"
    client.post(
        "/artifacts/",
        files={"file": ("photo.jpg", b"abc", "image/jpeg")},
    )
    mock_librarian.structure_db.update_artifact.assert_called_once_with(
        "artifact-test-id",
        filepath=str(tmp_path / "artifact-test-id.jpg"),
        size_bytes=3,
    )


# --- list ---


def test_list_artifacts_returns_artifacts(app):
    client, mock_librarian, _ = app
    mock_librarian.structure_db.get_artifacts.return_value = [
        {
            "id": "aid1",
            "filename": "photo.jpg",
            "mime_type": "image/jpeg",
            "size_bytes": 1024,
            "created_at": "2024-01-01",
        }
    ]
    resp = client.get("/artifacts/")
    assert resp.status_code == 200
    assert resp.json()["artifacts"][0]["id"] == "aid1"


def test_list_artifacts_session_forbidden(app):
    client, mock_librarian, _ = app
    mock_librarian.structure_db.get_session.return_value = {
        "user_id": "other-user"
    }
    resp = client.get("/artifacts/", params={"session_id": "s1"})
    assert resp.status_code == 403


def test_list_artifacts_project_forbidden(app):
    client, mock_librarian, _ = app
    mock_librarian.structure_db.get_project.return_value = {
        "user_id": "other-user"
    }
    resp = client.get("/artifacts/", params={"project_id": "p1"})
    assert resp.status_code == 403


# --- get ---


def test_get_artifact_returns_data(app):
    client, mock_librarian, _ = app
    mock_librarian.structure_db.resolve_artifact_id.return_value = "full-id"
    mock_librarian.structure_db.get_artifact.return_value = {
        "id": "full-id",
        "filename": "photo.jpg",
        "mime_type": "image/jpeg",
        "user_id": TEST_USER_ID,
        "filepath": "/tmp/photo.jpg",
        "size_bytes": 1024,
        "created_at": "2024-01-01",
    }
    resp = client.get("/artifacts/full-id")
    assert resp.status_code == 200
    assert resp.json()["artifact"]["filename"] == "photo.jpg"


def test_get_artifact_not_found(app):
    client, mock_librarian, _ = app
    mock_librarian.structure_db.resolve_artifact_id.return_value = None
    resp = client.get("/artifacts/unknown")
    assert resp.status_code == 404


# --- delete ---


def test_delete_artifact_success(app):
    client, mock_librarian, tmp_path = app
    artifact_file = tmp_path / "test-id.jpg"
    artifact_file.write_bytes(b"data")
    mock_librarian.structure_db.resolve_artifact_id.return_value = "test-id"
    mock_librarian.structure_db.get_artifact.return_value = {
        "id": "test-id",
        "filename": "test.jpg",
        "user_id": TEST_USER_ID,
        "filepath": str(artifact_file),
    }
    resp = client.delete("/artifacts/test-id")
    assert resp.status_code == 200
    assert not artifact_file.exists()


def test_delete_artifact_not_found(app):
    client, mock_librarian, _ = app
    mock_librarian.structure_db.resolve_artifact_id.return_value = None
    resp = client.delete("/artifacts/unknown")
    assert resp.status_code == 404


def test_delete_artifact_forbidden(app):
    client, mock_librarian, _ = app
    mock_librarian.structure_db.resolve_artifact_id.return_value = "aid"
    mock_librarian.structure_db.get_artifact.return_value = {
        "id": "aid",
        "filename": "test.jpg",
        "user_id": "other-user",
        "filepath": "",
    }
    resp = client.delete("/artifacts/aid")
    assert resp.status_code == 403
