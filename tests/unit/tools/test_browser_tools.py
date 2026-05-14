from unittest.mock import MagicMock, patch

from craftsman.tools.browser_tools import BrowserManager, make_browser_dispatch

_DISABLED_CFG = {"enabled": False, "headless": True}
_ENABLED_CFG = {"enabled": True, "headless": True}


def _manager(cfg=None, base_url="http://localhost:8000", token="tok"):
    mgr = BrowserManager(base_url=base_url, token=token)
    if cfg is not None:
        mgr._cfg = lambda: cfg
    return mgr


def _mock_page(url="https://example.com", title="Example"):
    page = MagicMock()
    page.url = url
    page.title.return_value = title
    return page


def _attach_page(mgr, page):
    """Inject a mock page so _ensure_page() returns it without launching."""
    browser = MagicMock()
    browser.is_connected.return_value = True
    mgr._browser = browser
    mgr._page = page


# ── disabled guard ───────────────────────────────────────────────────────────


def test_navigate_disabled_returns_error():
    mgr = _manager(_DISABLED_CFG)
    result = mgr.navigate({"url": "https://example.com"})
    assert "error" in result
    assert "disabled" in result["error"]


def test_get_text_disabled_returns_error():
    mgr = _manager(_DISABLED_CFG)
    result = mgr.get_text({})
    assert "error" in result
    assert "disabled" in result["error"]


def test_click_disabled_returns_error():
    mgr = _manager(_DISABLED_CFG)
    result = mgr.click({"selector": "button"})
    assert "error" in result
    assert "disabled" in result["error"]


def test_screenshot_disabled_returns_error():
    mgr = _manager(_DISABLED_CFG)
    result = mgr.screenshot({})
    assert "error" in result
    assert "disabled" in result["error"]


# ── navigate ─────────────────────────────────────────────────────────────────


def test_navigate_success():
    page = _mock_page()
    mgr = _manager(_ENABLED_CFG)
    _attach_page(mgr, page)

    result = mgr.navigate({"url": "https://example.com"})

    page.goto.assert_called_once_with(
        "https://example.com", wait_until="networkidle"
    )
    assert result["status"] == "ok"
    assert result["url"] == "https://example.com"
    assert result["title"] == "Example"


def test_navigate_error_returned_as_dict():
    page = _mock_page()
    page.goto.side_effect = Exception("net::ERR_NAME_NOT_RESOLVED")
    mgr = _manager(_ENABLED_CFG)
    _attach_page(mgr, page)

    result = mgr.navigate({"url": "https://nonexistent.invalid"})

    assert "error" in result
    assert "ERR_NAME_NOT_RESOLVED" in result["error"]


# ── get_text ─────────────────────────────────────────────────────────────────


def test_get_text_returns_body_text():
    page = _mock_page()
    page.inner_text.return_value = "Hello world"
    mgr = _manager(_ENABLED_CFG)
    _attach_page(mgr, page)

    result = mgr.get_text({})

    page.inner_text.assert_called_once_with("body")
    assert result["text"] == "Hello world"
    assert result["url"] == "https://example.com"


def test_get_text_uses_same_page_as_navigate():
    """Both tools must share the same page object (same browser session)."""
    page = _mock_page(url="https://example.com")
    page.inner_text.return_value = "Example Domain"
    mgr = _manager(_ENABLED_CFG)
    _attach_page(mgr, page)

    mgr.navigate({"url": "https://example.com"})
    result = mgr.get_text({})

    assert result["url"] == "https://example.com"
    assert result["text"] == "Example Domain"


# ── accessibility tree ───────────────────────────────────────────────────────


def test_aria_snapshot_shape():
    snapshot = '- document\n  - heading "Example Domain" [level=1]'
    page = _mock_page()
    page.aria_snapshot.return_value = snapshot
    mgr = _manager(_ENABLED_CFG)
    _attach_page(mgr, page)

    result = mgr.aria_snapshot({})

    assert result["tree"] == snapshot
    assert "url" in result


# ── screenshot → artifact upload ─────────────────────────────────────────────


def test_screenshot_uploads_and_returns_artifact():
    page = _mock_page()
    page.screenshot.return_value = b"\x89PNG\r\n"
    mgr = _manager(_ENABLED_CFG)
    _attach_page(mgr, page)

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"artifact_id": "abc-123"}

    with patch(
        "craftsman.tools.browser_tools.httpx.post", return_value=mock_resp
    ):
        result = mgr.screenshot({})

    assert result["artifact_id"] == "abc-123"


def test_screenshot_upload_failure_returns_error():
    page = _mock_page()
    page.screenshot.return_value = b"\x89PNG\r\n"
    mgr = _manager(_ENABLED_CFG)
    _attach_page(mgr, page)

    with patch(
        "craftsman.tools.browser_tools.httpx.post",
        side_effect=Exception("connection refused"),
    ):
        result = mgr.screenshot({})

    assert "error" in result
    assert "upload failed" in result["error"]


# ── dead-browser recovery ────────────────────────────────────────────────────


def test_navigate_recovers_after_external_close():
    """'target closed' error triggers reset and successful retry."""
    dead_page = MagicMock()
    dead_page.goto.side_effect = Exception("target closed")

    fresh_page = _mock_page()
    fresh_browser = MagicMock()
    fresh_browser.new_page.return_value = fresh_page

    fresh_pw = MagicMock()
    fresh_pw.chromium.launch.return_value = fresh_browser

    mgr = _manager(_ENABLED_CFG)
    mgr._browser = MagicMock()
    mgr._browser.is_connected.return_value = True
    mgr._page = dead_page
    mgr._pw = MagicMock()

    with patch("playwright.sync_api.sync_playwright") as mock_sp:
        mock_sp.return_value.start.return_value = fresh_pw
        result = mgr.navigate({"url": "https://example.com"})

    assert result["status"] == "ok"
    assert fresh_page.goto.called


def test_navigate_non_browser_error_not_retried():
    """Non-dead-browser errors are not retried."""
    page = _mock_page()
    page.goto.side_effect = Exception("net::ERR_NAME_NOT_RESOLVED")
    mgr = _manager(_ENABLED_CFG)
    _attach_page(mgr, page)

    result = mgr.navigate({"url": "https://nonexistent.invalid"})

    assert "error" in result
    assert page.goto.call_count == 1


# ── make_browser_dispatch ────────────────────────────────────────────────────


async def test_dispatch_keys_cover_all_tools():
    mgr = _manager(_DISABLED_CFG)
    dispatch = make_browser_dispatch(mgr)
    expected = {
        "browser:navigate",
        "browser:get_text",
        "browser:aria_snapshot",
        "browser:click",
        "browser:type",
        "browser:wait",
        "browser:scroll",
        "browser:hover",
        "browser:select",
        "browser:screenshot",
        "browser:eval",
    }
    assert set(dispatch.keys()) == expected


async def test_dispatch_calls_are_awaitable():
    page = _mock_page()
    page.inner_text.return_value = "hello"
    mgr = _manager(_ENABLED_CFG)
    _attach_page(mgr, page)
    dispatch = make_browser_dispatch(mgr)

    result = await dispatch["browser:get_text"]({})
    assert "text" in result or "error" in result
