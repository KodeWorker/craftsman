import asyncio
import json
import os
import signal
import ssl
from pathlib import Path

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


class TelegramClient:
    def __init__(self, host: str, port: int):
        self._entry_point = f"http://{host}:{port}"
        self._token = Auth.get_password("TELEGRAM_BOT_TOKEN")
        self._state = self._load_state()
        self._jwt: str | None = None
        self._http: httpx.AsyncClient | None = None
        self._app: Application | None = None
        self._model: str = ""
        self._ctx_used: int = 0
        self._ctx_total: int = 0
        self._prompt_tokens: int = 0
        self._completion_tokens: int = 0
        self._cost: float = 0.0

    # ── State ────────────────────────────────────────────────────────────

    def _state_path(self) -> Path:
        config = get_config()
        root = Path(os.path.expanduser(config["workspace"]["root"]))
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
        self._state_path().write_text(json.dumps(self._state))

    # ── Server API ───────────────────────────────────────────────────────

    async def _reset_provider(self) -> None:
        cfg = get_config().get("provider", {})
        await self._http.post(
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
            Path(os.path.expanduser(get_config()["workspace"]["root"]))
            / "system_prompt.md",
        ):
            if path.exists():
                return path.read_text().strip()
        return ""

    async def _set_system_prompt(self, session_id: str) -> None:
        prompt = self._read_system_prompt()
        if not prompt:
            return
        await self._http.put(
            f"{self._entry_point}/sessions/{session_id}/system",
            json={"system_prompt": prompt},
        )

    async def _create_session(self) -> str | None:
        resp = await self._http.post(f"{self._entry_point}/sessions/")
        if resp.status_code == 200:
            return resp.json().get("session_id")
        return None

    async def _get_sessions(self, limit: int = 5) -> list:
        resp = await self._http.get(
            f"{self._entry_point}/sessions/",
            params={"limit": limit},
        )
        if resp.status_code == 200:
            return resp.json().get("sessions", [])
        return []

    async def _get_artifacts(self, session_id: str) -> list:
        resp = await self._http.get(
            f"{self._entry_point}/artifacts/",
            params={"session_id": session_id},
        )
        if resp.status_code == 200:
            return resp.json().get("artifacts", [])
        return []

    async def _complete(self, session_id: str, text: str) -> str:
        chunks: list[str] = []
        async with self._http.stream(
            "POST",
            f"{self._entry_point}/sessions/{session_id}/completion",
            json={"message": {"role": "user", "content": text}},
        ) as resp:
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    kind = chunk.get("kind")
                    if kind == "content":
                        chunks.append(chunk["text"])
                    elif kind == "meta":
                        self._model = chunk.get("model", self._model)
                        self._ctx_used = chunk.get("ctx_used", self._ctx_used)
                        self._ctx_total = chunk.get(
                            "ctx_total", self._ctx_total
                        )
                        self._prompt_tokens += chunk.get("prompt_tokens", 0)
                        self._completion_tokens += chunk.get(
                            "completion_tokens", 0
                        )
                        self._cost += chunk.get("cost", 0.0)
                except json.JSONDecodeError:
                    pass
        return "".join(chunks)

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

        for _ in range(40):  # 40 × 3 s = 120 s timeout
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
            MessageHandler(cf & filters.TEXT & ~filters.COMMAND, self._on_text)
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
            "  /status — show model, session, token and cost info"
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
        resp = await self._http.post(
            f"{self._entry_point}/sessions/{sid}/clear"
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
        cfg_cmds = get_config().get("commands", [])
        limit, keep_turns = next(
            (
                (c.get("limit", 1000), c.get("keep_turns", 5))
                for c in cfg_cmds
                if c["name"] == "/compact"
            ),
            (1000, 5),
        )
        resp = await self._http.post(
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
        sid = self._state["session_id"]
        if not sid:
            await update.message.reply_text(
                "No active session. Send /new to start one."
            )
            return

        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action=ChatAction.TYPING
        )

        response = await self._complete(sid, update.message.text)
        if not response:
            await update.message.reply_text("(no response from server)")
            return

        max_len = 4096
        for i in range(0, len(response), max_len):
            await update.message.reply_text(response[i : i + max_len])

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
