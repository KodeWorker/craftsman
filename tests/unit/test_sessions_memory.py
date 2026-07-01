from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

TEST_USER_ID = "user-id-1"
SESSION_ID = "s1"


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


async def _content_stream(text="ok"):
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


# ── 1. Ingest fires as create_task ──────────────────────────────────────────


def test_ingest_scheduled_as_task_for_nonempty_content(app, mocker):
    client, _, mock_provider, mock_librarian = app
    mock_provider.completion = MagicMock(return_value=_content_stream())
    mock_librarian.ingest_message = AsyncMock()
    # close() the coroutine so GC doesn't emit an unawaited-coroutine warning
    mock_create_task = mocker.patch(
        "asyncio.create_task", side_effect=lambda c: c.close()
    )

    client.post(
        f"/sessions/{SESSION_ID}/completion",
        json={"message": {"role": "user", "content": "hello"}, "tools": []},
    )

    mock_librarian.ingest_message.assert_called_once_with(SESSION_ID, "hello")
    mock_create_task.assert_called_once()


def test_ingest_not_scheduled_for_empty_content(app):
    client, _, mock_provider, mock_librarian = app
    mock_provider.completion = MagicMock(return_value=_content_stream())

    client.post(
        f"/sessions/{SESSION_ID}/completion",
        json={"message": {"role": "user", "content": ""}, "tools": []},
    )

    mock_librarian.ingest_message.assert_not_called()


# ── 2. Retrieval block inserted before LLM call ─────────────────────────────


def test_retrieval_injected_as_system_block_when_nonempty(app):
    client, _, mock_provider, mock_librarian = app

    mock_librarian.get_context.return_value = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "What testing tool should I use?"},
    ]
    retrieved = "[Retrieved context]\nUse pytest for all tests."
    mock_librarian.retrieve_context = AsyncMock(return_value=retrieved)

    captured: list = []

    async def capturing_stream(context, **kwargs):
        captured.extend(context)
        yield ("content", "pytest")
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

    mock_provider.completion = capturing_stream

    client.post(
        f"/sessions/{SESSION_ID}/completion",
        json={
            "message": {
                "role": "user",
                "content": "What testing tool should I use?",
            },
            "tools": [],
        },
    )

    system_contents = [
        m["content"] for m in captured if m.get("role") == "system"
    ]
    assert any(retrieved in c for c in system_contents)


def test_retrieval_not_injected_when_empty_string_returned(app):
    client, _, mock_provider, mock_librarian = app

    mock_librarian.get_context.return_value = [
        {"role": "user", "content": "hello"},
    ]
    mock_librarian.retrieve_context = AsyncMock(return_value="")

    captured: list = []

    async def capturing_stream(context, **kwargs):
        captured.extend(context)
        yield ("content", "hi")
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

    mock_provider.completion = capturing_stream

    client.post(
        f"/sessions/{SESSION_ID}/completion",
        json={"message": {"role": "user", "content": "hello"}, "tools": []},
    )

    assert not any(
        "[Retrieved context]" in m.get("content", "")
        for m in captured
        if m.get("role") == "system"
    )


def test_retrieval_injected_at_index_1_after_system_prompt(app):
    client, _, mock_provider, mock_librarian = app

    mock_librarian.get_context.return_value = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "question"},
    ]
    retrieved = "[Retrieved context]\nsome facts"
    mock_librarian.retrieve_context = AsyncMock(return_value=retrieved)

    captured: list = []

    async def capturing_stream(context, **kwargs):
        captured.extend(context)
        yield ("content", "answer")
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

    mock_provider.completion = capturing_stream

    client.post(
        f"/sessions/{SESSION_ID}/completion",
        json={
            "message": {"role": "user", "content": "question"},
            "tools": [],
        },
    )

    assert captured[0] == {"role": "system", "content": "You are helpful."}
    assert captured[1]["role"] == "system"
    assert retrieved in captured[1]["content"]


# ── 3. close_session_memory called on compact and delete ────────────────────


def test_close_session_memory_called_on_compact(app):
    client, _, mock_provider, mock_librarian = app

    # 12 alternating user/assistant messages so len(convo)=12 > keep_turns*2=4
    mock_librarian.get_context.return_value = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
        for i in range(12)
    ]
    mock_provider.completion = MagicMock(
        return_value=_content_stream("summary")
    )

    client.post(
        f"/sessions/{SESSION_ID}/compact",
        json={"summary_limit": 500, "keep_turns": 2},
    )

    mock_librarian.close_session_memory.assert_called_once_with(SESSION_ID)


def test_close_session_memory_called_on_delete(app):
    client, _, mock_provider, mock_librarian = app

    client.delete(f"/sessions/{SESSION_ID}")

    mock_librarian.close_session_memory.assert_called_once_with(SESSION_ID)
