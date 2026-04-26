# craftsman

Self-hosted autonomous agent framework. Zero daemons.

## Setup

1. [docs/setup/llama.cpp.md](docs/setup/llama.cpp.md)
2. [docs/configuration.md](docs/configuration.md)

## Usage

```shell
# Basic Operations
uv run craftsman init
uv run craftsman server [--port]
uv run craftsman chat [--resume <id|prefix|title>] [--host] [--port]
uv run craftsman run <prompt> [--host] [--port]

# Run server + chat on localhost
uv run craftsman dev

# Authentication for LLM provider
uv run craftsman auth list
uv run craftsman auth set <provider>
uv run craftsman auth get <provider>
uv run craftsman auth delete [<provider>]

# Server-side User control
uv run craftsman user list
uv run craftsman user register [<username>]
uv run craftsman user delete [<username>]
# Client-side login
uv run craftsman user login [--host] [--port]

# Session management
uv run craftsman sess list [--host] [--port] [--project-id] [--limit]
uv run craftsman sess delete [<id|prefix|title>] [--host] [--port]

# Artifact management
uv run craftsman arti list [--host] [--port]
uv run craftsman arti delete [<id|prefix>] [--host] [--port]

# Server-side generate token
uv run craftsman telegram-token [<username>]
```

## Docs

- [Schema](docs/schema.md)
- [API](docs/api.md)
- [Roadmap](docs/roadmap.md)
