# Chromium / Playwright Setup

Browser tools (`browser:*`) require Playwright with a Chromium browser installed.

## Install

```bash
# Install Playwright Python package (included in craftsman dependencies)
uv sync

# Download the Chromium browser binary
uv run playwright install chromium
```

## Enable in config

Edit `craftsman.yaml` (or your local override):

```yaml
tools:
  browser:
    enabled: true    # opt-in
    headless: true   # set false for visual debugging
```

## Verify

```bash
# Run unit tests (mocked — no real browser needed)
uv run pytest tests/unit/tools/test_browser_tools.py

# Integration test
craftsman chat
# → "navigate to example.com and get the page text"
```

## Notes

- `headless: false` opens a visible browser window — useful for debugging
- `browser:screenshot` uploads the PNG via the artifact API and returns an `artifact_id`
- Browser state (cookies, local storage) persists for the lifetime of the chat session
- Set `browser.enabled: false` to disable all browser tools without uninstalling Playwright
