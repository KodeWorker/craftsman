# Phase 6: Web, Browser & Plan Tools

Extend craftsman with read/write web access and a human-gated plan/task
system. Three independent sub-phases; 6.1 and 6.3 can run in parallel.

---

## Architecture

```
craftsman chat / telegram  (client)
  │
  ├── ToolExecutor (existing)
  │    ├── web_tools.py     web:search, web:fetch_url          (6.1)
  │    ├── browser_tools.py browser:navigate, …                (6.2)
  │    └── plan_tools.py    plan:*, task:*                     (6.3)
  │
  └── BrowserManager (new, 6.2)
       └── one Playwright Browser + Page per ToolExecutor
           instance — persistent across tool calls in a session
```

Web and browser tools are **client-side** (run on user's machine).
Plan tools are also client-side — DB writes go through the local SQLite
file shared with the server.

---

## Dependency Chain

```
6.1 (web tools)         6.3 (plan tools)
  └─ 6.2 (browser)
```

6.1 and 6.3 are independent. 6.2 shares the `web:` yaml config section
with 6.1 but has no code dependency on it.

---

## 6.1 — Web Tools (searxng + fetch)

### Files

| Path | Change |
|------|--------|
| `src/craftsman/craftsman.yaml` | add `web:` config section |
| `src/craftsman/tools/web_tools.py` | `web:search`, `web:fetch_url` |
| `src/craftsman/tools/registry.py` | add web tool schemas (category `web`) |
| `docs/setup/searxng.md` | setup guide |

### Config (craftsman.yaml)

```yaml
web:
  searxng_url: "http://localhost:8080"  # required; no default
  search:
    max_results: 10
  fetch:
    max_chars: 8000
```

### Design notes

**`web:search`**
- `GET {searxng_url}/search?q={query}&format=json&categories=general`
- Parse `results[].{title, url, content}` → return up to `max_results`
- If `searxng_url` missing from config → `{"error": "searxng_url not configured in craftsman.yaml"}`
- All errors returned as `{"error": "..."}` — consistent with other tools

**`web:fetch_url`**
- `httpx.get(url)` → `readability-lxml` article extraction → `html2text`
  markdown conversion → truncate to `max_chars` with `[TRUNCATED]` marker
- `lxml` ships pre-built wheels for Linux/macOS/Windows/ARM — no system dep

### Tool schemas

```json
web:search:    { query: str, max_results: int? }
web:fetch_url: { url: str, max_chars: int? }
```

Both audited.

### Checklist

- [ ] `craftsman.yaml` — `web:` section with `searxng_url`, `search.max_results`, `fetch.max_chars`
- [ ] `tools/web_tools.py` — `web_search`, `web_fetch_url`
- [ ] `tools/registry.py` — 2 web schemas, category `web`, both audited
- [ ] `craftsman.yaml` tools section — `web: enabled: true` category switch
- [ ] `docs/setup/searxng.md` — install, configure, point `searxng_url`
- [ ] `tests/unit/tools/test_web_tools.py` — missing config, unreachable host,
      result truncation, html stripping

### Verify

```bash
uv run pytest tests/unit/tools/test_web_tools.py
# Integration: craftsman chat → "search for playwright python"
```

---

## 6.2 — Browser Tools (Playwright)

### Files

| Path | Change |
|------|--------|
| `src/craftsman/craftsman.yaml` | add `web.browser` subsection |
| `src/craftsman/tools/browser_tools.py` | all 11 browser tools |
| `src/craftsman/tools/executor.py` | `BrowserManager` lifecycle; teardown on session end |
| `src/craftsman/tools/registry.py` | add browser tool schemas (category `browser`) |
| `pyproject.toml` | add `playwright>=1.44` |
| `docs/setup/chromium.md` | setup guide |

### Config (craftsman.yaml)

```yaml
web:
  browser:
    enabled: false   # opt-in — heavy dep, requires `playwright install chromium`
    headless: true   # false for visual debugging
```

### Design notes

**BrowserManager**
- Lazy-init: first browser tool call creates the `Browser` and `Page`
- One `Browser` + one `Page` per `ToolExecutor` instance (persistent session)
- `executor.close()` calls `browser_manager.teardown()` — closes browser cleanly
- If `browser.enabled: false` → `{"error": "browser tools disabled — set web.browser.enabled: true"}`

**`browser:navigate`**
- `page.goto(url, wait_until="networkidle")`
- Auto-dismiss cookie/GDPR banners on load via JS inject:
  `page.add_init_script("/* banner dismissal snippet */")`

**`browser:get_accessibility_tree`**
- `page.accessibility.snapshot()` → JSON; preferred over raw HTML
- Token-efficient, handles dynamic content

**`browser:screenshot`**
- `page.screenshot(type="png")` → bytes
- Upload via `POST /artifacts` (existing artifact API) → return `{"artifact_id": ...}`
- Requires client to pass `base_url` and `token` to `BrowserManager`

**`browser:eval`**
- Last resort; schema description notes this explicitly
- Audited

### Tool list

| Tool | Audited |
|------|---------|
| `browser:navigate` | yes |
| `browser:get_text` | no |
| `browser:get_accessibility_tree` | no |
| `browser:click` | yes |
| `browser:type` | yes |
| `browser:wait` | no |
| `browser:scroll` | no |
| `browser:hover` | no |
| `browser:select` | yes |
| `browser:screenshot` | yes |
| `browser:eval` | yes |

### Checklist

- [ ] `pyproject.toml` — `playwright>=1.44`
- [ ] `craftsman.yaml` — `web.browser.enabled`, `web.browser.headless`
- [ ] `tools/browser_tools.py` — all 11 tools; `BrowserManager` class
- [ ] `tools/executor.py` — `BrowserManager` init + teardown; pass `base_url`/`token` for artifact upload
- [ ] `tools/registry.py` — 11 browser schemas, category `browser`
- [ ] `craftsman.yaml` tools section — `browser: enabled: false` category switch
- [ ] `docs/setup/chromium.md` — `pip install playwright`, `playwright install chromium`, config
- [ ] `tests/unit/tools/test_browser_tools.py` — disabled guard, navigate mock,
      screenshot → artifact upload, accessibility tree shape

### Verify

```bash
uv run pytest tests/unit/tools/test_browser_tools.py
# Integration: set browser.enabled: true
# craftsman chat → "navigate to example.com and get the page text"
```

---

## 6.3 — Plan Tools (redesign)

### DB schema changes

**Tasks table** — three changes:

1. Drop `verifying` state; add `cancelled` state
2. Drop `criteria` column (no `task:verify` — criteria have no consumer)
3. Add `depends_on TEXT NOT NULL DEFAULT '[]'` (JSON array of task UUIDs)

```sql
CREATE TABLE tasks (
  id          TEXT PRIMARY KEY,
  plan_id     TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
  description TEXT NOT NULL,
  depends_on  TEXT NOT NULL DEFAULT '[]',  -- JSON array of task UUIDs
  status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'in_progress', 'done', 'failed', 'cancelled')),
  output      TEXT,
  fail_reason TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Drop DB in dev; update DDL only — no ALTER TABLE.

### State machine

```
pending → in_progress → done       (human confirms at task:done)
                       ↘ failed    (LLM calls task:fail)
pending → cancelled                 (human confirms at task:cancel)
```

`task:start` blocked if any `depends_on` task is not `done` — error returned
immediately, no confirm prompt shown.

### Human-gated intercepts

Same pending-confirm pattern as `text:replace` (5.6). Tool returns
`{"status": "pending", "action": "...", ...}` — agentic loop in `chat.py`
and `telegram.py` intercepts before posting tool result.

| Tool | Confirm shows | On reject |
|------|--------------|-----------|
| `task:start` | task description + depends_on status | `{"status": "rejected", "reason": ...}` |
| `task:done` | task description + agent's claimed output | LLM can retry or call `task:fail` |
| `task:cancel` | task description | `{"status": "rejected"}` |
| `task:update` | task description + proposed changes | `{"status": "rejected"}` |

`task:update` only valid on `pending` tasks; updates `description`
and/or `depends_on`.

### `agent:run` mutual exclusion

When `tools.plan.enabled: true`, client auto-revokes `agent:run` at session
start (after `_seed_tools()`). Enforced via `executor._revoked` — same
mechanism as `tool:revoke`. No prompt engineering.

### Files

| Path | Change |
|------|--------|
| `docs/schema.md` | update tasks DDL |
| `src/craftsman/memory/structure.py` | update tasks DDL + methods: `cancel_task`, `update_task`, `get_plan_with_tasks` |
| `src/craftsman/tools/plan_tools.py` | full rewrite — all plan/task handlers |
| `src/craftsman/tools/registry.py` | add plan tool schemas (category `plan`) |
| `src/craftsman/tools/executor.py` | agent:run auto-revoke when plan enabled |
| `src/craftsman/client/chat.py` | pending-confirm intercepts for plan tools |
| `src/craftsman/client/telegram.py` | same |

### Tool schemas

| Tool | Human-gated | Notes |
|------|------------|-------|
| `plan:create` | no | `{goal, context?}` |
| `plan:list` | no | returns all plans: `[{plan_id, goal, status, task_count}]` |
| `plan:get` | no | `{plan_id}` → plan + full task tree with `depends_on` |
| `plan:done` | no | `{plan_id}` |
| `task:create` | no | `{plan_id, description, depends_on?}` |
| `task:start` | yes | `{task_id}` — blocked if deps not done |
| `task:done` | yes | `{task_id, output}` |
| `task:fail` | no | `{task_id, reason}` |
| `task:cancel` | yes | `{task_id}` — only from `pending` |
| `task:update` | yes | `{task_id, description?, depends_on?}` — only `pending` |
| `task:list` | no | `{plan_id}` → flat task list with status |

All write tools audited. Read tools not audited.

### Checklist

- [ ] `docs/schema.md` + `memory/structure.py` — updated tasks DDL; new methods:
      `cancel_task`, `update_task`, `get_plan_with_tasks`
- [ ] `tools/plan_tools.py` — full rewrite; `_TRANSITIONS` updated; pending-confirm
      returns for `task:start`, `task:done`, `task:cancel`, `task:update`
- [ ] `tools/registry.py` — 11 plan schemas, category `plan`
- [ ] `craftsman.yaml` tools section — `plan: enabled: false` (off by default)
- [ ] `tools/executor.py` — agent:run auto-revoke when `tools.plan.enabled: true`
- [ ] `client/chat.py` — `_confirm_plan_action` intercept alongside `_confirm_pending`
- [ ] `client/telegram.py` — same
- [ ] `tests/unit/tools/test_plan_tools.py` — state machine transitions, depends_on
      enforcement, cancel only from pending, update only on pending, pending-confirm
      return shape

### Verify

```bash
uv run pytest tests/unit/tools/test_plan_tools.py
# Integration: enable plan tools, disable agent
# craftsman chat → "create a plan to build a todo app"
# → add tasks → start task1 (confirm) → done task1 (confirm) → start task2
```

---

## Dependencies added

| Package | Purpose | Sub-phase |
|---------|---------|-----------|
| `readability-lxml>=0.9` | article extraction from HTML | 6.1 |
| `html2text>=2024.0` | HTML → Markdown conversion | 6.1 |
| `playwright>=1.44` | browser automation | 6.2 |
