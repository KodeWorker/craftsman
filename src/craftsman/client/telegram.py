import asyncio
import io
import json
import os
import signal
import ssl
from pathlib import Path

try:
    from pydub import AudioSegment as _AudioSegment
except ImportError:
    _AudioSegment = None

import httpx
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from craftsman.auth import Auth
from craftsman.configure import get_config
from craftsman.tools.constants import REMOTE_TOOLS
from craftsman.tools.executor import _LOCAL_DISPATCH
from craftsman.tools.text_tools import commit_tmp

_PENDING_TOOLS = {"text:replace", "text:insert", "text:delete"}


class TelegramClient:
    def __init__(self, host: str, port: int):
        self.config = get_config()
        self._entry_point = f"http://{host}:{port}"
        self._token = Auth.get_password("TELEGRAM_BOT_TOKEN")
        self._state = self._load_state()
        self._jwt: str | None = None
        self._http: httpx.AsyncClient | None = None
        self._app: Application | None = None
        self._model: str = self.config.get("provider", {}).get(
            "model", "unknown"
        )
        self._ctx_used: int = 0
        self._ctx_total: int = self.config.get("provider", {}).get(
            "ctx_size", 0
        )
        self._prompt_tokens: int = 0
        self._completion_tokens: int = 0
        self._cost: float = 0.0
        self._pending_audit: dict[str, asyncio.Future] = {}

    # ── State ────────────────────────────────────────────────────────────

    def _state_path(self) -> Path:
        root = Path(os.path.expanduser(self.config["workspace"]["root"]))
        return root / "telegram.json"

    def _load_state(self) -> dict:
        p = self._state_path()
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                pass
        return {"chat_id": 0, "session_id": ""}

    def _save_state(self) -> None:
        try:
            self._state_path().write_text(json.dumps(self._state))
        except Exception as e:
            print(f"Warning: failed to save state: {e}")

    # ── Server API ───────────────────────────────────────────────────────

    async def _request(
        self, method: str, url: str, **kwargs
    ) -> httpx.Response:
        resp = await getattr(self._http, method)(url, **kwargs)
        if resp.status_code == 401:
            if not await self._login():
                return resp
            resp = await getattr(self._http, method)(url, **kwargs)
        return resp

    async def _seed_tools(self) -> None:
        await self._request("post", f"{self._entry_point}/tools/seed")

    async def _run_dispatcher(self) -> None:
        from craftsman.tools.scheduler import JobDispatcher

        dispatcher = JobDispatcher(self._entry_point, self._jwt)
        await dispatcher.run_loop()

    async def _reset_provider(self) -> None:
        cfg = self.config.get("provider", {})
        await self._request(
            "post",
            f"{self._entry_point}/reset",
            json={
                "api_base": cfg.get("api_base"),
                "api_key": Auth.get_password("LLM_API_KEY"),
            },
        )

    async def _login(self) -> bool:
        username = Auth.get_password("USERNAME")
        password = Auth.get_password("PASSWORD")
        if not username or not password:
            print("Credentials not set. Run: craftsman user login")
            return False
        resp = await self._http.post(
            f"{self._entry_point}/users/login",
            json={"username": username, "password": password},
        )
        if resp.status_code == 200:
            self._jwt = resp.json()["token"]
            self._http.headers.update({"Authorization": f"Bearer {self._jwt}"})
            return True
        print(f"Login failed: {resp.status_code} {resp.text}")
        return False

    def _read_system_prompt(self) -> str:
        for path in (
            Path.cwd() / ".craftsman" / "system_prompt.md",
            Path(os.path.expanduser(self.config["workspace"]["root"]))
            / "system_prompt.md",
        ):
            if path.exists():
                return path.read_text().strip()
        return ""

    async def _set_system_prompt(self, session_id: str) -> None:
        prompt = self._read_system_prompt()
        if not prompt:
            return
        await self._request(
            "put",
            f"{self._entry_point}/sessions/{session_id}/system",
            json={"system_prompt": prompt},
        )

    async def _create_session(self) -> str | None:
        resp = await self._request("post", f"{self._entry_point}/sessions/")
        if resp.status_code == 200:
            return resp.json().get("session_id")
        return None

    async def _get_sessions(self, limit: int = 5) -> list:
        resp = await self._request(
            "get",
            f"{self._entry_point}/sessions/",
            params={"limit": limit},
        )
        if resp.status_code == 200:
            return resp.json().get("sessions", [])
        return []

    async def _get_artifacts(self, session_id: str) -> list:
        resp = await self._request(
            "get",
            f"{self._entry_point}/artifacts/",
            params={"session_id": session_id},
        )
        if resp.status_code == 200:
            return resp.json().get("artifacts", [])
        return []

    async def _drain(
        self, stream_resp: httpx.Response
    ) -> tuple[list[str], list[dict]]:
        chunks: list[str] = []
        tool_calls: list[dict] = []
        async for line in stream_resp.aiter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
                kind = chunk.get("kind")
                if kind == "content":
                    chunks.append(chunk["text"])
                elif kind == "tool_call":
                    tool_calls.append(chunk)
                elif kind == "meta":
                    self._model = chunk.get("model", self._model)
                    self._ctx_used = chunk.get("ctx_used", self._ctx_used)
                    self._ctx_total = chunk.get("ctx_total", self._ctx_total)
                    self._prompt_tokens += chunk.get("prompt_tokens", 0)
                    self._completion_tokens += chunk.get(
                        "completion_tokens", 0
                    )
                    self._cost += chunk.get("cost", 0.0)
            except json.JSONDecodeError:
                pass
        return chunks, tool_calls

    async def _call_tool(self, name: str, args: dict, session_id: str) -> dict:
        if name in _LOCAL_DISPATCH:
            try:
                return await _LOCAL_DISPATCH[name](args)
            except Exception as e:
                return {"error": str(e)}
        if name in REMOTE_TOOLS:
            try:
                resp = await self._request(
                    "post",
                    f"{self._entry_point}/tools/invoke",
                    json={
                        "name": name,
                        "args": args,
                        "session_id": session_id,
                    },
                )
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                return {"error": str(e)}
        return {"error": f"Unknown tool: {name}"}

    async def _request_confirmation(
        self,
        bot,
        chat_id: int,
        call_id: str,
        name: str,
        args: dict,
    ) -> tuple[bool, str]:
        args_str = json.dumps(args)
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✓ Approve",
                        callback_data=f"audit:y:{call_id}",
                    ),
                    InlineKeyboardButton(
                        "✗ Reject",
                        callback_data=f"audit:n:{call_id}",
                    ),
                ]
            ]
        )
        await bot.send_message(
            chat_id,
            f"[audited] {name}\n{args_str}\nApprove execution?",
            reply_markup=keyboard,
        )
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_audit[call_id] = future
        try:
            return await asyncio.wait_for(future, timeout=60.0)
        except asyncio.TimeoutError:
            self._pending_audit.pop(call_id, None)
            return False, "timed out"

    async def _on_audit_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        await query.answer()
        parts = query.data.split(":", 2)
        if len(parts) != 3:
            return
        _, decision, call_id = parts
        future = self._pending_audit.pop(call_id, None)
        if future and not future.done():
            if decision == "y":
                future.set_result((True, ""))
            else:
                future.set_result((False, "user rejected"))
        await query.edit_message_reply_markup(reply_markup=None)

    def _build_reply(
        self,
        tool_log: list[tuple[str, dict, dict]],
        content_chunks: list[str],
    ) -> str:
        parts: list[str] = []
        for name, args, result in tool_log:
            args_str = json.dumps(args)
            preview = json.dumps(result)
            if len(preview) > 200:
                preview = preview[:200] + "…"
            if result.get("error"):
                parts.append(
                    f"[tool: {name} {args_str}]\n"
                    f"→ error: {result['error']}"
                )
            else:
                parts.append(f"[tool: {name} {args_str}]\n→ {preview}")
        content = "".join(content_chunks)
        if parts:
            parts.append("")
            parts.append(content)
            return "\n".join(parts)
        return content

    async def _complete(
        self,
        session_id: str,
        text: str,
        bot=None,
        chat_id: int = 0,
    ) -> str:
        tools = self.config.get("chat", {}).get("tools", ["all"])
        max_loops = self.config.get("chat", {}).get("max_tool_loops", 10)
        url = f"{self._entry_point}/sessions/{session_id}/completion"
        body = {
            "message": {"role": "user", "content": text},
            "tools": tools,
        }
        tool_log: list[tuple[str, dict, dict]] = []
        content_chunks: list[str] = []
        tool_calls: list[dict] = []

        for attempt in range(2):
            async with self._http.stream("POST", url, json=body) as resp:
                if resp.status_code == 401 and attempt == 0:
                    if not await self._login():
                        return ""
                    continue
                content_chunks, tool_calls = await self._drain(resp)
                break
        else:
            return ""

        # pass 0 = first tool round; passes 1..max_loops-1 = subsequent
        # guard at tool_round >= max_loops mirrors chat.py's agentic_loop
        for tool_round in range(max_loops + 1):
            if not tool_calls or tool_round >= max_loops:
                break
            tool_results = []
            for tc in tool_calls:
                name = tc["name"]
                args = tc.get("args", {})
                audited = tc.get("audited", False)

                if audited and name not in _PENDING_TOOLS and bot and chat_id:
                    approved, reason = await self._request_confirmation(
                        bot, chat_id, tc["id"], name, args
                    )
                    if not approved:
                        result: dict = {
                            "status": "rejected",
                            "reason": reason,
                        }
                        tool_log.append((name, args, result))
                        tool_results.append(
                            {
                                "tool_call_id": tc["id"],
                                "tool_name": name,
                                "result": result,
                            }
                        )
                        continue

                result = await self._call_tool(name, args, session_id)
                if result.get("status") == "pending":
                    try:
                        bak = commit_tmp(result["file"], result["tmp"])
                        result = {
                            "status": "committed",
                            "file": result["file"],
                            "backup": bak,
                        }
                    except Exception as e:
                        result = {"error": str(e)}
                tool_log.append((name, args, result))
                tool_results.append(
                    {
                        "tool_call_id": tc["id"],
                        "tool_name": name,
                        "result": result,
                    }
                )
            tr_url = f"{self._entry_point}/sessions/{session_id}/tool_result"
            async with self._http.stream(
                "POST",
                tr_url,
                json={"tool_results": tool_results, "tools": tools},
            ) as resp:
                if resp.status_code != 200:
                    return self._build_reply(tool_log, content_chunks)
                content_chunks, tool_calls = await self._drain(resp)

        return self._build_reply(tool_log, content_chunks)

    # ── Pairing ──────────────────────────────────────────────────────────

    async def _pair(self, bot: Bot) -> bool:
        try:
            me = await bot.get_me()
        except Exception as e:
            print(f"Invalid bot token: {e}")
            return False

        print(f"Open t.me/{me.username} on your phone and send any message.")

        # delete any registered webhook — getUpdates is silently ignored
        # while a webhook is active
        try:
            await bot.delete_webhook(drop_pending_updates=True)
        except Exception:
            pass

        # drain stale updates and record the next offset
        offset = 0
        try:
            stale = await bot.get_updates(timeout=0)
            if stale:
                offset = stale[-1].update_id + 1
        except Exception:
            pass

        poll_interval = 3
        pair_timeout = self.config.get("telegram", {}).get(
            "pair_timeout_seconds", 120
        )
        max_polls = pair_timeout // poll_interval
        for _ in range(max_polls):
            try:
                updates = await bot.get_updates(
                    offset=offset,
                    timeout=3,
                    allowed_updates=["message"],
                )
            except Exception:
                await asyncio.sleep(1)
                continue
            for u in updates:
                offset = u.update_id + 1
                if u.message:
                    self._state["chat_id"] = u.message.chat.id
                    self._save_state()
                    await bot.send_message(
                        u.message.chat.id,
                        "Paired with craftsman ✓",
                    )
                    print(
                        f"Paired with chat_id {self._state['chat_id']}."
                        " Auto-connect saved."
                    )
                    return True

        print("Pairing timed out — no message received.")
        return False

    # ── Capability / upload helpers ──────────────────────────────────────

    def _caps(self, kind: str) -> dict:
        return (
            self.config.get("provider", {})
            .get("capabilities", {})
            .get(kind, {})
        )

    async def _upload_bytes(
        self, data: bytes, filename: str, mime_type: str
    ) -> str | None:
        resp = await self._request(
            "post",
            f"{self._entry_point}/artifacts/",
            files={"file": (filename, data, mime_type)},
            data={"session_id": self._state["session_id"]},
        )
        if resp.status_code == 200:
            return resp.json().get("artifact_id")
        return None

    async def _complete_and_reply(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        text: str,
    ) -> None:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action=ChatAction.TYPING
        )
        response = await self._complete(
            self._state["session_id"],
            text,
            bot=context.bot,
            chat_id=update.effective_chat.id,
        )
        if not response:
            await update.message.reply_text("(no response from server)")
            return
        max_len = 4096
        for i in range(0, len(response), max_len):
            await update.message.reply_text(response[i : i + max_len])

    # ── Handlers ─────────────────────────────────────────────────────────

    def _register_handlers(self) -> None:
        cf = filters.Chat(chat_id=self._state["chat_id"])
        self._app.add_handler(
            CommandHandler("help", self._on_help, filters=cf)
        )
        self._app.add_handler(CommandHandler("new", self._on_new, filters=cf))
        self._app.add_handler(
            CommandHandler("sessions", self._on_sessions, filters=cf)
        )
        self._app.add_handler(
            CommandHandler("artifacts", self._on_artifacts, filters=cf)
        )
        self._app.add_handler(
            CommandHandler("clear", self._on_clear, filters=cf)
        )
        self._app.add_handler(
            CommandHandler("compact", self._on_compact, filters=cf)
        )
        self._app.add_handler(
            CommandHandler("status", self._on_status, filters=cf)
        )
        self._app.add_handler(
            CallbackQueryHandler(self._on_session_switch, pattern=r"^switch:")
        )
        self._app.add_handler(
            CallbackQueryHandler(self._on_audit_callback, pattern=r"^audit:")
        )
        self._app.add_handler(
            MessageHandler(cf & filters.TEXT & ~filters.COMMAND, self._on_text)
        )
        self._app.add_handler(
            MessageHandler(cf & filters.PHOTO, self._on_photo)
        )
        self._app.add_handler(
            MessageHandler(cf & filters.Document.ALL, self._on_document)
        )
        self._app.add_handler(
            MessageHandler(cf & filters.AUDIO, self._on_audio)
        )
        self._app.add_handler(
            MessageHandler(cf & filters.VOICE, self._on_voice)
        )
        self._app.add_handler(
            MessageHandler(cf & filters.VIDEO_NOTE, self._on_video_note)
        )

    async def _on_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await update.message.reply_text(
            "Available commands:\n"
            "  /help — show this message\n"
            "  /new — end session; start fresh\n"
            "  /sessions — list recent sessions\n"
            "  /artifacts — list artifacts in current session\n"
            "  /clear — clear session history\n"
            "  /compact — summarize and reduce context size\n"
            "  /status — show model, session, token and cost info\n\n"
            "Media support:\n"
            "  photos and image documents → vision\n"
            "  audio files and voice messages → audio"
        )

    async def _on_new(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        sid = await self._create_session()
        if not sid:
            await update.message.reply_text("Failed to create session.")
            return
        self._state["session_id"] = sid
        self._save_state()
        await self._set_system_prompt(sid)
        await update.message.reply_text("New session started.")

    async def _on_sessions(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        sessions = await self._get_sessions(limit=5)
        if not sessions:
            await update.message.reply_text("No sessions found.")
            return
        active = self._state["session_id"]
        buttons = [
            [
                InlineKeyboardButton(
                    f"{'* ' if s['session_id'] == active else ''}"
                    f"{s.get('last_input_at', '')[:16]} — "
                    f"{s.get('title') or s['session_id'][:8]}",
                    callback_data=f"switch:{s['session_id']}",
                )
            ]
            for s in sessions
        ]
        await update.message.reply_text(
            "Recent sessions (* = active):",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    async def _on_artifacts(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        sid = self._state["session_id"]
        if not sid:
            await update.message.reply_text("No active session.")
            return
        artifacts = await self._get_artifacts(sid)
        if not artifacts:
            await update.message.reply_text("No artifacts in current session.")
            return
        lines = [
            f"{a['filename']} ({a.get('mime_type') or 'unknown'},"
            f" {a['id'][:8]})"
            for a in artifacts
        ]
        await update.message.reply_text("\n".join(lines))

    async def _on_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        sid = self._state["session_id"]

        def _fmt(n: int) -> str:
            return f"{n/1000:.1f}K" if n >= 1000 else str(n)

        await update.message.reply_text(
            f"model: {self._model or '(unknown)'}\n"
            f"session: {sid[:8] if sid else '(none)'}\n"
            f"ctx: {_fmt(self._ctx_used)}/{_fmt(self._ctx_total)}\n"
            f"tokens: {_fmt(self._prompt_tokens)}↑ "
            f"{_fmt(self._completion_tokens)}↓\n"
            f"cost: ${self._cost:.4f}"
        )

    async def _on_clear(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        sid = self._state["session_id"]
        if not sid:
            await update.message.reply_text("No active session.")
            return
        resp = await self._request(
            "post", f"{self._entry_point}/sessions/{sid}/clear"
        )
        if resp.status_code == 200:
            await update.message.reply_text("Session history cleared.")
        else:
            await update.message.reply_text("Failed to clear session.")

    async def _on_compact(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        sid = self._state["session_id"]
        if not sid:
            await update.message.reply_text("No active session.")
            return
        cfg_cmds = self.config.get("commands", [])
        limit, keep_turns = next(
            (
                (c.get("limit", 1000), c.get("keep_turns", 5))
                for c in cfg_cmds
                if c["name"] == "/compact"
            ),
            (1000, 5),
        )
        resp = await self._request(
            "post",
            f"{self._entry_point}/sessions/{sid}/compact",
            json={"summary_limit": limit, "keep_turns": keep_turns},
        )
        if resp.status_code == 200:
            await update.message.reply_text(
                resp.json().get("status", "Compacted.")
            )
        else:
            await update.message.reply_text("Failed to compact session.")

    async def _on_session_switch(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        await query.answer()
        session_id = query.data.split(":", 1)[1]
        self._state["session_id"] = session_id
        self._save_state()

        sessions = await self._get_sessions(limit=5)
        last_input = next(
            (
                s.get("last_input", "")
                for s in sessions
                if s["session_id"] == session_id
            ),
            "",
        )
        preview = (
            (last_input[:80] + "…") if len(last_input) > 80 else last_input
        )
        hint = f"\nLast: {preview}" if preview else ""
        await query.edit_message_text(
            f"Switched to session {session_id[:8]}{hint}"
        )

    async def _on_text(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not self._state["session_id"]:
            await update.message.reply_text(
                "No active session. Send /new to start one."
            )
            return
        await self._complete_and_reply(update, context, update.message.text)

    # ── Media handlers ────────────────────────────────────────────────────

    async def _on_photo(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        vision = self._caps("vision")
        if not vision.get("enabled", False):
            await update.message.reply_text(
                "Vision is not enabled for this provider."
            )
            return
        if not self._state["session_id"]:
            await update.message.reply_text(
                "No active session. Send /new to start one."
            )
            return
        photo = update.message.photo[-1]
        tg_file = await context.bot.get_file(photo.file_id)
        data = bytes(await tg_file.download_as_bytearray())
        max_mb = vision.get("max_size_mb", 10)
        if len(data) > max_mb * 1024 * 1024:
            await update.message.reply_text(
                f"Photo exceeds the {max_mb}MB size limit."
            )
            return
        artifact_id = await self._upload_bytes(data, "photo.jpg", "image/jpeg")
        if not artifact_id:
            await update.message.reply_text("Failed to upload photo.")
            return
        msg = f"@image:{artifact_id}"
        if update.message.caption:
            msg = f"{msg} {update.message.caption}"
        await self._complete_and_reply(update, context, msg)

    async def _on_document(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        doc = update.message.document
        mime = doc.mime_type or ""
        if not mime.startswith("image/"):
            await update.message.reply_text(
                "Only image documents are supported."
            )
            return
        vision = self._caps("vision")
        if not vision.get("enabled", False):
            await update.message.reply_text(
                "Vision is not enabled for this provider."
            )
            return
        if not self._state["session_id"]:
            await update.message.reply_text(
                "No active session. Send /new to start one."
            )
            return
        tg_file = await context.bot.get_file(doc.file_id)
        data = bytes(await tg_file.download_as_bytearray())
        max_mb = vision.get("max_size_mb", 10)
        if len(data) > max_mb * 1024 * 1024:
            await update.message.reply_text(
                f"Document exceeds the {max_mb}MB size limit."
            )
            return
        subtype = mime.split("/")[-1]
        filename = doc.file_name or f"image.{subtype}"
        artifact_id = await self._upload_bytes(data, filename, mime)
        if not artifact_id:
            await update.message.reply_text("Failed to upload document.")
            return
        msg = f"@image:{artifact_id}"
        if update.message.caption:
            msg = f"{msg} {update.message.caption}"
        await self._complete_and_reply(update, context, msg)

    async def _on_audio(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        audio_cfg = self._caps("audio")
        if not audio_cfg.get("enabled", False):
            await update.message.reply_text(
                "Audio is not enabled for this provider."
            )
            return
        if not self._state["session_id"]:
            await update.message.reply_text(
                "No active session. Send /new to start one."
            )
            return
        audio = update.message.audio
        mime = audio.mime_type or "audio/mpeg"
        tg_file = await context.bot.get_file(audio.file_id)
        data = bytes(await tg_file.download_as_bytearray())
        max_mb = audio_cfg.get("max_size_mb", 25)
        if len(data) > max_mb * 1024 * 1024:
            await update.message.reply_text(
                f"Audio file exceeds the {max_mb}MB size limit."
            )
            return
        filename = audio.file_name or "audio.mp3"
        artifact_id = await self._upload_bytes(data, filename, mime)
        if not artifact_id:
            await update.message.reply_text("Failed to upload audio.")
            return
        msg = f"@audio:{artifact_id}"
        if update.message.caption:
            msg = f"{msg} {update.message.caption}"
        await self._complete_and_reply(update, context, msg)

    async def _on_voice(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if _AudioSegment is None:
            await update.message.reply_text(
                "Voice messages require pydub. "
                "Install with: pip install pydub"
            )
            return
        audio_cfg = self._caps("audio")
        if not audio_cfg.get("enabled", False):
            await update.message.reply_text(
                "Audio is not enabled for this provider."
            )
            return
        if not self._state["session_id"]:
            await update.message.reply_text(
                "No active session. Send /new to start one."
            )
            return
        voice = update.message.voice
        tg_file = await context.bot.get_file(voice.file_id)
        ogg_data = bytes(await tg_file.download_as_bytearray())
        max_mb = audio_cfg.get("max_size_mb", 25)
        if len(ogg_data) > max_mb * 1024 * 1024:
            await update.message.reply_text(
                f"Voice message exceeds the {max_mb}MB size limit."
            )
            return

        def _transcode() -> bytes:
            seg = _AudioSegment.from_ogg(io.BytesIO(ogg_data))
            buf = io.BytesIO()
            seg.export(buf, format="wav")
            return buf.getvalue()

        loop = asyncio.get_running_loop()
        try:
            wav_data = await loop.run_in_executor(None, _transcode)
        except Exception as exc:
            await update.message.reply_text(
                f"Failed to transcode voice message: {exc}"
            )
            return
        artifact_id = await self._upload_bytes(
            wav_data, "voice.wav", "audio/wav"
        )
        if not artifact_id:
            await update.message.reply_text("Failed to upload voice message.")
            return
        await self._complete_and_reply(
            update, context, f"@audio:{artifact_id}"
        )

    async def _on_video_note(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await update.message.reply_text("Video notes are not supported.")

    # ── Entry point ──────────────────────────────────────────────────────

    async def run(self) -> None:
        if not self._token:
            print(
                "TELEGRAM_BOT_TOKEN not set. "
                "Run: craftsman auth set TELEGRAM_BOT_TOKEN"
            )
            return

        tg_request = HTTPXRequest(
            http_version="1.1",
            httpx_kwargs={"verify": ssl.create_default_context()},
        )

        if not self._state["chat_id"]:
            bot = Bot(token=self._token, request=tg_request)
            async with bot:
                if not await self._pair(bot):
                    return

        self._http = httpx.AsyncClient(timeout=60.0)
        try:
            if not await self._login():
                return
            await self._reset_provider()
            await self._seed_tools()
            asyncio.create_task(self._run_dispatcher())

            if not self._state["session_id"]:
                sid = await self._create_session()
                if not sid:
                    print("Failed to create session on server.")
                    return
                self._state["session_id"] = sid
                self._save_state()
            await self._set_system_prompt(self._state["session_id"])

            self._app = (
                Application.builder()
                .token(self._token)
                .request(tg_request)
                .build()
            )
            self._register_handlers()
            print(
                f"Connected: chat_id={self._state['chat_id']},"
                f" session={self._state['session_id'][:8]}"
            )
            async with self._app:
                await self._app.updater.start_polling(
                    allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=False,
                )
                await self._app.start()
                stop = asyncio.Event()
                loop = asyncio.get_running_loop()
                for sig in (signal.SIGINT, signal.SIGTERM):
                    loop.add_signal_handler(sig, stop.set)
                await stop.wait()
                await self._app.updater.stop()
                await self._app.stop()
        finally:
            await self._http.aclose()
