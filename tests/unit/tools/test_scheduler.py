import json
from unittest.mock import AsyncMock, MagicMock, patch

from craftsman.tools.agent_tools import make_agent_runner
from craftsman.tools.scheduler import JobDispatcher


def _make_dispatcher() -> JobDispatcher:
    d = JobDispatcher("http://localhost:6969", "test-token")
    d._http = AsyncMock()
    return d


def _ok_resp(payload: dict) -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = payload
    r.raise_for_status = MagicMock()
    return r


def _job(tool_name: str = "bash:ls", args: dict | None = None) -> dict:
    return {
        "id": "job-1",
        "tool_call": json.dumps({"name": tool_name, "args": args or {}}),
        "expression": "* * * * *",
    }


# ── _execute ──────────────────────────────────────────────────────────────


async def test_execute_unknown_returns_error():
    d = _make_dispatcher()
    result = await d._execute("no:such", {}, "sid")
    assert "error" in result


async def test_execute_local_dispatch():
    d = _make_dispatcher()
    mock_fn = AsyncMock(return_value={"output": "ok"})
    with patch.dict(
        "craftsman.tools.scheduler._LOCAL_DISPATCH", {"bash:ls": mock_fn}
    ):
        result = await d._execute("bash:ls", {"path": "/tmp"}, "sid")
    assert result == {"output": "ok"}
    mock_fn.assert_awaited_once_with({"path": "/tmp"})


async def test_execute_local_exception_returns_error():
    d = _make_dispatcher()
    mock_fn = AsyncMock(side_effect=RuntimeError("boom"))
    with patch.dict(
        "craftsman.tools.scheduler._LOCAL_DISPATCH", {"bash:ls": mock_fn}
    ):
        result = await d._execute("bash:ls", {}, "sid")
    assert result == {"error": "boom"}


async def test_execute_remote_tool_posts_invoke():
    d = _make_dispatcher()
    d._http.post = AsyncMock(return_value=_ok_resp({"stored": True}))
    with patch("craftsman.tools.scheduler.REMOTE_TOOLS", {"memory:store"}):
        result = await d._execute(
            "memory:store", {"key": "k", "value": "v"}, "sid-1"
        )
    d._http.post.assert_awaited_once()
    call_args = d._http.post.call_args
    assert "/tools/invoke" in call_args.args[0]
    assert call_args.kwargs["json"]["session_id"] == "sid-1"
    assert result == {"stored": True}


# ── _tick ─────────────────────────────────────────────────────────────────


async def test_tick_calls_run_scheduled_and_cron():
    d = _make_dispatcher()
    d._http.get = AsyncMock(
        return_value=_ok_resp({"scheduled": [], "cron": []})
    )
    d._run_scheduled = AsyncMock()
    d._run_cron = AsyncMock()

    await d._tick()

    d._run_scheduled.assert_awaited_once_with([])
    d._run_cron.assert_awaited_once_with([])


async def test_tick_skips_on_non_200():
    d = _make_dispatcher()
    bad = MagicMock()
    bad.status_code = 503
    d._http.get = AsyncMock(return_value=bad)
    d._run_scheduled = AsyncMock()

    await d._tick()

    d._run_scheduled.assert_not_awaited()


# ── _run_scheduled ────────────────────────────────────────────────────────


async def test_run_scheduled_posts_done_on_success():
    d = _make_dispatcher()
    d._run_job = AsyncMock(return_value={"output": "ok"})
    d._http.post = AsyncMock(return_value=_ok_resp({"ok": True}))

    await d._run_scheduled([_job()])

    d._run_job.assert_awaited_once()
    call = d._http.post.call_args
    assert "/jobs/scheduled/job-1/result" in call.args[0]
    assert call.kwargs["json"]["status"] == "done"


async def test_run_scheduled_posts_failed_on_error_result():
    d = _make_dispatcher()
    d._run_job = AsyncMock(return_value={"error": "bad"})
    d._http.post = AsyncMock(return_value=_ok_resp({"ok": True}))

    await d._run_scheduled([_job()])

    call = d._http.post.call_args
    assert call.kwargs["json"]["status"] == "failed"


async def test_run_scheduled_posts_failed_on_exception():
    d = _make_dispatcher()
    d._run_job = AsyncMock(side_effect=RuntimeError("crash"))
    d._http.post = AsyncMock(return_value=_ok_resp({"ok": True}))

    await d._run_scheduled([_job()])

    call = d._http.post.call_args
    assert call.kwargs["json"]["status"] == "failed"
    assert "crash" in call.kwargs["json"]["result"]["error"]


async def test_run_scheduled_empty_list_is_noop():
    d = _make_dispatcher()
    d._run_job = AsyncMock()
    await d._run_scheduled([])
    d._run_job.assert_not_awaited()


# ── _run_cron ─────────────────────────────────────────────────────────────


async def test_run_cron_posts_result():
    d = _make_dispatcher()
    d._run_job = AsyncMock(return_value={"output": "ok"})
    d._http.post = AsyncMock(return_value=_ok_resp({"ok": True}))

    await d._run_cron([_job()])

    call = d._http.post.call_args
    assert "/jobs/cron/job-1/result" in call.args[0]
    assert call.kwargs["json"]["result"] == {"output": "ok"}


async def test_run_cron_posts_error_on_exception():
    d = _make_dispatcher()
    d._run_job = AsyncMock(side_effect=RuntimeError("oops"))
    d._http.post = AsyncMock(return_value=_ok_resp({"ok": True}))

    await d._run_cron([_job()])

    call = d._http.post.call_args
    assert "oops" in call.kwargs["json"]["result"]["error"]


async def test_run_cron_empty_list_is_noop():
    d = _make_dispatcher()
    d._run_job = AsyncMock()
    await d._run_cron([])
    d._run_job.assert_not_awaited()


# ── make_agent_runner ─────────────────────────────────────────────────────


async def test_run_agent_empty_prompt_returns_error():
    runner = make_agent_runner("http://localhost:6969", "test-token")
    result = await runner({"prompt": "  "})
    assert "error" in result


async def test_run_agent_no_tool_calls_returns_content():
    runner = make_agent_runner("http://localhost:6969", "test-token")

    def _stream_ctx(*a, **kw):
        return _make_stream_ctx([{"kind": "content", "text": "hello"}])

    mock_client = AsyncMock()
    mock_client.post.return_value = _ok_resp({"session_id": "sub-sid"})
    mock_client.stream = _stream_ctx
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "craftsman.tools.agent_tools.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await runner({"prompt": "say hi"})

    assert result == {"content": "hello"}


async def test_run_agent_executes_tool_calls():
    runner = make_agent_runner("http://localhost:6969", "test-token")

    call_count = 0

    def _stream_ctx(*a, **kw):
        nonlocal call_count
        call_count += 1
        lines = (
            [
                {
                    "kind": "tool_call",
                    "id": "tc-1",
                    "name": "bash:ls",
                    "args": {},
                }
            ]
            if call_count == 1
            else [{"kind": "content", "text": "done"}]
        )
        return _make_stream_ctx(lines)

    mock_client = AsyncMock()
    mock_client.post.return_value = _ok_resp({"session_id": "sub-sid"})
    mock_client.stream = _stream_ctx
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    mock_fn = AsyncMock(return_value={"output": "files"})

    with patch(
        "craftsman.tools.agent_tools.httpx.AsyncClient",
        return_value=mock_client,
    ):
        with patch.dict(
            "craftsman.tools.executor._LOCAL_DISPATCH", {"bash:ls": mock_fn}
        ):
            result = await runner({"prompt": "list"})

    assert result == {"content": "done"}
    mock_fn.assert_awaited_once()


# ── helpers ───────────────────────────────────────────────────────────────


def _make_stream_ctx(lines: list[dict]):
    """Build an async context manager that yields NDJSON lines."""

    class _Resp:
        async def aiter_lines(self):
            for line in lines:
                yield json.dumps(line)

        def raise_for_status(self):
            pass

    class _Ctx:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *_):
            pass

    return _Ctx()
