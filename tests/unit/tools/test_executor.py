from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from craftsman.tools.executor import ToolExecutor


def _make_executor(http_response: dict | None = None):
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    if http_response is not None:
        resp = MagicMock()
        resp.json.return_value = http_response
        resp.raise_for_status = MagicMock()
        mock_client.post.return_value = resp
    return ToolExecutor(
        http_client=mock_client,
        base_url="http://localhost:6969",
        token="test-token",
    )


async def test_unknown_tool_returns_error():
    executor = _make_executor()
    result = await executor.execute("unknown:tool", {})
    assert "error" in result


async def test_local_tool_runs_without_http():
    executor = _make_executor()
    mock_fn = AsyncMock(return_value={"output": "ok", "truncated": False})
    with patch.dict(
        "craftsman.tools.executor._LOCAL_DISPATCH", {"bash:ls": mock_fn}
    ):
        result = await executor.execute("bash:ls", {"path": "/tmp"})
    executor.http.post.assert_not_called()
    assert "error" not in result


async def test_local_tool_exception_returns_error():
    executor = _make_executor()
    mock_fn = AsyncMock(side_effect=RuntimeError("boom"))
    with patch.dict(
        "craftsman.tools.executor._LOCAL_DISPATCH", {"bash:ls": mock_fn}
    ):
        result = await executor.execute("bash:ls", {"path": "/tmp"})
    assert result == {"error": "boom"}


async def test_remote_tool_posts_to_invoke():
    executor = _make_executor(http_response={"status": "stored", "key": "x"})
    result = await executor.execute(
        "memory:store", {"key": "x", "value": 1}, session_id="sess-1"
    )
    executor.http.post.assert_called_once()
    call_kwargs = executor.http.post.call_args
    assert "/tools/invoke" in call_kwargs.args[0]
    payload = call_kwargs.kwargs["json"]
    assert payload["name"] == "memory:store"
    assert payload["session_id"] == "sess-1"
    assert result["status"] == "stored"


async def test_remote_tool_sends_bearer_token():
    executor = _make_executor(http_response={"status": "ok"})
    await executor.execute("plan:create", {"goal": "g"})
    headers = executor.http.post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer test-token"


async def test_remote_http_error_returns_error():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = httpx.ConnectError("refused")
    executor = ToolExecutor(
        http_client=mock_client,
        base_url="http://localhost:6969",
        token="tok",
    )
    result = await executor.execute("memory:store", {"key": "k", "value": 1})
    assert "error" in result
