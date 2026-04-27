import asyncio
import json
import os
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
                    if chunk.get("kind") == "content":
                        chunks.append(chunk["text"])
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

        try:
            await bot.get_updates(offset=-1, timeout=1)
        except Exception:
            pass

        offset = 0
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
            "  /artifacts — list artifacts in current session"
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

    async def _on_session_switch(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        await query.answer()
        session_id = query.data.split(":", 1)[1]
        self._state["session_id"] = session_id
        self._save_state()
        await query.edit_message_text(f"Switched to session {session_id[:8]}")

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

            if not self._state["session_id"]:
                sid = await self._create_session()
                if not sid:
                    print("Failed to create session on server.")
                    return
                self._state["session_id"] = sid
                self._save_state()

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
            await self._app.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=False,
            )
        finally:
            await self._http.aclose()
