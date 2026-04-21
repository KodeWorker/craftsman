# craftsman

Self-hosted autonomous agent framework. Zero daemons.

## Setup

1. [docs/setup/llama.cpp.md](docs/setup/llama.cpp.md)
2. [docs/configuration.md](docs/configuration.md)

## Usage

```shell
uv run craftsman init
uv run craftsman server [--port]
uv run craftsman chat [--resume <id|prefix|title>] [--host] [--port]
uv run craftsman run <prompt> [--host] [--port]
uv run craftsman dev

uv run craftsman auth list
uv run craftsman auth set <provider>
uv run craftsman auth get <provider>
uv run craftsman auth delete [<provider>]

uv run craftsman user list
uv run craftsman user register
uv run craftsman user delete <usernam>
uv run craftsman user login

uv run craftsman sess list [--host] [--port] [--project-id] [--limit]
uv run craftsman sess delete <id|prefix|title> [--host] [--port]

# TODO:
uv run craftsman artifacts list [--host] [--port]
uv run craftsman artifacts delete <id|prefix> [--host] [--port]
```

## Docs

- [Schema](docs/schema.md)
- [API](docs/api.md)
- [Roadmap](docs/roadmap.md)
