# Phase 4: Telegram Bot Integration

Two sub-phases with distinct capability tiers:

- **4.1** — Standalone chatbot. Client-side long-polling. No tool use.
- **4.2** — Paired mode. `craftsman telegram` shares a session with an active
  `craftsman chat`; tool use works because the CLI client executes tools.

---

## Phase 4.1: Standalone Chatbot

### Goals

`craftsman telegram` — a client command that runs on the user's machine,
long-polls Telegram, and proxies messages to the craftsman server for
completion. Each user holds their own bot token. No public HTTPS required.
No server changes needed.

### Architecture

```
craftsman telegram (client process)
├── Telegram long-poll loop (asyncio task, get_updates)
├── JWT auth → server  (same flow as craftsman chat)
├── session management via /sessions API
└── chat_id persisted in local config
```

Server is unmodified — just a completion + session API.
`TELEGRAM_BOT_TOKEN` lives in the user's keyring, never on the server.

### Pairing (Initial Setup)

First run (no `chat_id` saved):
1. Client fetches bot username via `getMe`.
2. Prints: `open t.me/<username> on your phone and send any message`.
3. Long-polls until first message arrives → captures `chat_id`.
4. Saves `chat_id` to `~/.craftsman/craftsman.yaml`.
5. Sends confirmation to phone.

Subsequent runs: `chat_id` loaded from config → auto-connect, no handshake.

### Session Management

On start: resume last session (stored in config) or create a new one.
Session ID persisted alongside `chat_id` in config.

### Response Delivery

1. Send `sendChatAction(typing)` on receipt.
2. Buffer full response from server SSE stream.
3. Send as one message; split at 4096-char limit if needed.

### Bot Commands

Handled client-side by parsing incoming `/command` messages.

| Command | Action |
|---------|--------|
| `/new` | End session; create fresh one on server |
| `/sessions` | List 5 most recent sessions; inline keyboard to switch |
| `/artifacts` | List artifacts in current session |
| `/help` | Show command list |

### Media Handling

Client downloads Telegram file, uploads to server artifact pipeline, injects
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

### Configuration

```yaml
telegram:
  chat_id: 0        # auto-saved after first pairing; 0 = not paired
  session_id: ""    # last active session; auto-resumed on start
```

Token stored in keyring as `TELEGRAM_BOT_TOKEN` — not in yaml.

### Schema Changes

None. Server unchanged. No new tables.

### Dependencies

| Package | Purpose |
|---------|---------|
| `python-telegram-bot` | async Bot API wrapper (long-poll only; drop `[webhooks]` extra) |
| `pydub` | OGG/OPUS → WAV transcoding |
| `ffmpeg` | system dep; pydub shells out to it |

### Checklist

#### Configuration
- [ ] `craftsman.yaml`: add `telegram.chat_id`, `telegram.session_id`
- [ ] Keyring: `TELEGRAM_BOT_TOKEN`

#### Server
- [ ] Remove `TelegramBot` from `server.py`
- [ ] Remove `/telegram/webhook` route
- [ ] Remove `telegram_bot.py` server-side implementation

#### Schema cleanup
- [ ] Revert `telegram_id` column from `users` DDL in `structure.py`
- [ ] Remove `telegram_chats` table from DDL
- [ ] Remove `telegram_link_tokens` table from DDL
- [ ] Remove 6 telegram methods from `StructureDB`

#### Client (`telegram_bot.py` → rewrite as client)
- [ ] `TelegramClient` class: `__init__`, `start`, `stop`
- [ ] First-run pairing: `getMe` → print username → poll until first message → save `chat_id`
- [ ] Auto-connect: load `chat_id` from config on start
- [ ] Long-poll loop (asyncio task)
- [ ] `/new` handler
- [ ] `/sessions` handler — inline keyboard to switch
- [ ] `/artifacts` handler
- [ ] `/help` handler
- [ ] Text message handler — call server `/sessions/{id}/chat`, reply
- [ ] `sendChatAction(typing)` before completions
- [ ] Split responses at 4096-char limit
- [ ] Photo handler
- [ ] Document handler (images)
- [ ] Audio handler
- [ ] Voice handler — transcode OGG → WAV
- [ ] `video_note` handler — reject

#### CLI
- [ ] `craftsman telegram` command — entry point, runs `TelegramClient`
- [ ] Remove `craftsman users telegram-token` command (no longer needed)
- [ ] Remove webhook URL startup log from `craftsman server`

---

## Phase 4.2: Paired Mode (Agentic)

### Goals

`craftsman telegram` shares a session with a running `craftsman chat`.
Phone messages injected into the shared session; CLI executes tool calls.
Full agentic capabilities when paired.

### Pairing Flow

No server-side tokens needed. Both processes run on the same machine and
share config.

1. `craftsman chat` is running with session_id X.
2. User types `/pair` in CLI → CLI prints session_id X.
3. User sends `/pair <session_id>` to bot from phone.
4. `craftsman telegram` switches active session to X; saves to config.
5. Phone messages now flow into session X alongside CLI keyboard input.

Unpair: `/unpair` from phone or CLI, or `craftsman telegram` process exits.

### Message Flow (Paired)

```
Phone msg → craftsman telegram (client)
          → POST /sessions/{paired_id}/chat
          → server completion (tool calls returned)
          → craftsman chat (CLI) picks up tool call SSE events, executes tools
          → server produces final text
          → craftsman telegram polls for final response → send to phone
```

### Response Delivery (Paired)

`craftsman telegram` subscribes to the SSE stream for the paired session,
same as the CLI client. Final `content` chunks forwarded to phone.

### Bot Commands (additions)

| Command | Action |
|---------|--------|
| `/pair <session_id>` | Switch to shared session |
| `/unpair` | Revert to standalone session |
| `/status` | Show current mode and active session ID |

### CLI Slash Commands (additions)

| Command | Action |
|---------|--------|
| `/pair` | Print current session_id for use with `/pair` on phone |
| `/unpair` | Detach (no-op if not paired) |

### Checklist

#### Client
- [ ] `/pair <session_id>` handler — update config, confirm to phone
- [ ] `/unpair` handler — revert to standalone session
- [ ] `/status` handler
- [ ] Paired SSE subscriber task
- [ ] Forward final response chunks to phone

#### CLI slash commands
- [ ] `/pair` — print session_id
- [ ] `/unpair` — print confirmation
