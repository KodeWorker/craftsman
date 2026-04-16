# Agent Tool Calls

## Design Principles

- **Prefer named tools over raw `bash_run`** — named tools (`bash:grep`, `text:read`) have typed schemas the LLM can reason about. Reserve `bash_run` for commands that don't map to a named tool.
- **`bash_run` must use `shlex.split()`** — never pass raw user strings to a shell; always tokenize first to prevent injection (`shlex.split(cmd)` in Python, or equivalent).
- **Every write operation is atomic** — use `.bak` or temp-file + rename patterns; never partial-write a file the agent may read back.
- **Truncate by default, not by exception** — any tool that reads content (files, logs, web pages) should have a `limit` / `max_bytes` parameter and enforce it. The agent requests more if needed.

---

## Meta Tool

Tools that operate on the tool system itself — discovery, schema injection, and composition. The agent never hard-codes a tool name it hasn't confirmed exists.

### Core operations

| Tool | Purpose | Key Parameters |
|------|---------|----------------|
| `tool:list` | Enumerate every registered tool with name and one-line description | `category` (optional filter) |
| `tool:describe` | Return the full JSON schema for a named tool | `name` |
| `tool:find` | Semantic search over tool descriptions; returns the best-matching schema | `intent` |
| `tool:compose` | Declare a pipeline of tool calls as a named macro | `name`, `steps[]` |
| `tool:revoke` | Remove a tool from the active set for this session | `name` |

### Dynamic Tool Registry pattern

When the tool list grows beyond ~20 entries, injecting every schema into every prompt wastes tokens and degrades reasoning. Instead:

1. Store all tool schemas (JSON) in sqlite-vec.
2. Expose only `tool:find(intent)` and `tool:describe(name)` to the agent by default.
3. When the agent calls `tool:find("search log for errors")`, the backend retrieves the `bash:grep` schema and injects it into the **next turn** as a newly available tool.
4. After the session ends, the `librarian` worker evicts schemas that were never called to keep the registry lean.

This keeps the live tool count small and lets the agent self-select at runtime instead of pattern-matching across a wall of schemas.

### Tool composition (`tool:compose`)

Frequently chained sequences can be promoted to a named macro:

```json
{
  "name": "find_recent_errors",
  "steps": [
    { "tool": "bash:grep", "args": { "pattern": "ERROR", "path": "{{log_dir}}", "recursive": true } },
    { "tool": "bash:tail", "args": { "file": "{{result.file}}", "n_lines": 50 } }
  ]
}
```

- `{{result.*}}` binds the output of the previous step.
- The composed macro is registered as a first-class tool and appears in `tool:list` results.
- Macros are session-scoped by default; the `librarian` worker can promote them to the global registry if they prove reusable.

### Safety constraints

- `tool:revoke` is **append-only within a session** — once a tool is revoked, it cannot be re-added without a new session. This prevents an adversarial prompt from revoking `tool:revoke` itself to lock in a dangerous capability set.
- `tool:compose` steps are validated against the registry at declaration time; any unknown tool name causes the macro to be rejected immediately rather than at call time.
- Schema injection from `tool:find` is sandboxed: the injected schema is shown to the agent, but the backend verifies the tool name against the registry before execution.

---

## Bash

### Essential 8 for a sandbox agent

| Tool | Purpose | Key Parameters |
|------|---------|----------------|
| `bash:ls` | Discovery — list directory contents | `path`, `recursive` |
| `bash:cat` | Read file with range control | `file`, `line_start`, `line_end` |
| `bash:grep` | Search logs / code by pattern | `pattern`, `path`, `recursive` |
| `bash:find` | Locate files by name or extension | `name_pattern`, `path` |
| `bash:df` / `bash:du` | Workstation health, disk / VRAM artifacts | `path` |
| `bash:ps` | Check if a process (LLM server, game server) is running | `name_filter` |
| `bash:head` / `bash:tail` | Sample large logs without blowing the context window | `file`, `n_lines` |
| `bash:stat` | Read timestamps and size without reading file content | `file` |

### Meta-tool for scaling (Dynamic Tool Registry)

When the tool list grows, don't dump every schema into every prompt:

1. Store JSON schemas for `bash:grep`, `bash:find`, etc. in sqlite-vec.
2. Expose a single tool `find_shell_utility(intent: str)` to the agent.
3. When the agent says "Find all errors in the log," it calls `find_shell_utility("search log for errors")` — your backend retrieves the `bash:grep` schema and injects it into the next turn.

This keeps the active tool list small and lets the agent self-select the right tool at runtime.

---

## Text

Tools for structured file editing — safer than `bash:cat` + `bash_run` write for code and config files.

1. `text:read` — returns `line_num + content` for every line; line numbers make subsequent `insert`/`replace` calls unambiguous
2. `text:search` — regex or literal search within a file; returns matching line numbers + context
3. `text:replace` — replace a range of lines or a matched pattern; writes atomically via temp-file + rename
4. `text:insert` — insert lines at a specific `line_num`; enabled by `text:read` returning line numbers
5. `text:delete` — delete a line range

**Implementation notes:**
- `text:read` must enforce a `max_lines` limit (e.g., 200); agent requests `line_start`/`line_end` to page through large files
- All write operations (`replace`, `insert`, `delete`) create a `.bak` before writing so the agent can undo
- `text:replace` should take `old_string` + `new_string` rather than raw line numbers when possible — more robust against line-count drift between read and write

---

## Web

### Observer (read-only)

1. `web:search` — returns titles, URLs, and snippets; agent decides which URLs to fetch
2. `web:fetch_url` — fetches a URL and returns **Markdown**, not HTML; strip tags server-side with BeautifulSoup or Readability.js before the agent ever sees the content; enforce `max_chars`

### Actor (browser automation)

3. `browser:navigate` — auto-dismiss GDPR/cookie banners on load so the agent doesn't get stuck before its first click
4. `browser:get_text` — extract visible text from current page
5. ~~`browser:get_html`~~ → prefer `browser:get_accessibility_tree` — structured, token-efficient, handles dynamic content better than raw HTML
6. `browser:click` — always include built-in `wait_for_selector` before the click; never click a selector that may not exist yet
7. `browser:type` — type into a focused element; pair with `browser:click` to focus first
8. `browser:wait` — explicit wait for selector or network idle; use when `wait_for_selector` isn't sufficient
9. `browser:scroll` — scroll to reveal lazy-loaded content
10. `browser:hover` — trigger hover states (tooltips, dropdowns)
11. `browser:select` — set a `<select>` value by label or value string
12. `browser:screenshot` — capture current viewport; useful when text tools fail on canvas/SVG-heavy pages
13. `browser:eval` — run arbitrary JS; last resort — prefer semantic tools above

---

## Memory

1. `memory:store` — write a key-value fact to the session scratchpad; also updates the session knowledge graph
2. `memory:retrieve` — hybrid fetch: relations from the knowledge graph + semantic facts from the vector DB
3. `memory:forget` — explicitly remove a fact; triggers graph edge pruning

### Tiered Memory Mechanism

**Within session:**
- `memory:store` and `memory:forget` write to the scratchpad and maintain a live session knowledge graph
- `memory:retrieve` does a hybrid lookup: relationship traversal (graph) + semantic similarity (vector DB)
- The scratchpad lives in an in-process dict for sub-millisecond access (see [agent-memory.md](./2026-4-16-agent-memory.md))

**Cross-session (offline):**
- A `librarian` worker runs at the end of each session (or nightly)
- Promotes scratchpad facts worth keeping to the Project or Global layer
- Expires stale nodes via TTL; discards the Session layer entirely

---

## Schedule

Two distinct concepts — pick based on trigger type:

**One-shot / delayed execution**

1. `schedule:at(datetime, tool_call)` — run a specific tool call once at a given time
2. `schedule:list` — list pending one-shot jobs
3. `schedule:cancel(job_id)` — cancel a pending job

**Recurring execution**

4. `cron:create(expression, tool_call)` — schedule a recurring tool call (standard cron expression)
5. `cron:list` — list active cron jobs
6. `cron:remove(job_id)` — delete a recurring job

> Use `schedule:at` for "remind me in 2 hours" style tasks. Use `cron:*` for "run the librarian every night at 3 AM" style tasks.

---

## Plan / Task

Tools for structured goal execution. State transitions are enforced at the tool layer — the backend rejects invalid transitions regardless of what the agent reasons. This is a programmatic guardrail, not a prompt instruction.

### State machine

```
pending → in_progress → verifying → done
                                   ↘ failed
```

The `status` column has a `CHECK` constraint; the tool backend additionally validates that the transition is legal before updating the row. An agent cannot call `task:verify` before `task:start`, or `task:done` before `task:verify` — the tool returns an error, not a warning.

### Core operations

| Tool | Purpose | Key Parameters |
|------|---------|----------------|
| `plan:create` | Create a plan with goal + context; agent calls this after research via other tools | `goal`, `context` |
| `plan:done` | Close a completed plan | `plan_id` |
| `task:create` | Add a task to a plan with description + acceptance criteria | `plan_id`, `description`, `criteria` |
| `task:start` | Transition task `pending → in_progress` | `task_id` |
| `task:verify` | Check task output against acceptance criteria; transition `in_progress → verifying` | `task_id`, `output` |
| `task:done` | Transition `verifying → done` | `task_id` |
| `task:fail` | Transition to `failed` with reason | `task_id`, `reason` |
| `task:list` | List tasks for a plan with current status | `plan_id` |

### Design notes

- `plan:create` is called **after** research, not before — the agent uses `web:search`, `bash:grep`, `memory:retrieve` etc. to gather context, then crystallises it into a plan.
- `task:verify` should run acceptance criteria deterministically where possible (e.g. run a test, check a file exists) rather than asking the LLM to self-assess.
- A failed task transitions to `failed` but does not block the plan — the agent can create a replacement task or mark the plan done with caveats.
