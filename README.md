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
uv run craftsman auth clear [<provider>]

uv run craftsman sess list
uv run craftsman sess delete
```

## Docs

- [Schema](docs/schema.md)
- [API](docs/api.md)
- [Roadmap](docs/roadmap.md)
