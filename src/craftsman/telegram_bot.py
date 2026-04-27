from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from craftsman.auth import Auth
from craftsman.configure import get_config


class TelegramBot:
    def __init__(self, librarian, provider):
        config = get_config().get("telegram", {})
        self.enabled = config.get("enabled", False)
        self.webhook_url = config.get("webhook_url", "")
        self.ssl_certfile = config.get("ssl_certfile", "")
        self.ssl_keyfile = config.get("ssl_keyfile", "")
        token = Auth.get_password("TELEGRAM_BOT_TOKEN")
        self.app = Application.builder().token(token).build()
        self.librarian = librarian
        self.provider = provider
        self._register_handlers()

    def _register_handlers(self):
        # Register command handlers for /help, /start, /new, /sessions,
        # and /artifacts
        self.app.add_handler(CommandHandler("help", self._on_help))
        self.app.add_handler(CommandHandler("start", self._on_start))
        self.app.add_handler(CommandHandler("new", self._on_new))
        self.app.add_handler(CommandHandler("sessions", self._on_sessions))
        self.app.add_handler(CommandHandler("artifacts", self._on_artifacts))

        self.app.add_handler(
            CallbackQueryHandler(self._on_session_switch, pattern=r"^switch:")
        )
        # Register a message handler for text messages
        self.app.add_handler(MessageHandler(filters.TEXT, self._on_text))

    async def initialize(self):
        await self.app.initialize()
        await self.app.start()  # starts update queue workers

    async def shutdown(self):
        await self.app.stop()
        await self.app.shutdown()

    async def process_update(self, data: dict):
        update = Update.de_json(data, self.app.bot)
        await self.app.process_update(update)

    async def _on_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await update.message.reply_text(
            "Available commands:\n"
            "  /help - Show this help message\n"
            "  /start - Link account; create initial session\n"
            "  /new - End session; start fresh\n"
            "  /sessions - List 5 most recent sessions with inline keyboard; "
            "tap to switch active session\n"
            "  /artifacts - List available artifacts"
        )

    async def _on_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        if not context.args:
            await update.message.reply_text(
                "Send /start <token> to link your account."
            )
            return

        token = context.args[0]
        telegram_id = str(update.effective_user.id)
        chat_id = str(update.effective_chat.id)

        db = self.librarian.structure_db
        user_id = db.consume_telegram_link_token(token)
        if user_id is None:
            await update.message.reply_text(
                "Invalid or expired token. Ask your admin for a new one."
            )
            return

        db.link_telegram_user(telegram_id, user_id)
        session_id = db.create_session(user_id=user_id)
        db.upsert_telegram_chat(chat_id, user_id, session_id)

        await update.message.reply_text(
            "Account linked. Session created. Start chatting!"
        )

    async def _on_new(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        chat_id = str(update.effective_chat.id)
        db = self.librarian.structure_db

        chat = db.get_telegram_chat(chat_id)
        if chat is None:
            await update.message.reply_text(
                "No linked account. Send /start <token> first."
            )
            return

        if chat["session_id"]:
            db.end_session(chat["session_id"])

        session_id = db.create_session(user_id=chat["user_id"])
        db.upsert_telegram_chat(chat_id, chat["user_id"], session_id)

        await update.message.reply_text("Session reset. Fresh start!")

    async def _on_sessions(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        chat_id = str(update.effective_chat.id)
        db = self.librarian.structure_db

        chat = db.get_telegram_chat(chat_id)
        if chat is None:
            await update.message.reply_text(
                "No linked account. Send /start <token> first."
            )
            return

        sessions = db.list_sessions(user_id=chat["user_id"], limit=5)
        if not sessions:
            await update.message.reply_text("No sessions found.")
            return

        buttons = [
            [
                InlineKeyboardButton(
                    f"{'* ' if s['id'] == chat['session_id'] else ''}"
                    f"{s['created_at'][:16]} — {(s['title'] or s['id'][:8])}",
                    callback_data=f"switch:{s['id']}",
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
    ):
        chat_id = str(update.effective_chat.id)
        db = self.librarian.structure_db

        chat = db.get_telegram_chat(chat_id)
        if chat is None:
            await update.message.reply_text(
                "No linked account. Send /start <token> first."
            )
            return

        if not chat["session_id"]:
            await update.message.reply_text("No active session.")
            return

        artifacts = db.get_artifacts(session_id=chat["session_id"])
        if not artifacts:
            await update.message.reply_text("No artifacts in current session.")
            return

        lines = [
            f"{a['filename']} ({a['mime_type'] or 'unknown'}, {a['id'][:8]})"
            for a in artifacts
        ]
        await update.message.reply_text("\n".join(lines))

    async def _on_session_switch(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        await query.answer()

        chat_id = str(query.message.chat.id)
        session_id = query.data.split(":", 1)[1]
        db = self.librarian.structure_db

        chat = db.get_telegram_chat(chat_id)
        if chat is None:
            await query.edit_message_text(
                "No linked account. Send /start <token> first."
            )
            return

        db.upsert_telegram_chat(chat_id, chat["user_id"], session_id)
        msgs = db.get_messages(session_id)
        preview = (
            msgs[-1]["content"][:80] + "..." if msgs else "(empty session)"
        )
        await query.edit_message_text(
            f"Switched to session {session_id[:8]}\nLast: {preview}"
        )

    async def _on_text(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        chat_id = str(update.effective_chat.id)
        db = self.librarian.structure_db

        chat = db.get_telegram_chat(chat_id)
        if chat is None:
            await update.message.reply_text(
                "No linked account. Send /start <token> first."
            )
            return

        session_id = chat["session_id"]
        if not session_id:
            await update.message.reply_text(
                "No active session. Send /new to start one."
            )
            return

        await context.bot.send_chat_action(
            chat_id=chat_id, action=ChatAction.TYPING
        )

        user_msg = {"role": "user", "content": update.message.text}
        messages, _ = self.librarian.retrieve_messages(session_id)
        messages.append(user_msg)

        chunks = []
        async for kind, chunk in self.provider.completion(messages):
            if kind == "content":
                chunks.append(chunk)
        full_response = "".join(chunks)

        self.librarian.store_message(session_id, user_msg)
        self.librarian.store_message(
            session_id, {"role": "assistant", "content": full_response}
        )

        max_len = 4096
        for i in range(0, len(full_response), max_len):
            await update.message.reply_text(full_response[i : i + max_len])
