# Telegram Bot Setup

`craftsman telegram` runs on your machine, long-polls Telegram, and proxies
messages to the craftsman server. Each user holds their own bot token.
No public HTTPS required.

## Prerequisites

- Bot token from [@BotFather](https://t.me/BotFather)
- A running craftsman server (`craftsman server`)
- A registered craftsman user (`craftsman user register`)

## Steps

**1. Register bot token in keyring:**

```bash
uv run craftsman auth set TELEGRAM_BOT_TOKEN
```

**2. Save craftsman credentials (if not already done):**

```bash
uv run craftsman user login
```

**3. Start the bot client:**

```bash
uv run craftsman telegram [--host localhost] [--port 6969]
```

**First run only** — pairing handshake:

```
Open t.me/<your-bot-username> on your phone and send any message.
Paired with chat_id 123456789. Auto-connect saved.
```

The bot captures your `chat_id` from the first message and saves state to
`~/.craftsman/telegram.json`. Subsequent runs auto-connect without the
handshake.

**4. Start chatting.** Send any text to the bot. Available commands:

```
/help      — show command list
/new       — end session; start fresh
/sessions  — list recent sessions (tap to switch)
/artifacts — list artifacts in current session
/clear     — clear session history
/compact   — summarize and reduce context size
```

## Resetting the Pairing

Delete `~/.craftsman/telegram.json` to force a new pairing handshake on
the next `craftsman telegram` run.
