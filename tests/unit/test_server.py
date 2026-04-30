import json
from unittest.mock import MagicMock, call

import pytest
from fastapi.testclient import TestClient

TEST_USER_ID = "user-id-1"


@pytest.fixture
def app(mocker):
    mock_provider = MagicMock()
    mock_provider.cost = MagicMock(return_value=0.0)
    mock_librarian = MagicMock()
    mock_librarian.structure_db.get_session.return_value = {
        "user_id": TEST_USER_ID
    }
    mocker.patch("craftsman.server.Provider", return_value=mock_provider)
    mocker.patch("craftsman.server.Librarian", return_value=mock_librarian)
    mocker.patch(
        "craftsman.server.CraftsmanLogger"
    ).return_value.get_logger.return_value = MagicMock()

    from craftsman.router.deps import get_current_user
    from craftsman.server import Server

    server = Server(port=8080)
    server.app.dependency_overrides[get_current_user] = lambda: TEST_USER_ID
    client = TestClient(server.app, raise_server_exceptions=True)
    return client, server, mock_provider, mock_librarian


@pytest.fixture
def mock_crypto(mocker):
    return mocker.patch("craftsman.server._crypto")


# --- simple GET endpoints ---


def test_health_returns_ok(app):
    client, *_ = app
    assert client.get("/health").json() == {"status": "ok"}


def test_get_system_prompt_joins_system_messages(app):
    client, _, _, mock_librarian = app
    mock_librarian.get_context.return_value = [
        {"role": "system", "content": "Be helpful."},
        {"role": "user", "content": "hi"},
    ]
    resp = client.get("/sessions/s1/system")
    assert resp.json()["system_prompt"] == "Be helpful."


def test_get_session_id_found(app):
    client, _, _, mock_librarian = app
    mock_librarian.structure_db.resolve_session.return_value = {
        "id": "abc-123"
    }
    assert client.get(
        "/sessions/resolve", params={"session": "abc"}
    ).json() == {"session_id": "abc-123"}


def test_get_session_id_not_found(app):
    client, _, _, mock_librarian = app
    mock_librarian.structure_db.resolve_session.return_value = None
    assert client.get("/sessions/resolve", params={"session": "x"}).json() == {
        "session_id": None
    }


def test_list_sessions_empty(app):
    client, _, _, mock_librarian = app
    mock_librarian.structure_db.list_sessions.return_value = []
    assert client.get("/sessions/").json() == {"sessions": []}


def test_list_sessions_maps_fields(app):
    client, _, _, mock_librarian = app
    mock_librarian.structure_db.list_sessions.return_value = [
        {
            "id": "sid-1",
            "title": "mytitle",
            "last_input": "hello",
            "last_input_at": "2024-01-01",
        }
    ]
    sessions = client.get("/sessions/").json()["sessions"]
    assert sessions[0]["session_id"] == "sid-1"
    assert sessions[0]["title"] == "mytitle"


def test_create_session_returns_id(app):
    client, server, _, mock_librarian = app
    mock_librarian.structure_db.create_session.return_value = "new-sid"
    resp = client.post("/sessions/")
    assert resp.json()["session_id"] == "new-sid"
    assert "new-sid" in server.active_sessions


# --- system prompt ---


def test_set_system_prompt_forbidden_for_different_owner(app):
    client, _, _, mock_librarian = app
    mock_librarian.structure_db.get_session.return_value = {"user_id": "other"}
    resp = client.put("/sessions/s1/system", json={"system_prompt": "hi"})
    assert resp.status_code == 403


def test_set_system_prompt_missing_prompt(app):
    client, *_ = app
    resp = client.put("/sessions/s1/system", json={})
    assert resp.status_code == 400


def test_set_system_prompt_clears_then_pushes(app):
    client, _, _, mock_librarian = app
    client.put(
        "/sessions/s1/system",
        json={"system_prompt": "You are helpful."},
    )
    mock_librarian.clear_system_prompt.assert_called_once_with("s1")
    mock_librarian.push_context.assert_called_once_with(
        "s1", {"role": "system", "content": "You are helpful."}
    )


# --- completion ---


def test_completion_missing_message(app):
    client, *_ = app
    resp = client.post("/sessions/s1/completion", json={})
    assert resp.status_code == 400


def test_completion_forbidden_for_different_owner(app):
    client, _, _, mock_librarian = app
    mock_librarian.structure_db.get_session.return_value = {"user_id": "other"}
    resp = client.post(
        "/sessions/s1/completion",
        json={"message": {"role": "user", "content": "hi"}},
    )
    assert resp.status_code == 403


def test_clear_session_success(app):
    client, server, _, mock_librarian = app
    server.active_sessions.add("s1")
    resp = client.post("/sessions/s1/clear")
    assert resp.json()["status"] == "session cleared"
    mock_librarian.clear_session.assert_called_once_with("s1")
    assert "s1" not in server.active_sessions


def test_delete_session_success(app):
    client, _, _, mock_librarian = app
    resp = client.delete("/sessions/s1")
    assert "deleted" in resp.json()["status"]
    mock_librarian.structure_db.delete_session.assert_called_once_with("s1")


# --- streaming completion ---


def _make_fake_completion(*yields):
    async def fake_completion(
        ctx, ctx_size=None, cancel_event=None, tools=None, tool_choice="auto"
    ):
        for item in yields:
            yield item

    return fake_completion


def test_completion_streams_ndjson(app):
    client, _, mock_provider, mock_librarian = app
    mock_provider.completion = _make_fake_completion(
        ("content", "hello"),
        (
            "meta",
            {
                "model": "m",
                "ctx_total": 4096,
                "prompt_tokens": 5,
                "completion_tokens": 3,
                "ctx_used": 8,
                "reasoning_tokens": 0,
                "cost": 0.0,
            },
        ),
    )
    mock_librarian.get_context.return_value = []
    mock_librarian.store_message.return_value = "mid"

    resp = client.post(
        "/sessions/s1/completion",
        json={"message": {"role": "user", "content": "hi"}},
    )
    lines = [line for line in resp.text.strip().split("\n") if line.strip()]
    assert all(json.loads(line) for line in lines)
    kinds = [json.loads(line)["kind"] for line in lines]
    assert "content" in kinds
    assert "meta" in kinds


def test_completion_stores_messages(app):
    client, _, mock_provider, mock_librarian = app
    mock_provider.completion = _make_fake_completion(
        ("content", "hello"),
        (
            "meta",
            {
                "model": "m",
                "ctx_total": 4096,
                "prompt_tokens": 5,
                "completion_tokens": 3,
                "ctx_used": 8,
                "reasoning_tokens": 0,
                "cost": 0.0,
            },
        ),
    )
    mock_librarian.get_context.return_value = []
    mock_librarian.store_message.return_value = "mid"

    client.post(
        "/sessions/s1/completion",
        json={"message": {"role": "user", "content": "hi"}},
    )
    assert mock_librarian.store_message.call_count == 3


def test_completion_pushes_assistant_to_context(app):
    client, _, mock_provider, mock_librarian = app
    mock_provider.completion = _make_fake_completion(
        ("content", "world"),
        (
            "meta",
            {
                "model": "m",
                "ctx_total": 4096,
                "prompt_tokens": 5,
                "completion_tokens": 3,
                "ctx_used": 8,
                "reasoning_tokens": 0,
                "cost": 0.0,
            },
        ),
    )
    mock_librarian.get_context.return_value = []
    mock_librarian.store_message.return_value = "mid"

    client.post(
        "/sessions/s1/completion",
        json={"message": {"role": "user", "content": "hi"}},
    )
    mock_librarian.push_context.assert_any_call(
        "s1", {"role": "assistant", "content": "world"}
    )


# --- resume_session ---


def test_resume_session_converts_summary_to_user(app):
    client, server, mock_provider, mock_librarian = app
    mock_librarian.retrieve_messages.return_value = (
        [{"role": "summary", "content": "we discussed X", "tokens": 10}],
        {"ctx_used": 10, "upload_tokens": 0, "download_tokens": 10},
    )
    mock_provider.cost = MagicMock(return_value=0.0)
    client.post("/sessions/s1/resume")
    mock_librarian.push_context.assert_called_once_with(
        "s1",
        {
            "role": "user",
            "content": "[Conversation summary: we discussed X]",
            "tokens": 10,
        },
    )


def test_resume_session_adds_to_active_sessions(app):
    client, server, mock_provider, mock_librarian = app
    mock_librarian.retrieve_messages.return_value = (
        [],
        {"ctx_used": 0, "upload_tokens": 0, "download_tokens": 0},
    )
    mock_provider.cost = MagicMock(return_value=0.0)
    client.post("/sessions/s-new/resume")
    assert "s-new" in server.active_sessions


def test_resume_session_meta_includes_cost(app):
    client, _, mock_provider, mock_librarian = app
    mock_librarian.retrieve_messages.return_value = (
        [],
        {"ctx_used": 0, "upload_tokens": 5, "download_tokens": 10},
    )
    mock_provider.cost = MagicMock(return_value=1.23)
    resp = client.post("/sessions/s1/resume")
    assert resp.json()["meta"]["cost"] == 1.23


# --- compact_session ---


def test_compact_nothing_to_do(app):
    client, _, _, mock_librarian = app
    mock_librarian.get_context.return_value = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
    ]  # 2 convo msgs <= keep_turns(5)*2=10
    resp = client.post("/sessions/s1/compact", json={})
    assert resp.json()["status"] == "nothing to compact"


def test_compact_invokes_provider_and_stores_summary(app):
    client, _, mock_provider, mock_librarian = app
    convo = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
        for i in range(12)
    ]
    mock_librarian.get_context.return_value = convo
    mock_provider.completion = _make_fake_completion(
        ("content", "summary text")
    )
    mock_librarian.store_message.return_value = "mid"

    client.post("/sessions/s1/compact", json={})
    mock_librarian.store_message.assert_called_once()
    stored = mock_librarian.store_message.call_args[0][1]
    assert stored["role"] == "summary"
    assert stored["content"] == "summary text"


def test_compact_preserves_system_messages(app):
    client, _, mock_provider, mock_librarian = app
    sys_msg = {"role": "system", "content": "You are helpful."}
    convo = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
        for i in range(12)
    ]
    mock_librarian.get_context.return_value = [sys_msg] + convo
    mock_provider.completion = _make_fake_completion(("content", "summary"))
    mock_librarian.store_message.return_value = "mid"

    client.post("/sessions/s1/compact", json={})
    push_calls = mock_librarian.push_context.call_args_list
    assert call("s1", sys_msg) in push_calls


def test_compact_rebuilds_context_with_tail(app):
    client, _, mock_provider, mock_librarian = app
    convo = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
        for i in range(12)
    ]
    mock_librarian.get_context.return_value = convo
    mock_provider.completion = _make_fake_completion(
        ("content", "the summary")
    )
    mock_librarian.store_message.return_value = "mid"

    client.post("/sessions/s1/compact", json={"keep_turns": 2})
    push_calls = [
        args[0][1] for args in mock_librarian.push_context.call_args_list
    ]
    summary_msg = {
        "role": "user",
        "content": "[Conversation summary: the summary]",
    }
    assert summary_msg in push_calls
    # tail = last 4 messages (keep_turns=2 → 2*2=4)
    tail = convo[-4:]
    for msg in tail:
        assert msg in push_calls


# --- login ---


def test_login_success(app, mock_crypto):
    client, _, _, mock_librarian = app
    mock_librarian.structure_db.get_user.return_value = {
        "id": TEST_USER_ID,
        "username": "alice",
        "password_hash": "hashed",
    }
    mock_crypto.verify_password.return_value = True
    mock_crypto.create_token.return_value = "tok123"
    resp = client.post(
        "/users/login", json={"username": "alice", "password": "pass"}
    )
    assert resp.status_code == 200
    assert resp.json()["token"] == "tok123"


def test_login_wrong_password(app, mock_crypto):
    client, _, _, mock_librarian = app
    mock_librarian.structure_db.get_user.return_value = {
        "id": TEST_USER_ID,
        "username": "alice",
        "password_hash": "hashed",
    }
    mock_crypto.verify_password.return_value = False
    resp = client.post(
        "/users/login", json={"username": "alice", "password": "wrong"}
    )
    assert resp.status_code == 401


def test_login_user_not_found(app, mock_crypto):
    client, _, _, mock_librarian = app
    mock_librarian.structure_db.get_user.return_value = None
    mock_crypto.verify_password.return_value = False
    resp = client.post(
        "/users/login", json={"username": "ghost", "password": "pass"}
    )
    assert resp.status_code == 401


def test_login_missing_fields(app):
    client, *_ = app
    assert client.post("/users/login", json={}).status_code == 400
    assert (
        client.post("/users/login", json={"username": "a"}).status_code == 400
    )


def test_login_same_error_for_wrong_password_and_missing_user(
    app, mock_crypto
):
    client, _, _, mock_librarian = app
    mock_librarian.structure_db.get_user.return_value = None
    mock_crypto.verify_password.return_value = False
    r1 = client.post(
        "/users/login", json={"username": "ghost", "password": "x"}
    )
    mock_librarian.structure_db.get_user.return_value = {
        "id": "uid",
        "username": "alice",
        "password_hash": "h",
    }
    r2 = client.post(
        "/users/login", json={"username": "alice", "password": "wrong"}
    )
    assert r1.json()["detail"] == r2.json()["detail"]


# --- ownership ---


def test_session_forbidden_for_different_owner(app):
    client, _, _, mock_librarian = app
    mock_librarian.structure_db.get_session.return_value = {
        "user_id": "other-user"
    }
    assert client.post("/sessions/s1/clear").status_code == 403
