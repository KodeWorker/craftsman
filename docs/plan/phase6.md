# Phase 6: Web & Browser Tools

Extend craftsman with read/write web access. Two sub-phases.

---

## Architecture

```
craftsman chat / telegram  (client)
  │
  ├── ToolExecutor (existing)
  │    ├── web_tools.py     web:search, web:fetch_url          (6.1)
  │    └── browser_tools.py browser:navigate, …                (6.2)
  │
  └── BrowserManager (new, 6.2)
       └── one Playwright Browser + Page per ToolExecutor
           instance — persistent across tool calls in a session
```

Web and browser tools are **client-side** (run on user's machine).

---

## Dependency Chain

```
6.1 (web tools)
  └─ 6.2 (browser)
```

6.2 shares the `web:` yaml config section with 6.1 but has no code
dependency on it.

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

## Dependencies added

| Package | Purpose | Sub-phase |
|---------|---------|-----------|
| `readability-lxml>=0.9` | article extraction from HTML | 6.1 |
| `html2text>=2024.0` | HTML → Markdown conversion | 6.1 |
| `playwright>=1.44` | browser automation | 6.2 |
