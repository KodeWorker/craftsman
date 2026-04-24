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
uv run craftsman auth set LLM_BASE_URL
uv run craftsman auth set LLM_API_KEY
uv run craftsman auth set LLM_SSL_CRT   # optional, for self-signed certs
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

## Auth Credentials

Credentials are stored in the system keyring (not in config files).

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_BASE_URL` | Base URL of the OpenAI-compatible server (client) | _(empty)_ |
| `LLM_API_KEY` | API key (client) | _(empty)_ |
| `LLM_SSL_CRT` | Path to SSL certificate for self-signed servers (server) | _(empty)_ |
