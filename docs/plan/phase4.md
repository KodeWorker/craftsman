# Phase 4: Telegram Bot Integration

Two sub-phases with distinct capability tiers:

- **4.1** — Standalone chatbot. Server-side only, text/media, no tool use.
- **4.2** — Paired mode. Bot hijacks an active CLI chat session; tool use works because CLI client executes tools.

---

## Phase 4.1: Standalone Chatbot

### Goals

Telegram bot as a remote chatbot. Server handles completion directly.
No tool use — agentic capabilities unavailable in this mode.

### Architecture

```
Telegram → POST /telegram/webhook → TelegramRouter
         → resolve user (telegram_id)
         → resolve/create session (chat_id)
         → handle media (transcode if needed → artifact upload)
         → librarian + provider (server-side, direct call)
         → buffer response → Telegram sendMessage
```

`TelegramRouter` sits alongside `SessionsRouter` and `ArtifactsRouter`:

```
Server
├── SessionsRouter   → /sessions/*
├── ArtifactsRouter  → /artifacts/*
└── TelegramRouter   → /telegram/*
```

Calls `librarian` and `provider` directly — no self-HTTP calls.

### User Linking

Telegram users must link to an existing craftsman account. Auto-creation
bypasses the managed user registry and is not allowed.

**Link flow:**

1. Admin creates craftsman user: `craftsman users register <username>`
2. Generate one-time link token: `craftsman users telegram-token <username>`
   — TTL 10 min, stored in `telegram_link_tokens`
3. User sends `/start <token>` to bot
4. Bot verifies token (not expired, not used), writes `telegram_id` into
   `users.telegram_id`, deletes token row
5. Bot creates session, confirms linkage

Unlinked chat_ids rejected: "Send `/start <token>` to link your account."

### Session Mapping

One persistent session per `chat_id`. `telegram_chats` table tracks mapping.
`/new` ends current session and creates a fresh one.

### Response Delivery

Telegram does not support streaming.

1. Send `sendChatAction(typing)` on receipt.
2. Buffer full response from completion stream.
3. Send as one `sendMessage`; split at 4096-char limit if needed.

### Bot Commands

| Command | Action |
|---------|--------|
| `/start <token>` | Link account; create initial session |
| `/new` | End session; start fresh |
| `/sessions` | List 5 most recent sessions |
| `/artifacts` | List artifacts in current session |
| `/help` | Show command list |

### Media Handling

Bot downloads Telegram file, uploads via artifact pipeline, injects
`@image:<uuid>` / `@audio:<uuid>` token into completion request.

| Telegram type | Disposition |
|---------------|-------------|
| `photo` | JPEG → artifact upload (vision) |
| `document` (image) | original format → artifact upload |
| `audio` | MP3/M4A → artifact upload (audio) |
| `voice` | OGG/OPUS → transcode WAV → artifact upload |
| `video_note` | reject with message |

Transcoding: `pydub` + `ffmpeg` (system dep).

### Capability Guard

If `capabilities.vision.enabled` is false and photo arrives, reply with
capabilities-disabled message instead of crashing.

### Schema Changes

`users` DDL — add `telegram_id`:

```sql
CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  telegram_id   TEXT UNIQUE,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
```

New tables:

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
- `link_telegram_user(telegram_id, user_id) -> None`
- `get_user_by_telegram_id(telegram_id) -> Row | None`
- `create_telegram_link_token(user_id, ttl_minutes=10) -> str`
- `consume_telegram_link_token(token) -> str | None`
- `get_telegram_chat(chat_id) -> Row | None`
- `upsert_telegram_chat(chat_id, user_id, session_id) -> None`

### Configuration

```yaml
telegram:
  enabled: false
  token: ""          # or keyring key TELEGRAM_BOT_TOKEN
  webhook_url: ""    # public HTTPS URL; required
  allowed_chat_ids: []  # empty = allow all
```

### Dependencies

| Package | Purpose |
|---------|---------|
| `python-telegram-bot[webhooks]` | async Bot API wrapper |
| `pydub` | OGG/OPUS → WAV transcoding |
| `ffmpeg` | system dep; pydub shells out to it |

### Checklist

#### Schema
- [ ] Add `telegram_id TEXT UNIQUE` to `users` DDL in `structure.py`
- [ ] Add `telegram_chats` table to DDL in `structure.py`
- [ ] Add `telegram_link_tokens` table to DDL in `structure.py`
- [ ] `StructureDB`: `link_telegram_user`, `get_user_by_telegram_id`, `create_telegram_link_token`, `consume_telegram_link_token`, `get_telegram_chat`, `upsert_telegram_chat`

#### Configuration
- [ ] `craftsman.yaml` `telegram` block
- [ ] Keyring: `TELEGRAM_BOT_TOKEN`

#### Server
- [ ] `TelegramRouter` — `POST /telegram/webhook`
- [ ] Register `TelegramRouter` in `Server.__init__`
- [ ] Startup: register webhook URL with Telegram API

#### Bot logic (`telegram_bot.py`)
- [ ] `TelegramBot` class
- [ ] `/start <token>` handler — consume token, bind `telegram_id`, create session
- [ ] `/new` handler
- [ ] `/sessions` handler
- [ ] `/artifacts` handler
- [ ] `/help` handler
- [ ] Text message handler — resolve user/session, call completion, reply
- [ ] Photo handler
- [ ] Document handler (images)
- [ ] Audio handler
- [ ] Voice handler — transcode OGG → WAV
- [ ] `video_note` handler — reject
- [ ] `sendChatAction(typing)` before completions
- [ ] Split responses at 4096-char limit

#### CLI
- [ ] `craftsman users telegram-token <username>` — generate link token
- [ ] `craftsman server` — print webhook URL on startup when enabled

---

## Phase 4.2: Paired Mode (Agentic)

### Goals

Telegram bot hijacks an active CLI chat session. CLI client remains
connected and executes tool calls; bot relays messages in both directions.
Full agentic capabilities enabled when paired.

### Pairing Flow

1. User starts CLI chat: `craftsman chat`
2. User runs `/pair` slash command in CLI — generates a short-lived pair
   token (TTL: 5 min), stored server-side keyed to the session_id
3. User sends `/pair <token>` to Telegram bot
4. Bot verifies token, records `paired_session_id` in `telegram_chats`
5. Bot now injects messages into that session; CLI client executes tool calls

Unpair: `/unpair` in CLI or bot, or session ends.

### Message Flow (Paired)

```
Telegram msg → bot injects into paired session_id
             → server streams completion (tool calls included)
             → CLI client picks up tool calls, executes, returns results
             → server produces final text response
             → bot polls/subscribes for response → forwards to Telegram
```

### Response Subscription

CLI client streams via SSE. Bot needs the same — server must support
multiple concurrent SSE subscribers on one session, or bot polls
`GET /sessions/{id}/messages` for new assistant messages since its
last injected user message.

Polling is simpler; SSE fanout deferred unless latency is unacceptable.

### Session State in `telegram_chats`

Add `paired_session_id` column:

```sql
ALTER TABLE telegram_chats ADD COLUMN paired_session_id TEXT
    REFERENCES sessions(id) ON DELETE SET NULL;
```

Or include in DDL from the start (no migration needed if added before 4.1
ships).

### Bot Commands (additions)

| Command | Action |
|---------|--------|
| `/pair <token>` | Attach bot to active CLI session |
| `/unpair` | Detach; fall back to standalone mode |
| `/status` | Show current mode (standalone / paired to session `<id>`) |

### CLI Slash Commands (additions)

| Command | Action |
|---------|--------|
| `/pair` | Generate pair token; print for user to send to bot |
| `/unpair` | Detach bot from this session |

### Checklist

#### Schema
- [ ] Add `paired_session_id` to `telegram_chats` DDL (before 4.1 ships)
- [ ] `StructureDB`: `set_paired_session`, `clear_paired_session`
- [ ] `StructureDB`: `create_pair_token(session_id) -> str`, `consume_pair_token(token) -> str | None`
- [ ] New table `telegram_pair_tokens` (same shape as `telegram_link_tokens`)

#### Server
- [ ] `POST /telegram/pair` — generate pair token for a session (auth required)
- [ ] Bot inject endpoint or reuse existing message POST with session switching

#### Bot logic
- [ ] `/pair <token>` handler — consume token, set `paired_session_id`
- [ ] `/unpair` handler — clear `paired_session_id`
- [ ] `/status` handler
- [ ] Paired message handler — inject to `paired_session_id`, poll for response
- [ ] Response poller — `GET /sessions/{id}/messages?after=<msg_id>`

#### CLI
- [ ] `/pair` slash command — call `POST /telegram/pair`, print token
- [ ] `/unpair` slash command
