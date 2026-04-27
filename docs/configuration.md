# Configuration

## Python Environment

### Runtime Environment

Requires Python 3.12+. Install dependencies with:

```bash
uv sync
```

### Development Environment

```bash
uv sync
uv run pre-commit install
```

## Craftsman Configuration

Run once to create `~/.craftsman/` and copy the default `craftsman.yaml`:

```bash
uv run craftsman init
```

This copies `craftsman.yaml` to `~/.craftsman/craftsman.yaml`. Edit that file
to configure the provider, logging, and workspace paths. Re-running `init` will
not overwrite an existing config.

Set credentials before starting the server:

```bash
uv run craftsman auth set LLM_API_KEY
uv run craftsman auth set LLM_SSL_CRT   # optional, for self-signed certs
```

## Provider Setup

Set `api_base` in `~/.craftsman/craftsman.yaml` to point at your LLM backend:

| Setup | `api_base` |
|---|---|
| llama.cpp direct (HTTP) | `http://localhost:<port>` |
| llama.cpp via Caddy (HTTPS) | `https://<host>` |
| Remote OpenAI-compatible API | `https://<host>` |

```yaml
provider:
  api_base: ""   # set to your LLM backend URL
```

**If using Caddy with `tls internal`** (self-signed CA), register the CA cert
path so litellm trusts it:

```bash
uv run craftsman auth set LLM_SSL_CRT
# enter path to Caddy root CA:
# ~/.local/share/caddy/pki/authorities/local/root.crt
```

## Session Management

```bash
uv run craftsman sess list   [--host] [--port] [--project-id] [--limit]
uv run craftsman sess delete [<id|prefix|title>] [--host] [--port]
```

## User Management

Manage users directly (no server required):

```bash
uv run craftsman user register
uv run craftsman user list
uv run craftsman user delete <username>
```

Save credentials to keyring (no server required):

```bash
uv run craftsman user login
```

Credentials are stored in the system keyring. `craftsman chat` and `craftsman run` fetch a JWT token automatically on start and refresh it transparently on expiry.

## Telegram Bot Setup

### Prerequisites

- Public HTTPS endpoint (ngrok for dev, VPS for production)
- Bot token from [@BotFather](https://t.me/BotFather)

### Security Warning

Tunnel services (ngrok, Cloudflare Tunnel, localtunnel) terminate TLS on
their servers — the operator can read all webhook traffic, including
conversation content. **Do not use tunnel services in production.**

For production: run craftsman on a VPS with a public IP. Let Caddy or
Certbot manage a real TLS certificate. No third party sees your traffic.

### Steps

**1. Register bot token in keyring:**

```bash
uv run craftsman auth set TELEGRAM_BOT_TOKEN
```

**2. Expose server via public HTTPS (ngrok for dev):**

```bash
ngrok http <port>
```

**3. Edit `~/.craftsman/craftsman.yaml`:**

```yaml
telegram:
  enabled: true
  webhook_url: "https://yourdomain.com/telegram/webhook"
  allowed_chat_ids: []  # empty = allow all
```

**4. Register a craftsman user and generate a link token:**

```bash
uv run craftsman user register <username>
uv run craftsman user telegram-token <username>
# prints a one-time token valid for 10 minutes
```

**5. Start the server:**

```bash
uv run craftsman server --port <port>
```

**6. In Telegram, send to your bot:**

```
/start <token>
```

Account is now linked. Start chatting.

---

## Auth Credentials

Credentials are stored in the system keyring (not in config files).

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_API_KEY` | API key (client) | _(empty)_ |
| `LLM_SSL_CRT` | Path to SSL certificate for self-signed servers (server) | _(empty)_ |
| `TELEGRAM_BOT_TOKEN` | Telegram bot API token from BotFather | _(empty)_ |
