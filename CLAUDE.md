# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run CLI
uv run craftsman <command>

# Lint / format (via pre-commit)
uv run pre-commit run --all-files

# Format only
uv run black --line-length=79 src/
uv run isort src/
```

Run tests: `uv run pytest tests/unit/`

## Architecture

Early-stage autonomous agent framework. CLI + server functional; client/vector/graph are stubs.

### Entry point

`src/craftsman/cli.py` — Click CLI with three command groups:
- Top-level: `init`, `server`, `chat`, `run`, `dev`
- `auth` subgroup: `list`, `set`, `get`, `delete`
- `sess` subgroup: `list`, `delete`
- `user` subgroup: `list`, `register`, `delete`, `login` (API only; no CLI yet)

### Modules

| Module | Status | Purpose |
|--------|--------|---------|
| `cli.py` | Done | Click entrypoint, wires all commands |
| `auth.py` | Done | Keyring wrapper; credentials: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_SSL_CRT` |
| `server.py` | Done | FastAPI server; streaming completion, session management |
| `provider.py` | Done | LiteLLM wrapper; streams `(kind, text)` tuples |
| `memory/structure.py` | Done | SQLite layer; all tables per `docs/schema.md` |
| `memory/librarian.py` | Done | Unified memory interface; in-process cache + SQLite |
| `memory/vector.py` | Stub | sqlite-vec embeddings via LightRAG |
| `memory/graph.py` | Stub | Kuzu knowledge graph via LightRAG |
| `client.py` | Done | Terminal chat client; streaming display, session resume, slash commands |
| `crypto.py` | Done | JWT token creation/verification; bcrypt password hashing; secret key management |
| `router/deps.py` | Done | FastAPI dependencies; `get_current_user` JWT guard; `_crypto` singleton |

### Infrastructure

All embedded — zero daemons required. See `docs/schema.md`.

- **In-process dict** — session scratchpad, agent state, context window (lives in server process)
- **SQLite** (`~/.craftsman/database/craftsman.db`) — projects, sessions, messages, global_facts, artifacts, plans, tasks, tools, scheduled/cron jobs
- **sqlite-vec** — vector embeddings managed by LightRAG; SQLite extension, same DB file
- **Kuzu** (embedded graph DB) — knowledge graph, managed by LightRAG, no daemon
- **LightRAG** — KG orchestration: entity extraction + graph+vector hybrid retrieval
- **Local filesystem** (`~/.craftsman/workspace/`) — artifact storage

### Memory hierarchy

Three layers, promoted upward over time:

1. **Session** (in-process dict) — scratchpad, discarded at end; promotes to Project
2. **Project** (SQLite) — retained for continuation/resume
3. **Global** (SQLite) — nightly-distilled keynotes from Project layer

LightRAG/Kuzu knowledge graph spans all layers; nightly batch promotes/prunes nodes.

## Code style

- Line length: 79 (Black)
- Imports sorted via isort
- Pre-commit enforces trailing whitespace, EOF newline, YAML validity, Black, isort, flake8
