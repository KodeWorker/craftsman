# Phase 4: Telegram Bot Integration

## Goals

Wire Telegram as an alternative input channel. Bot receives messages from
Telegram, resolves/creates a craftsman session per chat, forwards to the
existing completion pipeline, and replies back. No parallel infrastructure —
reuse the artifact upload and multimodal flows from Phase 3.

## Architecture

Webhook-based; Telegram pushes updates to the server rather than polling.
Requires a publicly reachable TLS-terminated URL (ngrok for local dev).

```
Telegram → POST /telegram/webhook → TelegramRouter
         → resolve user (telegram_id → craftsman user)
         → resolve/create session (chat_id → session_id)
         → handle media (transcode if needed → POST /artifacts/)
         → POST /sessions/{id}/completion
         → send reply via Telegram Bot API
```

`TelegramRouter` registers `/telegram/webhook` on the FastAPI app alongside
`SessionsRouter` and `ArtifactsRouter`.

```
Server
├── SessionsRouter   → /sessions/*
├── ArtifactsRouter  → /artifacts/*
└── TelegramRouter   → /telegram/*
```

`/health` and `/subagent/run` remain directly on `Server`.

## Design Decisions

### Telegram user → craftsman user

Telegram users must link to an existing craftsman account (registered via
`craftsman users register`). Auto-creation is not allowed — it would bypass
the managed user registry.

**Link flow:**

1. Admin creates craftsman user: `craftsman users register <username>`
2. Admin (or user) generates a one-time link token:
   `craftsman users telegram-token <username>`
   — prints a short-lived token (TTL: 10 min), stored in `telegram_link_tokens`
3. User sends `/start <token>` to the bot
4. Bot verifies token (not expired, not used), writes `telegram_id` into
   `users.telegram_id`, deletes the token row
5. Bot creates a session and confirms linkage

Unlinked chat_ids are rejected with: "Send `/start <token>` to link your
account. Ask your admin for a token."

`telegram_id` added to the `users` table DDL in `structure.py` (not a
migration — recreate DB to pick up).

### Session mapping

One persistent session per Telegram chat_id. New `telegram_chats` table
tracks the mapping:

```sql
CREATE TABLE IF NOT EXISTS telegram_chats (
    chat_id    TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id),
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

`/new` command ends the current session and creates a fresh one.

### Streaming / response delivery

Telegram does not support streaming.

1. Send `sendChatAction(typing)` immediately on receipt.
2. Buffer full response from completion stream.
3. Send as one `sendMessage`; split at 4096-char Telegram limit if needed.

### Bot commands

| Command | Action |
|---------|--------|
| `/start <token>` | Link Telegram account to craftsman user; create initial session |
| `/new` | End current session; start fresh |
| `/sessions` | List 5 most recent sessions (id prefix + last message) |
| `/artifacts` | List artifacts uploaded in current session |
| `/help` | Show command list |

### Media handling

Reuse Phase 3 artifact upload flow. Bot downloads Telegram file, uploads to
`POST /artifacts/`, injects `@image:<uuid>` / `@audio:<uuid>` token.

| Telegram type | Disposition |
|---------------|-------------|
| `photo` | JPEG → artifact upload (vision) |
| `document` (image) | original format → artifact upload |
| `audio` | MP3/M4A → artifact upload (audio) |
| `voice` | OGG/OPUS → transcode WAV → artifact upload |
| `video_note` | reject with message |

Transcoding: `pydub` shells out to `ffmpeg`. Both must be installed.

### Capability guard

Same guard as Phase 3: if `capabilities.vision.enabled` is false and a
photo arrives, reply with a capabilities-disabled error message.

## New Module: `telegram_bot.py`

Handles bot initialization, webhook registration, message/command dispatch,
media download + transcode, and craftsman API calls.

`TelegramRouter` is a thin HTTP shim; all logic lives in `telegram_bot.py`.

## Configuration

```yaml
telegram:
  enabled: false
  token: ""          # or keyring key TELEGRAM_BOT_TOKEN
  webhook_url: ""    # public HTTPS URL; required
  allowed_chat_ids: []  # empty = allow all
```

`TELEGRAM_BOT_TOKEN` stored in keyring via `craftsman auth set TELEGRAM_BOT_TOKEN`.

## Dependencies

| Package | Purpose |
|---------|---------|
| `python-telegram-bot[webhooks]` | async Bot API wrapper |
| `pydub` | OGG/OPUS → WAV transcoding |
| `ffmpeg` | system dep; pydub shells out to it |

## Schema Changes

`users` DDL in `structure.py` — add `telegram_id`:

```sql
CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  telegram_id   TEXT UNIQUE,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
```

New tables added to DDL:

```sql
CREATE TABLE IF NOT EXISTS telegram_chats (
    chat_id    TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id),
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS telegram_link_tokens (
    token      TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

`StructureDB` new methods:
- `link_telegram_user(telegram_id, user_id) -> None` — writes `telegram_id` into `users` row
- `get_user_by_telegram_id(telegram_id) -> Row | None`
- `create_telegram_link_token(user_id, ttl_minutes=10) -> str` — returns token
- `consume_telegram_link_token(token) -> str | None` — verifies + deletes; returns `user_id` or `None`
- `get_telegram_chat(chat_id) -> Row | None`
- `upsert_telegram_chat(chat_id, user_id, session_id) -> None`

## Checklist

### Schema
- [ ] Add `telegram_id TEXT UNIQUE` to `users` DDL in `structure.py`
- [ ] Add `telegram_chats` table to DDL in `structure.py`
- [ ] Add `telegram_link_tokens` table to DDL in `structure.py`
- [ ] `StructureDB`: `link_telegram_user`, `get_user_by_telegram_id`, `create_telegram_link_token`, `consume_telegram_link_token`, `get_telegram_chat`, `upsert_telegram_chat`

### Configuration
- [ ] `craftsman.yaml` `telegram` block (enabled, token, webhook_url, allowed_chat_ids)
- [ ] Keyring: `TELEGRAM_BOT_TOKEN` (already generic — no new auth code needed)

### Server
- [ ] `TelegramRouter` — `POST /telegram/webhook` endpoint
- [ ] Register `TelegramRouter` in `Server.__init__`
- [ ] Startup hook: register webhook URL with Telegram API

### Bot logic (`telegram_bot.py`)
- [ ] `TelegramBot` class — wraps `python-telegram-bot` Application
- [ ] `/start <token>` handler — `consume_telegram_link_token`, bind `telegram_id`, create session
- [ ] `/new` handler — end session, create fresh
- [ ] `/sessions` handler — list recent sessions
- [ ] `/artifacts` handler — list session artifacts
- [ ] `/help` handler
- [ ] Text message handler — resolve user/session, call completion, reply
- [ ] Photo handler — download JPEG, upload artifact, inject token
- [ ] Document handler (images) — download, upload artifact, inject token
- [ ] Audio handler — download MP3/M4A, upload artifact, inject token
- [ ] Voice handler — download OGG, transcode → WAV, upload artifact, inject token
- [ ] `video_note` handler — reject with message
- [ ] `sendChatAction(typing)` before all completions
- [ ] Split long responses at 4096-char Telegram limit

### CLI
- [ ] `craftsman users telegram-token <username>` — generate + print one-time link token (TTL 10 min)
- [ ] `craftsman server` — print webhook URL on startup when telegram enabled
