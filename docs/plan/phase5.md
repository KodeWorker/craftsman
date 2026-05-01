# Phase 5: Tool Use

Turn craftsman from a chat proxy into an agent that can act on the world:
run shell commands, edit files, manage plans, schedule work, and discover
new capabilities at runtime.

**Web/browser tools are out of scope** — deferred to Phase 6.

---

## Architecture

Tool execution is **client-side**. The server handles LLM calls and context
storage; the client drives the agentic loop.

```
craftsman chat / telegram  (client)
  │  1. POST /sessions/{id}/completion  {message, tools:[names]}
  │  4. POST /sessions/{id}/tool_result {tool_results:[...]}
  │  (repeat 1/4 until content)
  ▼
sessions.py  (server)
  │  2. calls LLM with tool schemas from DB
  │  3. on tool_call: streams tool_call events, stores assistant msg, ends stream
  │     on content: streams content as usual
  ▼
provider.py  ─── yields ("tool_call", {...}) chunks (5.2)

ToolExecutor  (client-side, 5.3 / 5.4 / 5.5)
  ├── bash_tools.py    bash:ls, bash:grep, ...
  ├── text_tools.py    text:read, text:replace, ...
  ├── memory_tools.py  memory:store, memory:retrieve, ...
  ├── plan_tools.py    plan:create, task:start, ...
  ├── schedule_tools.py schedule:at, cron:create, ...
  └── meta_tools.py    tool:list, tool:find, tool:revoke, ...
```

Registry seeded via `POST /tools/seed` called by the client on startup.
DB schema for `tools`, `tool_invocations`, `tool_macros`, `plans`, `tasks`,
`scheduled_jobs`, and `cron_jobs` is **already in place** in
`memory/structure.py`.

---

## Dependency Chain

```
5.1 (registry seed)
  └─ 5.2 (provider tool_call plumbing)
       └─ 5.3 (bash + text executor)
            └─ 5.4 (memory + plan + schedule executor)
                 └─ 5.5 (meta tools + dynamic registry)
                      └─ 5.6 (session agentic loop)
                           ├─ 5.7 (TUI display)       [leaf]
                           └─ 5.8 (job dispatcher)    [leaf]
```

5.1–5.6 are strictly sequential. 5.7 and 5.8 are independent leaves.

---

## 5.1 — Tool Registry Seed

Populate the `tools` table at server boot so all subsequent phases have a
concrete registry to query against.

### Files

| Path | Change |
|------|--------|
| `src/craftsman/tools/registry.py` | `_TOOLS` list + `seed_registry(db)` |
| `src/craftsman/server.py` | `POST /tools/seed` endpoint → calls `seed_registry` |
| `src/craftsman/client/base.py` | `_seed_tools()` helper → `POST /tools/seed` |
| `src/craftsman/client/chat.py` | call `_seed_tools()` after JWT setup in `chat()` and `run()` |
| `src/craftsman/client/telegram.py` | `_seed_tools()` called after `_reset_provider()` |

### Design notes

- One JSON schema dict per tool in OpenAI function-calling format:
  `{name, description, category, audited, parameters: {type, properties, required}}`
- `seed_registry` uses `StructureDB.register_tool` (INSERT OR REPLACE —
  safe to call on every boot)
- Each entry carries an `audited: bool` flag — the executor checks this to
  decide whether to write an invocation record (see 5.3)
- Categories and tools to register:
  - `meta`: `tool:list`, `tool:describe`, `tool:find`, `tool:compose`✓, `tool:revoke`✓
  - `bash`: `bash:ls`✓, `bash:cat`✓, `bash:grep`✓, `bash:find`✓, `bash:head`✓,
    `bash:tail`✓, `bash:stat`✓, `bash:ps`✓, `bash:df`✓, `bash:du`✓
  - `text`: `text:read`, `text:search`, `text:replace`✓, `text:insert`✓, `text:delete`✓
  - `memory`: `memory:store`✓, `memory:retrieve`, `memory:forget`✓
  - `schedule`: `schedule:at`✓, `schedule:list`, `schedule:cancel`✓,
    `cron:create`✓, `cron:list`, `cron:remove`✓
  - `plan`: `plan:create`✓, `plan:done`✓, `task:create`✓, `task:start`✓,
    `task:verify`✓, `task:done`✓, `task:fail`✓, `task:list`

  ✓ = audited

- Add `tool_invocations` table to `docs/schema.md` and `StructureDB`:

  ```sql
  CREATE TABLE tool_invocations (
    id          TEXT PRIMARY KEY,
    session_id  TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    tool_name   TEXT NOT NULL,
    args        TEXT NOT NULL,   -- JSON
    result      TEXT NOT NULL,   -- JSON
    duration_ms INTEGER NOT NULL,
    is_error    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
  );
  ```

### Checklist

- [x] `src/craftsman/tools/registry.py` — 37 schemas with `audited` flag
- [x] `docs/schema.md` + `memory/structure.py` — `tool_invocations` table +
      `audited` column on `tools` + `log_tool_invocation` method
- [x] `server.py` — `POST /tools/seed` endpoint
- [x] `client/base.py` — `_seed_tools()` helper
- [x] `client/chat.py` — `_seed_tools()` called in `chat()` and `run()`
- [x] `client/telegram.py` — `_seed_tools()` called in `run()`
- [x] `tests/unit/tools/test_registry.py` — 8 tests passing

### Verify

```bash
uv run python -c "
from craftsman.memory.structure import StructureDB
from craftsman.tools.registry import seed_registry
db = StructureDB(); seed_registry(db)
print(len(db.list_tools()), 'tools')
"
uv run pytest tests/unit/tools/test_registry.py
```

---

## 5.2 — LiteLLM Tool-Call Plumbing

Extend `provider.py` to accept tool schemas, detect streaming `tool_calls`
deltas, accumulate them across chunks, and yield `("tool_call", {...})` tuples.

### Files

| Path | Change |
|------|--------|
| `src/craftsman/provider.py` | `tools=` param, delta accumulation, new yield type |
| `tests/unit/conftest.py` | extend `make_chunk` with tool_call delta fields |

### Design notes

- Add `tools: list[dict] | None = None` and `tool_choice: str = "auto"` to
  `completion()`; pass through to `litellm.acompletion`
- In `model_response_parser()`: accumulate `delta.tool_calls` fragments by
  `index` across chunks (id, name, arguments each arrive in pieces)
- After stream ends (or on `finish_reason == "tool_calls"`), yield one
  `("tool_call", {"id": ..., "name": ..., "arguments_raw": ...})` per call

### Checklist

- [x] `completion()` accepts `tools` and `tool_choice` params
- [x] `model_response_parser()` accumulates tool_call deltas by index
- [x] Yields `("tool_call", {...})` after full accumulation
- [x] `finish_reason == "tool_calls"` handled
- [x] `tests/unit/test_provider.py` — delta accumulation across chunks,
      mixed content+tool_call stream, missing fields don't crash

### Verify

```bash
uv run pytest tests/unit/test_provider.py
```

---

## 5.3 — Executor: Bash and Text Tools

Implement concrete execution for `bash:*` and `text:*` tools in
`ToolExecutor`.

### Files

| Path | Change |
|------|--------|
| `src/craftsman/tools/executor.py` | `ToolExecutor` with `async execute(name, args) -> dict` |
| `src/craftsman/tools/bash_tools.py` | `bash:ls/cat/grep/find/head/tail/stat/ps/df/du` |
| `src/craftsman/tools/text_tools.py` | `text:read/search/replace/insert/delete` |

### Design notes

- All bash tools: `asyncio.create_subprocess_exec(*shlex.split(cmd))` —
  never `shell=True`; validate args against schema before building the command
- Enforce `max_lines`/`max_bytes` with truncation markers
  (`[TRUNCATED after N lines]`)
- `text:read` returns `{"lines": [{"n": 1, "text": "..."}], ...}` so line
  numbers are unambiguous for follow-up edits
- `text:replace/insert/delete`: write to `<path>.craftsman.tmp` then
  `os.replace()`; create `<path>.bak` before any modification (atomic + undo)
- `executor.execute()` catches all exceptions → `{"error": str(e)}`; always
  calls `StructureDB.increment_tool_call_count`; if the tool's `audited` flag
  is set, also calls `StructureDB.log_tool_invocation` with args, result,
  elapsed `duration_ms`, and `is_error` — regardless of success or failure

### Checklist

- [x] `src/craftsman/tools/executor.py` — dispatch table, error wrapping,
      call count increment, conditional audit log
- [x] `src/craftsman/tools/bash_tools.py` — all 10 bash tools
- [x] `src/craftsman/tools/text_tools.py` — all 5 text tools
- [x] `tests/unit/tools/test_bash_tools.py` — truncation, shlex, bad path
- [x] `tests/unit/tools/test_text_tools.py` — atomic write, .bak, line numbers
- [x] `tests/unit/tools/test_executor.py` — audited tool writes invocation
      record; non-audited tool does not; error path also writes record with
      `is_error=1`

### Verify

```bash
uv run pytest tests/unit/tools/test_bash_tools.py tests/unit/tools/test_text_tools.py
```

---

## 5.4 — Executor: Memory, Plan/Task, Schedule Tools

Implement concrete execution for `memory:*`, `plan:*`, `task:*`,
`schedule:*`, and `cron:*` tools.

### Files

| Path | Change |
|------|--------|
| `src/craftsman/tools/memory_tools.py` | `memory:store/retrieve/forget` |
| `src/craftsman/tools/plan_tools.py` | `plan:create/done`, `task:create/start/verify/done/fail/list` |
| `src/craftsman/tools/schedule_tools.py` | `schedule:at/list/cancel`, `cron:create/list/remove` |
| `src/craftsman/tools/executor.py` | accept `librarian: Librarian` and `session_id: str` |
| `pyproject.toml` | add `croniter>=2.0` |

### Design notes

- `memory:store/retrieve/forget` — `librarian.set_scratchpad /
  get_scratchpad` only; no vector DB yet (Phase 6)
- Task state machine enforced in code — invalid transitions return
  `{"error": "Invalid transition: X -> Y"}`, never silently succeed
- `schedule:at` validates ISO 8601 datetime, then normalizes to UTC before
  storing: naive datetimes are treated as machine-local time and converted
  via `datetime.astimezone(timezone.utc)`. Agents reason in local time;
  SQLite `datetime('now')` compares in UTC — normalization bridges the gap.
- `cron:create` validates cron expression via `croniter`
- `plan:create` always attaches `session_id`

### Task state machine

```
pending → in_progress → verifying → done
                                   ↘ failed
```

### Checklist

- [x] `src/craftsman/tools/memory_tools.py`
- [x] `src/craftsman/tools/plan_tools.py` — state machine validation
- [x] `src/craftsman/tools/schedule_tools.py` — datetime + cron validation
- [x] `executor.py` extended with `librarian` + `session_id`
- [x] `pyproject.toml` — `croniter>=2.0`
- [x] `tests/unit/tools/test_memory_tools.py`
- [x] `tests/unit/tools/test_plan_tools.py` — every valid and invalid transition
- [x] `tests/unit/tools/test_schedule_tools.py` — bad datetime/cron rejected

### Verify

```bash
uv run pytest tests/unit/tools/test_memory_tools.py \
              tests/unit/tools/test_plan_tools.py \
              tests/unit/tools/test_schedule_tools.py
```

---

## 5.5 — Meta Tools and Dynamic Registry

Implement `tool:list/describe/find/compose/revoke` with per-session
revocation and the `tool:find` schema-injection pattern.

### Files

| Path | Change |
|------|--------|
| `src/craftsman/tools/meta_tools.py` | all five meta tools |
| `src/craftsman/tools/executor.py` | `self._revoked: set[str]`; check at dispatch |
| `src/craftsman/memory/librarian.py` | `revoke_tool(session_id, name)` and `get_revoked_tools(session_id)` |

### Design notes

- `tool:list` — `StructureDB.list_tools(category=...)` minus revoked;
  returns `[{name, description, category}]`
- `tool:describe` — full schema JSON, filtered for revocation
- `tool:find` — keyword substring match on `name + description` via SQLite
  `LIKE`; sufficient for a ~30-tool registry. sqlite-vec embedding upgrade
  deferred to Phase 7 (see note there); returns `{"injected_tool": schema}`
  — session router adds it to `tools=` next turn
- `tool:compose` — validates each step name against registry (including
  revoke check); calls `StructureDB.create_macro`
- `tool:revoke` — appends to in-process revoke set; guard: `tool:revoke`
  itself cannot be revoked; revocations are append-only within a session

### Checklist

- [x] `src/craftsman/tools/meta_tools.py`
- [x] `constants.py` — `META_DISPATCH`; `router/tools.py` — meta dispatch branch
- [x] `librarian.py` — `revoke_tool` / `get_revoked_tools` cache slots
- [x] `memory/structure.py` — `search_tools(keyword)` for `tool:find`
- [x] `tests/unit/tools/test_meta_tools.py` — 21 tests: revoke idempotency,
      self-revoke guard, compose unknown/revoked step rejected, tool:find schema injection

### Verify

```bash
uv run pytest tests/unit/tools/test_meta_tools.py
```

---

## 5.6 — Agentic Loop (client-driven)

Client drives the tool loop. Server detects tool_calls, streams them to the
client, and stores the assistant message. Client executes tools locally and
sends results back. Loop repeats until the LLM returns content.

### Files

| Path | Change |
|------|--------|
| `src/craftsman/router/sessions.py` | (1) accept `tools` list in completion request body; (2) on tool_call: stream events + store assistant msg + end stream; (3) new `POST /{session_id}/tool_result` endpoint |
| `src/craftsman/client/chat.py` | client-side agentic loop: execute tools, POST results, re-run completion |
| `src/craftsman/client/telegram.py` | same loop in `_complete` |

### Completion request body (updated)

```json
{
  "message": {"role": "user", "content": "..."},
  "tools": ["bash:grep", "bash:ls"]
}
```

Server looks up schemas for the listed tool names from the DB and passes
them to `litellm.acompletion` as `tools=`.

### Active tool list logic (client-side, per request)

```
if meta category enabled:
    send only meta tools  → LLM discovers everything else via tool:find
                            tool:find injects the requested schema for next turn
else:
    send all enabled tools → LLM sees full list upfront (no discovery)
```

This keeps the active tool count small when meta is on, and falls back to
the full list when it's off.

### Tool result endpoint

`POST /sessions/{id}/tool_result`
```json
{
  "tool_results": [
    {"tool_call_id": "call_abc", "tool_name": "bash:ls", "result": {...}}
  ]
}
```
Server stores each as `role="tool"` message, calls LLM again, streams
response. The client loop repeats until a content response arrives.

### Design notes

- Client sends `tools: [names]` with each completion; server builds
  OpenAI-format schemas from DB + injected tools from session state
- Server streams `{"kind": "tool_call", "id": ..., "name": ..., "args": {...}}`
  then ends stream (no content in the same response)
- Client collects all tool_call events, executes via `ToolExecutor`, then
  `POST /sessions/{id}/tool_result`
- Client loop guard: max 10 iterations (configurable in client config)
- Store tool-call messages with `role = "tool"` in `messages` table

### Pending tool confirmation (human-in-the-loop)

Text write tools (`text:replace`, `text:insert`, `text:delete`) return
`{"status": "pending", "tmp": ..., "file": ...}` instead of executing
immediately. The loop must intercept this before posting the tool result:

```
result["status"] == "pending"
  → display the pending change to user (diff or summary)
  → prompt: "[y] approve / [n] reject (enter reason): "
  → "y"         → executor.commit_pending(file, tmp)
                  → tool result: {"status": "committed", "file": ...}
  → "n <reason>" → executor.discard_pending(tmp)
                  → tool result: {"status": "rejected", "reason": "<user input>"}
```

The rejection reason is sent back to the LLM as part of the tool result
so it can understand why and adjust its approach rather than retrying blindly.

### Checklist

- [x] `sessions.py` — accept `tools` list; `_build_tool_schemas`; `_stream_completion`
      handles tool_call and content paths; `POST /tool_result` endpoint
- [x] `client/chat.py` — `_agentic_loop`, `_do_stream`, `_call_tool`,
      `_confirm_pending`, `_start_spinner`; chat loop replaced with `_agentic_loop`
- [ ] `client/telegram.py` — same loop in `_complete` (deferred to 5.7)
- [x] Tool role messages stored in DB
- [x] `tests/unit/test_sessions_tool_loop.py` — 10 tests: tool_call stream,
      assistant ctx msg, user msg stored, tool_result endpoint, schema builder
- [ ] `tests/unit/test_client_tool_loop.py` — deferred (sync client hard to unit-test)

### Verify

```bash
uv run pytest tests/unit/test_sessions_tool_loop.py tests/unit/test_client_tool_loop.py
# Integration:
uv run craftsman dev   # chat: "list files in /tmp"
```

---

## 5.7 — Client Tool-Call Display

Render `tool_call` and `tool_result` NDJSON events in both clients so the
user can see the agent acting.

### Files

| Path | Change |
|------|--------|
| `src/craftsman/client/chat.py` | handle `kind == "tool_call"` and `kind == "tool_result"` |
| `src/craftsman/client/telegram.py` | handle same kinds in `_drain`; send as Telegram messages |

### Design notes

**TUI (`chat.py`)**
- `tool_call`: print dimmed `[tool: bash:grep {"pattern": "error"}]`
- `tool_result`: print dimmed yellow for result, red for error
- Do not accumulate as assistant content — side-channel display only
- Spinner stays active across tool iterations; stop only on first content
  or meta chunk

**Telegram (`telegram.py`)**
- `_drain` currently silently drops unknown kinds — extend it to collect
  `tool_call` and `tool_result` events into a side list
- After the full response is assembled, prepend a summary block before the
  answer, e.g.:
  ```
  [tool: bash:ls /tmp]
  → {"files": ["a", "b"]}
  ```
- Keep it concise — truncate result previews to ~200 chars to stay within
  the 4096-char Telegram message limit
- Errors shown as `→ error: <message>`

### Checklist

- [ ] `chat.py` — `tool_call` event handler
- [ ] `chat.py` — `tool_result` event handler (yellow / red)
- [ ] Spinner behaviour unchanged across tool iterations
- [ ] `telegram.py` — `_drain` collects `tool_call` / `tool_result` events
- [ ] `telegram.py` — tool summary prepended to reply, truncated to 200 chars
- [ ] `tests/unit/test_client_display.py` — interleaved NDJSON stream verify

### Verify

```bash
uv run pytest tests/unit/test_client_display.py
# Manual TUI: craftsman chat → "list files in /tmp"
# Manual Telegram: send "list files in /tmp" → verify tool block appears above answer
```

---

## 5.8 — Scheduled Job Dispatcher

Background task that fires pending `scheduled_jobs` and due `cron_jobs`
when the client is running.  The dispatcher lives **client-side** — tools
execute on the user's own machine, never on the server.

### Architecture

```
craftsman chat / telegram / daemon  (client process)
  │
  ├── agentic loop          (existing)
  │
  └── JobDispatcher         (background asyncio task, new)
       │  polls DB every 30 s via direct StructureDB access
       │  (client and server share the same local SQLite file)
       │
       ├── scheduled_job / cron_job with a single tool call
       │    └── ToolExecutor.execute(name, args, session_id)
       │         ├── local tools  → run on client machine (bash, text, …)
       │         └── server tools → POST /tools/invoke   (memory, plan, …)
       │
       └── agent:run — multi-tool prompt-driven task
            └── drives HTTP agentic loop against server
                 POST /sessions/{id}/completion  (LLM call, server-side)
                 ← tool_call events
                 → ToolExecutor.execute per tool call   (client-side)
                 → POST /sessions/{id}/tool_result
                 repeat until content-only response
```

**Why client-side?**
Running bash/text tools on the server would allow any authenticated user
to execute arbitrary commands on the server filesystem.  The client is the
user's own machine — the same security context as an interactive session.

### Files

| Path | Change |
|------|--------|
| `src/craftsman/tools/scheduler.py` | rewrite: `JobDispatcher(executor, db)` polls DB, dispatches via `ToolExecutor`; `_run_agent` drives HTTP loop |
| `src/craftsman/server.py` | remove `JobDispatcher` from lifespan (server is queue only) |
| `src/craftsman/client/chat.py` | spawn `JobDispatcher` background task on startup |
| `src/craftsman/client/telegram.py` | same |
| `src/craftsman/cli.py` | add `craftsman daemon` command — headless dispatcher without interactive chat |
| `src/craftsman/tools/registry.py` | `agent:run` entry (`category: "agent"`, `audited: True`) |
| `src/craftsman/memory/structure.py` | `user_id` on `scheduled_jobs` + `cron_jobs`; `last_result` on `cron_jobs` |
| `src/craftsman/tools/schedule_tools.py` | resolve + pass `user_id` in `schedule_at` / `cron_create` |

### Design notes

- `JobDispatcher.__init__(executor: ToolExecutor, db: StructureDB)` — no
  `Provider` or `Librarian`; LLM calls go through the server API
- `run_loop` polls every 30 s; `get_due_jobs()` + `list_cron_jobs(active_only=True)`
- Per job: create session on server (`POST /sessions`), execute, store
  result, delete session
- `_run_agent`: same HTTP streaming loop as `chat.py._agentic_loop`; reuse
  or extract shared helper
- `cron_jobs.last_result TEXT` — dispatcher writes JSON result after each
  run; `cron:list` exposes it; user checks via CLI or API (no tool needed)

#### User ownership

`scheduled_jobs.user_id` and `cron_jobs.user_id` track who owns the job.
Dispatcher creates a fresh session per job (`POST /sessions`), passes the
session JWT for auth on tool calls, discards session after.

#### `agent:run` tool

```json
{
  "name": "agent:run",
  "args": { "prompt": "Write a joke and append it to ~/jokes.txt" }
}
```

The LLM drives the full tool loop.  Since the dispatcher uses
`ToolExecutor`, the `text:insert` call above writes to `~/jokes.txt` on
the **client machine**, exactly as if the user had typed it interactively.

### Checklist

- [x] `memory/structure.py` — `user_id` on both job tables; `schedule_job`
      and `create_cron_job` updated
- [x] `tools/schedule_tools.py` — `user_id` resolved from session
- [x] `tools/registry.py` — `agent:run` entry added
- [ ] `server.py` — remove `JobDispatcher` from lifespan
- [ ] `tools/scheduler.py` — rewrite: `JobDispatcher(executor, db)`;
      `_run_scheduled`, `_run_cron`, `_run_agent` via HTTP loop
- [ ] `client/chat.py` — spawn dispatcher background task
- [ ] `client/telegram.py` — same
- [ ] `cli.py` — `craftsman daemon` command
- [ ] `tests/unit/tools/test_scheduler.py` — update mocks to use
      `ToolExecutor` instead of dispatch tables

### Verify

```bash
uv run pytest tests/unit/tools/test_scheduler.py
# Manual: craftsman daemon &
# schedule bash:ls /tmp for 30 s, wait, check DB status=done, result populated
# schedule agent:run {"prompt": "append date to /tmp/log.txt"} for 30 s
```

---

## Dependencies added

| Package | Purpose | Sub-phase |
|---------|---------|-----------|
| `croniter>=2.0` | cron expression validation and scheduling | 5.4, 5.8 |
