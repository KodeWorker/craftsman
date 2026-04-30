import json
from unittest.mock import MagicMock

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
    mock_librarian.get_context.return_value = []
    mock_librarian.structure_db.list_tools.return_value = []
    mock_librarian.structure_db.get_tool.return_value = None
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


def _make_meta_chunk(model="m", ctx_size=4096, prompt=10, completion=5):
    import types

    details = types.SimpleNamespace(reasoning_tokens=0)
    usage = types.SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        completion_tokens_details=details,
    )
    chunk = types.SimpleNamespace(choices=[], usage=usage)
    return chunk


async def _tool_call_stream(
    tool_id="tc1", tool_name="bash:ls", arguments='{"path":"/tmp"}'
):
    """Async generator that mimics provider yielding a tool_call response."""
    yield (
        "tool_call",
        {"id": tool_id, "name": tool_name, "arguments_raw": arguments},
    )
    yield (
        "meta",
        {
            "model": "m",
            "ctx_total": 4096,
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "ctx_used": 15,
            "reasoning_tokens": 0,
            "cost": 0.0,
        },
    )


async def _content_stream(text="hello"):
    yield ("content", text)
    yield (
        "meta",
        {
            "model": "m",
            "ctx_total": 4096,
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "ctx_used": 15,
            "reasoning_tokens": 0,
            "cost": 0.0,
        },
    )


# --- handle_completion: tool_call response ---


def test_completion_tool_call_streams_tool_call_event(app):
    client, _, mock_provider, mock_librarian = app
    mock_provider.completion = MagicMock(return_value=_tool_call_stream())

    resp = client.post(
        "/sessions/s1/completion",
        json={"message": {"role": "user", "content": "ls /tmp"}, "tools": []},
        headers={"Accept": "application/x-ndjson"},
    )
    assert resp.status_code == 200
    lines = [json.loads(ln) for ln in resp.text.strip().splitlines()]
    kinds = [ln["kind"] for ln in lines]
    assert "tool_call" in kinds
    tc = next(ln for ln in lines if ln["kind"] == "tool_call")
    assert tc["name"] == "bash:ls"
    assert tc["id"] == "tc1"
    assert tc["args"] == {"path": "/tmp"}


def test_completion_tool_call_stores_assistant_ctx_msg(app):
    client, _, mock_provider, mock_librarian = app
    mock_provider.completion = MagicMock(return_value=_tool_call_stream())

    client.post(
        "/sessions/s1/completion",
        json={"message": {"role": "user", "content": "ls"}, "tools": []},
    )

    pushed = mock_librarian.push_context.call_args_list
    assistant_calls = [c for c in pushed if c[0][1].get("role") == "assistant"]
    assert assistant_calls, "assistant message not pushed to context"
    msg = assistant_calls[0][0][1]
    assert "tool_calls" in msg
    assert msg["tool_calls"][0]["function"]["name"] == "bash:ls"


def test_completion_tool_call_stores_user_message(app):
    client, _, mock_provider, mock_librarian = app
    mock_provider.completion = MagicMock(return_value=_tool_call_stream())

    client.post(
        "/sessions/s1/completion",
        json={"message": {"role": "user", "content": "ls"}, "tools": []},
    )

    store_calls = mock_librarian.store_message.call_args_list
    roles = [c[0][1]["role"] for c in store_calls]
    assert "user" in roles


# --- handle_completion: content response ---


def test_completion_content_streams_text(app):
    client, _, mock_provider, mock_librarian = app
    mock_provider.completion = MagicMock(
        return_value=_content_stream("hello world")
    )

    resp = client.post(
        "/sessions/s1/completion",
        json={"message": {"role": "user", "content": "hi"}, "tools": []},
    )
    assert resp.status_code == 200
    lines = [json.loads(ln) for ln in resp.text.strip().splitlines()]
    content_lines = [ln for ln in lines if ln["kind"] == "content"]
    assert content_lines[0]["text"] == "hello world"


def test_completion_content_no_tool_call_events(app):
    client, _, mock_provider, mock_librarian = app
    mock_provider.completion = MagicMock(return_value=_content_stream("hi"))

    resp = client.post(
        "/sessions/s1/completion",
        json={"message": {"role": "user", "content": "hi"}, "tools": []},
    )
    lines = [json.loads(ln) for ln in resp.text.strip().splitlines()]
    assert not any(ln["kind"] == "tool_call" for ln in lines)


# --- tool_result endpoint ---


def test_tool_result_pushes_tool_messages_to_context(app):
    client, _, mock_provider, mock_librarian = app
    mock_provider.completion = MagicMock(return_value=_content_stream("done"))

    client.post(
        "/sessions/s1/tool_result",
        json={
            "tool_results": [
                {
                    "tool_call_id": "tc1",
                    "tool_name": "bash:ls",
                    "result": {"files": ["a", "b"]},
                }
            ],
            "tools": [],
        },
    )

    pushed = mock_librarian.push_context.call_args_list
    tool_calls = [c for c in pushed if c[0][1].get("role") == "tool"]
    assert tool_calls
    msg = tool_calls[0][0][1]
    assert msg["tool_call_id"] == "tc1"
    assert msg["name"] == "bash:ls"


def test_tool_result_stores_tool_messages_in_db(app):
    client, _, mock_provider, mock_librarian = app
    mock_provider.completion = MagicMock(return_value=_content_stream("done"))

    client.post(
        "/sessions/s1/tool_result",
        json={
            "tool_results": [
                {
                    "tool_call_id": "tc1",
                    "tool_name": "bash:ls",
                    "result": {"files": []},
                }
            ],
            "tools": [],
        },
    )

    store_calls = mock_librarian.store_message.call_args_list
    roles = [c[0][1]["role"] for c in store_calls]
    assert "tool" in roles


def test_tool_result_streams_next_completion(app):
    client, _, mock_provider, mock_librarian = app
    mock_provider.completion = MagicMock(return_value=_content_stream("done"))

    resp = client.post(
        "/sessions/s1/tool_result",
        json={"tool_results": [], "tools": []},
    )
    assert resp.status_code == 200
    lines = [json.loads(ln) for ln in resp.text.strip().splitlines()]
    assert any(ln["kind"] == "meta" for ln in lines)


# --- _build_tool_schemas ---


def test_build_tool_schemas_all(app):
    client, server, _, mock_librarian = app
    mock_librarian.structure_db.list_tools.return_value = [
        {
            "name": "bash:ls",
            "description": "list",
            "schema": json.dumps({"type": "object", "properties": {}}),
        }
    ]
    schemas = server.sessions_router._build_tool_schemas(["all"])
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "bash:ls"


def test_build_tool_schemas_empty_returns_empty(app):
    client, server, _, mock_librarian = app
    schemas = server.sessions_router._build_tool_schemas([])
    assert schemas == []
