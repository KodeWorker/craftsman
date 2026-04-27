import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from craftsman.telegram_bot import TelegramClient

_CONFIG = {
    "workspace": {"root": "/tmp/tg-test"},
    "provider": {"model": "test-model", "ctx_size": 8192},
    "commands": [{"name": "/compact", "limit": 500, "keep_turns": 3}],
}


@pytest.fixture
def client(mocker, tmp_path):
    cfg = dict(_CONFIG)
    cfg["workspace"] = {"root": str(tmp_path)}
    mocker.patch("craftsman.telegram_bot.get_config", return_value=cfg)
    mocker.patch(
        "craftsman.telegram_bot.Auth.get_password", return_value="tok"
    )
    return TelegramClient(host="localhost", port=6969)


# ── State ─────────────────────────────────────────────────────────────────


def test_load_state_default_when_no_file(client):
    assert client._state == {"chat_id": 0, "session_id": ""}


def test_load_state_reads_existing_file(mocker, tmp_path):
    state = {"chat_id": 999, "session_id": "sid-abc"}
    cfg = dict(_CONFIG)
    cfg["workspace"] = {"root": str(tmp_path)}
    mocker.patch("craftsman.telegram_bot.get_config", return_value=cfg)
    mocker.patch(
        "craftsman.telegram_bot.Auth.get_password", return_value="tok"
    )
    (tmp_path / "telegram.json").write_text(json.dumps(state))
    c = TelegramClient(host="localhost", port=6969)
    assert c._state["chat_id"] == 999
    assert c._state["session_id"] == "sid-abc"


def test_save_state_writes_file(client, tmp_path):
    client._state = {"chat_id": 123, "session_id": "s1"}
    client._save_state()
    data = json.loads((tmp_path / "telegram.json").read_text())
    assert data["chat_id"] == 123
    assert data["session_id"] == "s1"


# ── _complete: SSE parsing + meta accumulation ────────────────────────────


@pytest.mark.asyncio
async def test_complete_collects_content_chunks(client):
    lines = [
        json.dumps({"kind": "content", "text": "hello "}),
        json.dumps({"kind": "content", "text": "world"}),
        json.dumps(
            {
                "kind": "meta",
                "model": "m1",
                "ctx_used": 10,
                "ctx_total": 100,
                "prompt_tokens": 5,
                "completion_tokens": 3,
                "cost": 0.001,
            }
        ),
    ]

    mock_resp = MagicMock()
    mock_resp.aiter_lines = MagicMock(return_value=aiter(lines))

    mock_http = MagicMock()
    mock_http.stream.return_value.__aenter__ = AsyncMock(
        return_value=mock_resp
    )
    mock_http.stream.return_value.__aexit__ = AsyncMock(return_value=False)
    client._http = mock_http

    result = await client._complete("sid-1", "hi")
    assert result == "hello world"


@pytest.mark.asyncio
async def test_complete_updates_meta(client):
    lines = [
        json.dumps(
            {
                "kind": "meta",
                "model": "gemma",
                "ctx_used": 20,
                "ctx_total": 200,
                "prompt_tokens": 10,
                "completion_tokens": 7,
                "cost": 0.002,
            }
        ),
    ]

    mock_resp = MagicMock()
    mock_resp.aiter_lines = MagicMock(return_value=aiter(lines))

    mock_http = MagicMock()
    mock_http.stream.return_value.__aenter__ = AsyncMock(
        return_value=mock_resp
    )
    mock_http.stream.return_value.__aexit__ = AsyncMock(return_value=False)
    client._http = mock_http

    await client._complete("sid-1", "hi")

    assert client._model == "gemma"
    assert client._ctx_used == 20
    assert client._ctx_total == 200
    assert client._prompt_tokens == 10
    assert client._completion_tokens == 7
    assert abs(client._cost - 0.002) < 1e-9


@pytest.mark.asyncio
async def test_complete_accumulates_tokens_across_calls(client):
    def make_stream(pt, ct, cost):
        lines = [
            json.dumps(
                {
                    "kind": "meta",
                    "model": "m",
                    "ctx_used": 0,
                    "ctx_total": 0,
                    "prompt_tokens": pt,
                    "completion_tokens": ct,
                    "cost": cost,
                }
            )
        ]
        mock_resp = MagicMock()
        mock_resp.aiter_lines = MagicMock(return_value=aiter(lines))
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    client._http = MagicMock()
    client._http.stream.side_effect = [
        make_stream(5, 3, 0.001),
        make_stream(8, 4, 0.002),
    ]

    await client._complete("s", "msg1")
    await client._complete("s", "msg2")

    assert client._prompt_tokens == 13
    assert client._completion_tokens == 7
    assert abs(client._cost - 0.003) < 1e-9


# ── /status handler ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_on_status_formats_output(client):
    client._model = "gemma-4"
    client._ctx_used = 1500
    client._ctx_total = 8192
    client._prompt_tokens = 2000
    client._completion_tokens = 500
    client._cost = 0.0042
    client._state["session_id"] = "abcd1234-0000-0000-0000-000000000000"

    update = MagicMock()
    update.message.reply_text = AsyncMock()
    await client._on_status(update, MagicMock())

    text = update.message.reply_text.call_args[0][0]
    assert "gemma-4" in text
    assert "abcd1234" in text
    assert "1.5K" in text  # ctx_used
    assert "2.0K" in text  # prompt_tokens
    assert "500" in text  # completion_tokens
    assert "0.0042" in text


# ── /new handler ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_on_new_creates_session_and_saves(client):
    client._http = MagicMock()
    client._http.post = AsyncMock(
        return_value=MagicMock(
            status_code=200, json=lambda: {"session_id": "new-sid"}
        )
    )
    client._http.put = AsyncMock(return_value=MagicMock(status_code=200))

    update = MagicMock()
    update.message.reply_text = AsyncMock()

    with patch.object(client, "_read_system_prompt", return_value=""):
        await client._on_new(update, MagicMock())

    assert client._state["session_id"] == "new-sid"
    update.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_on_new_replies_failure_when_server_error(client):
    client._http = MagicMock()
    client._http.post = AsyncMock(
        return_value=MagicMock(status_code=500, json=lambda: {})
    )

    update = MagicMock()
    update.message.reply_text = AsyncMock()

    await client._on_new(update, MagicMock())

    assert "Failed" in update.message.reply_text.call_args[0][0]


# ── /on_text handler ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_on_text_no_session_replies_prompt(client):
    client._state["session_id"] = ""
    update = MagicMock()
    update.message.reply_text = AsyncMock()

    await client._on_text(update, MagicMock())

    text = update.message.reply_text.call_args[0][0]
    assert "No active session" in text


@pytest.mark.asyncio
async def test_on_text_sends_completion(client):
    client._state["session_id"] = "sid-1"

    update = MagicMock()
    update.effective_chat.id = 123
    update.message.text = "hello"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.bot.send_chat_action = AsyncMock()

    with patch.object(client, "_complete", new=AsyncMock(return_value="hi!")):
        await client._on_text(update, context)

    update.message.reply_text.assert_called_once_with("hi!")


@pytest.mark.asyncio
async def test_on_text_empty_response_sends_fallback(client):
    client._state["session_id"] = "sid-1"

    update = MagicMock()
    update.effective_chat.id = 123
    update.message.text = "hello"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.bot.send_chat_action = AsyncMock()

    with patch.object(client, "_complete", new=AsyncMock(return_value="")):
        await client._on_text(update, context)

    text = update.message.reply_text.call_args[0][0]
    assert "no response" in text


# ── _pair handshake ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pair_captures_chat_id(client, tmp_path):
    bot = MagicMock()
    bot.get_me = AsyncMock(return_value=MagicMock(username="testbot"))
    bot.delete_webhook = AsyncMock()
    bot.get_updates = AsyncMock(
        side_effect=[
            [],  # drain
            [
                MagicMock(
                    update_id=1,
                    message=MagicMock(chat=MagicMock(id=42)),
                )
            ],
        ]
    )
    bot.send_message = AsyncMock()

    result = await client._pair(bot)

    assert result is True
    assert client._state["chat_id"] == 42
    bot.delete_webhook.assert_called_once()
    bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_pair_timeout_returns_false(client):
    bot = MagicMock()
    bot.get_me = AsyncMock(return_value=MagicMock(username="testbot"))
    bot.delete_webhook = AsyncMock()
    bot.get_updates = AsyncMock(return_value=[])

    result = await client._pair(bot)

    assert result is False
    assert client._state["chat_id"] == 0


# ── helpers ───────────────────────────────────────────────────────────────


async def aiter(items):
    for item in items:
        yield item
