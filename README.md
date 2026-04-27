# craftsman

Self-hosted autonomous agent framework. Zero daemons.

## Setup

1. [docs/setup/llama.cpp.md](docs/setup/llama.cpp.md)
2. [docs/configuration.md](docs/configuration.md)
3. [docs/setup/telegram.md](docs/setup/telegram.md) — optional

## Usage

```shell
# Basic operations
uv run craftsman init
uv run craftsman server [--port]
uv run craftsman chat [--resume <id|prefix|title>] [--host] [--port]
uv run craftsman run <prompt> [--host] [--port]
uv run craftsman dev

# Telegram bot (client-side, long-poll)
uv run craftsman telegram [--host] [--port]

# Authentication
uv run craftsman auth list
uv run craftsman auth set <key>
uv run craftsman auth get <key>
uv run craftsman auth delete [<key>]

# User management
uv run craftsman user list
uv run craftsman user register [<username>]
uv run craftsman user delete [<username>]
uv run craftsman user login

# Session management
uv run craftsman sess list [--host] [--port] [--project-id] [--limit]
uv run craftsman sess delete [<id|prefix|title>] [--host] [--port]

# Artifact management
uv run craftsman arti list [--host] [--port]
uv run craftsman arti delete [<id|prefix>] [--host] [--port]
```

## Docs

- [Configuration](docs/configuration.md)
- [Schema](docs/schema.md)
- [API](docs/api.md)
- [Roadmap](docs/roadmap.md)
