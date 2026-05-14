import asyncio
import concurrent.futures
import io
import queue
import threading
from datetime import datetime

import httpx

from craftsman.configure import get_config

_BANNER_SCRIPT = """
(() => {
    const dismiss = () => {
        const patterns = [
            'button[id*="accept"]', 'button[class*="accept"]',
            '[id*="cookie"] button', '[class*="cookie"] button',
            '[id*="consent"] button', '[class*="gdpr"] button',
        ];
        for (const sel of patterns) {
            const btn = document.querySelector(sel);
            if (btn) { btn.click(); return; }
        }
    };
    const obs = new MutationObserver(dismiss);
    obs.observe(document.documentElement, {childList: true, subtree: true});
    dismiss();
})();
"""

_DEAD_BROWSER_HINTS = ("browser has been closed", "target closed")


def _is_dead_browser(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(h in msg for h in _DEAD_BROWSER_HINTS)


class _BrowserThread:
    """Single worker thread that owns all Playwright objects."""

    def __init__(self):
        self._q: queue.Queue = queue.Queue()
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                return
            fut, fn = item
            try:
                fut.set_result(fn())
            except Exception as e:
                fut.set_exception(e)

    def run(self, fn):
        """Submit fn() to the browser thread and block until done."""
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self._q.put((fut, fn))
        return fut.result()

    def stop(self) -> None:
        self._q.put(None)


class BrowserManager:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._bt = _BrowserThread()
        self._pw = None
        self._browser = None
        self._page = None

    def _cfg(self) -> dict:
        return get_config().get("tools", {}).get("browser", {})

    def _reset(self) -> None:
        # Must only be called on the browser thread.
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._pw = None
        self._browser = None
        self._page = None

    def _ensure_page(self):
        # Must only be called on the browser thread.
        if not self._cfg().get("enabled", False):
            raise RuntimeError(
                "browser tools disabled" " — set web.browser.enabled: true"
            )
        if self._browser is not None and not self._browser.is_connected():
            self._reset()
        if self._page is None:
            from playwright.sync_api import sync_playwright

            headless = self._cfg().get("headless", True)
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=headless)
            self._page = self._browser.new_page()
            self._page.add_init_script(_BANNER_SCRIPT)
        return self._page

    def _call(self, op):
        """Run op(page) on the browser thread, retry once on dead-browser."""

        def _on_thread():
            for attempt in range(2):
                try:
                    return op(self._ensure_page())
                except Exception as e:
                    if attempt == 0 and _is_dead_browser(e):
                        self._reset()
                        continue
                    raise

        return self._bt.run(_on_thread)

    def teardown(self) -> None:
        def _on_thread():
            try:
                if self._browser:
                    self._browser.close()
            except Exception:
                pass
            try:
                if self._pw:
                    self._pw.stop()
            except Exception:
                pass
            self._browser = None
            self._page = None
            self._pw = None

        try:
            self._bt.run(_on_thread)
        except Exception:
            pass
        self._bt.stop()

    # ── tools ────────────────────────────────────────────────────────────

    def navigate(self, args: dict) -> dict:
        try:

            def _op(page):
                page.goto(args["url"], wait_until="networkidle")
                return {"status": "ok", "url": page.url, "title": page.title()}

            return self._call(_op)
        except Exception as e:
            return {"error": str(e)}

    def get_text(self, args: dict) -> dict:
        try:
            return self._call(
                lambda page: {"text": page.inner_text("body"), "url": page.url}
            )
        except Exception as e:
            return {"error": str(e)}

    def aria_snapshot(self, args: dict) -> dict:
        try:
            return self._call(
                lambda page: {
                    "tree": page.aria_snapshot(),
                    "url": page.url,
                }
            )
        except Exception as e:
            return {"error": str(e)}

    def click(self, args: dict) -> dict:
        try:

            def _op(page):
                page.click(args["selector"])
                return {"status": "ok", "selector": args["selector"]}

            return self._call(_op)
        except Exception as e:
            return {"error": str(e)}

    def type_text(self, args: dict) -> dict:
        try:

            def _op(page):
                page.fill(args["selector"], args["text"])
                return {"status": "ok", "selector": args["selector"]}

            return self._call(_op)
        except Exception as e:
            return {"error": str(e)}

    def wait(self, args: dict) -> dict:
        try:
            ms = int(args.get("ms", 1000))

            def _op(page):
                page.wait_for_timeout(ms)
                return {"status": "ok", "waited_ms": ms}

            return self._call(_op)
        except Exception as e:
            return {"error": str(e)}

    def scroll(self, args: dict) -> dict:
        try:
            x = int(args.get("x", 0))
            y = int(args.get("y", 0))

            def _op(page):
                page.evaluate(f"window.scrollBy({x}, {y})")
                return {"status": "ok", "scrolled": {"x": x, "y": y}}

            return self._call(_op)
        except Exception as e:
            return {"error": str(e)}

    def hover(self, args: dict) -> dict:
        try:

            def _op(page):
                page.hover(args["selector"])
                return {"status": "ok", "selector": args["selector"]}

            return self._call(_op)
        except Exception as e:
            return {"error": str(e)}

    def select(self, args: dict) -> dict:
        try:

            def _op(page):
                page.select_option(args["selector"], args["value"])
                return {
                    "status": "ok",
                    "selector": args["selector"],
                    "value": args["value"],
                }

            return self._call(_op)
        except Exception as e:
            return {"error": str(e)}

    def screenshot(self, args: dict) -> dict:
        try:
            png_bytes = self._call(lambda page: page.screenshot(type="png"))
        except Exception as e:
            return {"error": str(e)}
        try:
            resp = httpx.post(
                f"{self.base_url}/artifacts/",
                files={
                    "file": (
                        "screenshot_"
                        + datetime.now().strftime("%Y%m%d_%H%M%S")
                        + ".png",
                        io.BytesIO(png_bytes),
                        "image/png",
                    )
                },
                data={"session_id": args.get("session_id", "")},
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=15.0,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": f"screenshot captured but upload failed: {e}"}

    def eval(self, args: dict) -> dict:
        try:
            return self._call(
                lambda page: {"result": page.evaluate(args["script"])}
            )
        except Exception as e:
            return {"error": str(e)}


def make_browser_dispatch(manager: BrowserManager) -> dict:
    # manager.*(args) blocks on the browser thread; wrap in run_in_executor
    # so telegram.py's async event loop is not stalled.
    async def _run(fn, args):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn, args)

    return {
        "browser:navigate": lambda args: _run(manager.navigate, args),
        "browser:get_text": lambda args: _run(manager.get_text, args),
        "browser:aria_snapshot": lambda args: _run(
            manager.aria_snapshot, args
        ),
        "browser:click": lambda args: _run(manager.click, args),
        "browser:type": lambda args: _run(manager.type_text, args),
        "browser:wait": lambda args: _run(manager.wait, args),
        "browser:scroll": lambda args: _run(manager.scroll, args),
        "browser:hover": lambda args: _run(manager.hover, args),
        "browser:select": lambda args: _run(manager.select, args),
        "browser:screenshot": lambda args: _run(manager.screenshot, args),
        "browser:eval": lambda args: _run(manager.eval, args),
    }
