import json
from unittest.mock import AsyncMock, MagicMock, patch

from craftsman.tools.agent_tools import make_agent_runner

BASE_URL = "http://localhost:6969"
TOKEN = "test-token"


def _make_http(
    *,
    session_resp=None,
    stream_chunks=None,
    delete_error=None,
):
    http = AsyncMock()

    if session_resp is not None:
        post_resp = MagicMock()
        post_resp.json.return_value = session_resp
        post_resp.raise_for_status = MagicMock()
        http.post.return_value = post_resp

    if stream_chunks is not None:
        stream_cm = AsyncMock()
        stream_cm.__aenter__ = AsyncMock(return_value=stream_cm)
        stream_cm.__aexit__ = AsyncMock(return_value=False)
        stream_cm.raise_for_status = MagicMock()

        async def _aiter_lines():
            for line in stream_chunks:
                yield line

        stream_cm.aiter_lines = _aiter_lines
        http.stream.return_value = stream_cm

    if delete_error is not None:
        http.delete.side_effect = delete_error
    else:
        delete_resp = MagicMock()
        delete_resp.raise_for_status = MagicMock()
        http.delete.return_value = delete_resp

    return http


async def test_empty_prompt_returns_error():
    agent_run = make_agent_runner(BASE_URL, TOKEN)
    result = await agent_run({"prompt": "  "})
    assert result == {"error": "prompt is required"}


async def test_session_create_failure_returns_error():
    agent_run = make_agent_runner(BASE_URL, TOKEN)
    with patch("httpx.AsyncClient") as mock_cls:
        instance = AsyncMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.post.side_effect = Exception("connection refused")
        mock_cls.return_value = instance
        result = await agent_run({"prompt": "do something"})
    assert "error" in result
    assert "session create failed" in result["error"]


def _make_stream_cm(chunks: list[str]) -> MagicMock:
    """Return an async context manager that yields lines from chunks."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=cm)
    cm.__aexit__ = AsyncMock(return_value=False)
    cm.raise_for_status = MagicMock()

    async def _aiter_lines():
        for line in chunks:
            yield line

    cm.aiter_lines = _aiter_lines
    return cm


def _make_instance(session_id: str, chunks: list[str], delete_error=None):
    """Build a mock AsyncClient instance for agent_run tests."""
    instance = AsyncMock()
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=False)

    post_resp = MagicMock()
    post_resp.json.return_value = {"session_id": session_id}
    post_resp.raise_for_status = MagicMock()
    instance.post.return_value = post_resp

    # stream() is not async — it returns an async CM directly
    instance.stream = MagicMock(return_value=_make_stream_cm(chunks))

    if delete_error:
        instance.delete.side_effect = delete_error
    else:
        delete_resp = MagicMock()
        delete_resp.raise_for_status = MagicMock()
        instance.delete = AsyncMock(return_value=delete_resp)

    return instance


async def test_successful_run_returns_content():
    content_line = json.dumps({"kind": "content", "text": "hello"})
    agent_run = make_agent_runner(BASE_URL, TOKEN)

    with patch("httpx.AsyncClient") as mock_cls:
        instance = _make_instance("sess-xyz", [content_line])
        mock_cls.return_value = instance
        result = await agent_run({"prompt": "say hello"})

    assert result == {"content": "hello"}
    instance.delete.assert_called_once()


async def test_session_cleanup_failure_returns_error():
    content_line = json.dumps({"kind": "content", "text": "done"})
    agent_run = make_agent_runner(BASE_URL, TOKEN)

    with patch("httpx.AsyncClient") as mock_cls:
        instance = _make_instance(
            "sess-del-fail",
            [content_line],
            delete_error=Exception("delete failed"),
        )
        mock_cls.return_value = instance
        result = await agent_run({"prompt": "say hello"})

    assert result == {"error": "delete failed"}
