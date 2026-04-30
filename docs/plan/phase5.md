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

### Checklist

- [ ] `sessions.py` — accept `tools` list; on tool_call stream events +
      store assistant msg; `POST /tool_result` endpoint
- [ ] `client/chat.py` — client agentic loop
- [ ] `client/telegram.py` — same loop in `_complete`
- [ ] Tool role messages stored in DB
- [ ] `tests/unit/test_sessions_tool_loop.py` — mock provider tool_call
      stream, verify events streamed + assistant msg stored
- [ ] `tests/unit/test_client_tool_loop.py` — mock server responses,
      verify execute + POST tool_result + loop termination

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
at the right time.

### Files

| Path | Change |
|------|--------|
| `src/craftsman/tools/scheduler.py` | `JobDispatcher` with `async run_loop()` |
| `src/craftsman/server.py` | start `JobDispatcher` as FastAPI lifespan task |

### Design notes

- `run_loop` polls every 30 s: `StructureDB.get_due_jobs()` → for each:
  set `running`, parse `tool_call` JSON, `ToolExecutor.execute()`, store
  result, set `done`/`failed`
- Cron jobs: use `croniter` to check expression against `last_run`; same
  execution pattern; update `last_run`
- Server-level `ToolExecutor` (no session context) — memory/plan tools
  operate with `session_id=None`

### Checklist

- [ ] `src/craftsman/tools/scheduler.py` — `JobDispatcher.run_loop()`
- [ ] `server.py` — lifespan startup/shutdown for `JobDispatcher`
- [ ] Cron expression checked via `croniter`
- [ ] `tests/unit/tools/test_scheduler.py` — mock due jobs, verify execute
      called, status updated

### Verify

```bash
uv run pytest tests/unit/tools/test_scheduler.py
# Manual: schedule bash:ls /tmp for 30 s, wait, check DB status=done
```

---

## Dependencies added

| Package | Purpose | Sub-phase |
|---------|---------|-----------|
| `croniter>=2.0` | cron expression validation and scheduling | 5.4, 5.8 |
