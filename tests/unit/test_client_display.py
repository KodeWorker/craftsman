import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from craftsman.client.telegram import TelegramClient

_CONFIG = {
    "workspace": {"root": "/tmp/tg-display-test"},
    "provider": {
        "model": "test-model",
        "ctx_size": 4096,
        "capabilities": {},
    },
    "chat": {"tools": ["all"], "max_tool_loops": 10},
    "telegram": {},
    "commands": [],
}

_META = {
    "kind": "meta",
    "model": "claude-3",
    "ctx_used": 50,
    "ctx_total": 4096,
    "prompt_tokens": 10,
    "completion_tokens": 5,
    "cost": 0.001,
}


@pytest.fixture
def tg_client(mocker, tmp_path):
    cfg = dict(_CONFIG)
    cfg["workspace"] = {"root": str(tmp_path)}
    mocker.patch("craftsman.client.telegram.get_config", return_value=cfg)
    mocker.patch(
        "craftsman.client.telegram.Auth.get_password", return_value="tok"
    )
    return TelegramClient(host="localhost", port=8080)


class _FakeResp:
    status_code = 200

    def __init__(self, *lines):
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def aiter_lines(self):
        for line in self._lines:
            yield line


# ── _drain ────────────────────────────────────────────────────────────────


def test_drain_collects_content(tg_client):
    lines = (
        json.dumps({"kind": "content", "text": "hello"}),
        json.dumps({"kind": "content", "text": " world"}),
    )

    async def _run():
        chunks, tcs = await tg_client._drain(_FakeResp(*lines))
        return chunks, tcs

    chunks, tcs = asyncio.run(_run())
    assert chunks == ["hello", " world"]
    assert tcs == []


def test_drain_collects_tool_calls(tg_client):
    tc = {
        "kind": "tool_call",
        "id": "tc1",
        "name": "bash:ls",
        "args": {"path": "/tmp"},
    }

    async def _run():
        return await tg_client._drain(_FakeResp(json.dumps(tc)))

    chunks, tcs = asyncio.run(_run())
    assert chunks == []
    assert len(tcs) == 1
    assert tcs[0]["name"] == "bash:ls"
    assert tcs[0]["id"] == "tc1"


def test_drain_updates_meta(tg_client):
    async def _run():
        await tg_client._drain(_FakeResp(json.dumps(_META)))

    asyncio.run(_run())
    assert tg_client._model == "claude-3"
    assert tg_client._ctx_used == 50
    assert tg_client._prompt_tokens == 10
    assert tg_client._cost == pytest.approx(0.001)


def test_drain_skips_invalid_json(tg_client):
    async def _run():
        return await tg_client._drain(
            _FakeResp(
                "not-json", json.dumps({"kind": "content", "text": "ok"})
            )
        )

    chunks, tcs = asyncio.run(_run())
    assert chunks == ["ok"]


def test_drain_separates_content_and_tool_calls(tg_client):
    lines = (
        json.dumps(
            {"kind": "tool_call", "id": "t1", "name": "bash:ls", "args": {}}
        ),
        json.dumps({"kind": "content", "text": "done"}),
        json.dumps(_META),
    )

    async def _run():
        return await tg_client._drain(_FakeResp(*lines))

    chunks, tcs = asyncio.run(_run())
    assert chunks == ["done"]
    assert tcs[0]["name"] == "bash:ls"


# ── _build_reply ──────────────────────────────────────────────────────────


def test_build_reply_no_tools_returns_content(tg_client):
    assert tg_client._build_reply([], ["hello", " world"]) == "hello world"


def test_build_reply_empty_content_no_tools(tg_client):
    assert tg_client._build_reply([], []) == ""


def test_build_reply_with_tool_prepends_summary(tg_client):
    log = [("bash:ls", {"path": "/tmp"}, {"files": ["a", "b"]})]
    reply = tg_client._build_reply(log, ["done"])
    lines = reply.split("\n")
    tool_idx = next(i for i, ln in enumerate(lines) if "[tool:" in ln)
    content_idx = next(i for i, ln in enumerate(lines) if "done" in ln)
    assert tool_idx < content_idx


def test_build_reply_error_uses_error_prefix(tg_client):
    log = [("bash:ls", {"path": "/bad"}, {"error": "no such file"})]
    reply = tg_client._build_reply(log, ["sorry"])
    assert "→ error: no such file" in reply
    assert "sorry" in reply


def test_build_reply_truncates_long_result(tg_client):
    long_result = {"data": "x" * 300}
    log = [("bash:cat", {"path": "/f"}, long_result)]
    reply = tg_client._build_reply(log, ["ok"])
    arrow_line = next(ln for ln in reply.split("\n") if ln.startswith("→"))
    assert arrow_line.endswith("…")
    assert len(arrow_line) <= 205


def test_build_reply_multiple_tools(tg_client):
    log = [
        ("bash:ls", {}, {"files": []}),
        ("bash:cat", {"path": "/f"}, {"content": "hi"}),
    ]
    reply = tg_client._build_reply(log, ["all done"])
    assert "[tool: bash:ls" in reply
    assert "[tool: bash:cat" in reply
    assert "all done" in reply


# ── _complete agentic loop ────────────────────────────────────────────────


def _tool_call_resp():
    return _FakeResp(
        json.dumps(
            {
                "kind": "tool_call",
                "id": "tc1",
                "name": "bash:ls",
                "args": {"path": "/tmp"},
            }
        ),
        json.dumps(_META),
    )


def _content_resp(text="done"):
    return _FakeResp(
        json.dumps({"kind": "content", "text": text}),
        json.dumps(_META),
    )


def test_complete_no_tool_calls_returns_content(tg_client, mocker):
    tg_client._http = MagicMock()
    tg_client._http.stream = MagicMock(return_value=_content_resp("hello"))

    result = asyncio.run(tg_client._complete("s1", "hi"))
    assert result == "hello"


def test_complete_tool_call_posts_tool_result(tg_client, mocker):
    call_log = []

    def fake_stream(method, url, **kwargs):
        call_log.append(url)
        if "tool_result" in url:
            return _content_resp("done")
        return _tool_call_resp()

    tg_client._http = MagicMock()
    tg_client._http.stream = MagicMock(side_effect=fake_stream)
    mocker.patch.object(
        tg_client,
        "_call_tool",
        new=AsyncMock(return_value={"files": ["a"]}),
    )

    result = asyncio.run(tg_client._complete("s1", "ls /tmp"))
    assert any("tool_result" in url for url in call_log)
    assert "done" in result


def test_complete_tool_summary_prepended(tg_client, mocker):
    def fake_stream(method, url, **kwargs):
        if "tool_result" in url:
            return _content_resp("answer here")
        return _tool_call_resp()

    tg_client._http = MagicMock()
    tg_client._http.stream = MagicMock(side_effect=fake_stream)
    mocker.patch.object(
        tg_client,
        "_call_tool",
        new=AsyncMock(return_value={"files": ["a"]}),
    )

    result = asyncio.run(tg_client._complete("s1", "ls /tmp"))
    lines = result.split("\n")
    tool_idx = next(i for i, ln in enumerate(lines) if "[tool:" in ln)
    answer_idx = next(i for i, ln in enumerate(lines) if "answer here" in ln)
    assert tool_idx < answer_idx


def test_complete_tool_error_shown_in_summary(tg_client, mocker):
    def fake_stream(method, url, **kwargs):
        if "tool_result" in url:
            return _content_resp("sorry")
        return _tool_call_resp()

    tg_client._http = MagicMock()
    tg_client._http.stream = MagicMock(side_effect=fake_stream)
    mocker.patch.object(
        tg_client,
        "_call_tool",
        new=AsyncMock(return_value={"error": "permission denied"}),
    )

    result = asyncio.run(tg_client._complete("s1", "ls /root"))
    assert "error: permission denied" in result
