# Phase 4: Telegram Bot Integration

`craftsman telegram` — client-side long-polling bot. Each user holds their
own bot token. No public HTTPS required. No server changes needed.

---

## Architecture

```
craftsman telegram (client process)
├── Telegram long-poll loop (asyncio, get_updates)
├── JWT auth → server  (same flow as craftsman chat)
├── session management via /sessions API
└── state (chat_id, session_id) persisted in ~/.craftsman/telegram.json
```

Server is unmodified — completion + session API only.
`TELEGRAM_BOT_TOKEN` lives in the user's keyring, never on the server.

## Pairing (Initial Setup)

First run (no `chat_id` saved):
1. Deletes any registered webhook (`delete_webhook`) so `get_updates` works.
2. Fetches bot username via `getMe`.
3. Prints: `open t.me/<username> on your phone and send any message`.
4. Long-polls until first message arrives → captures `chat_id`.
5. Saves state to `~/.craftsman/telegram.json`.
6. Sends confirmation to phone.

Subsequent runs: `chat_id` loaded from state → auto-connect, no handshake.

## Session Management

On start: resume last session (from state) or create a new one.
System prompt loaded from `.craftsman/system_prompt.md` or
`~/.craftsman/system_prompt.md` — same lookup as `craftsman chat`.

## Bot Commands

| Command | Action |
|---------|--------|
| `/help` | Show command list |
| `/new` | Create fresh session; load system prompt |
| `/sessions` | List 5 most recent sessions; inline keyboard to switch |
| `/artifacts` | List artifacts in current session |
| `/clear` | Clear session history |
| `/compact` | Summarize and reduce context size |

## Response Delivery

1. Send `sendChatAction(typing)` on receipt.
2. Buffer full response from server SSE stream.
3. Send as one message; split at 4096-char limit if needed.

## Dependencies

| Package | Purpose |
|---------|---------|
| `python-telegram-bot>=22.7` | async Bot API wrapper (long-poll) |
| `httpx>=0.28` | async HTTP client for server API calls |

## Checklist

### Server cleanup
- [x] Remove `TelegramBot` from `server.py`
- [x] Remove `/telegram/webhook` route
- [x] Revert `telegram_id` column from `users` DDL
- [x] Remove `telegram_chats` and `telegram_link_tokens` tables
- [x] Remove 6 telegram methods from `StructureDB`
- [x] Remove `craftsman users telegram-token` CLI command

### Client (`telegram_bot.py`)
- [x] `TelegramClient` class
- [x] First-run pairing: `delete_webhook` → `getMe` → poll → save `chat_id`
- [x] Auto-connect on subsequent runs
- [x] Provider reset (`POST /reset`) on startup
- [x] System prompt loading (`PUT /sessions/{id}/system`)
- [x] Long-poll loop via PTB `updater.start_polling()`
- [x] `/help`, `/new`, `/sessions`, `/artifacts`, `/clear`, `/compact` handlers
- [x] Inline keyboard session switching (`CallbackQueryHandler`)
- [x] Last-message preview in session switch confirmation
- [x] Text message handler — completion → reply
- [x] `sendChatAction(typing)` before completions
- [x] Split responses at 4096-char limit
- [x] State persisted in `~/.craftsman/telegram.json`

### CLI
- [x] `craftsman telegram [--host] [--port]` command

### Docs
- [x] `docs/configuration.md` — Telegram Bot Setup section
- [x] `docs/plan/phase4.md` — finalized

### Deferred
- [ ] Media handlers (photo, document, audio, voice) — Phase 4.x
- [ ] Paired/mirroring mode — not planned
