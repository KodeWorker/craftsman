from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


class TelegramBot:
    def __init__(self, token, librarian, provider):
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
        pass

    async def _on_new(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        pass

    async def _on_sessions(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        pass

    async def _on_artifacts(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        pass

    async def _on_session_switch(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        pass

    async def _on_text(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        pass
