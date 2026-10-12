from __future__ import annotations

import logging
import urllib.parse
from collections.abc import Callable

from network.client import FetchError

log = logging.getLogger("jobsearch")

# "Just a moment" often clears on its own. The checkbox does not, so Chrome is
# moved on screen and the fetch waits for a person to finish it.
_AUTO_TICKS = 12
_HUMAN_TICKS = 200
_TICK_MS = 1500
_CHALLENGE = (
    "just a moment",
    "verify you are human",
    "перевірка надійності",
    "підтвердьте, що ви людина",
)
_HUMAN = (
    "verify you are human",
    "підтвердьте, що ви людина",
)


def is_browser_check(title: str, body: str = "") -> bool:
    blob = f"{title}\n{body}".lower()
    return any(marker in blob for marker in _CHALLENGE)


def asks_for_human(title: str, body: str = "") -> bool:
    blob = f"{title}\n{body}".lower()
    return any(marker in blob for marker in _HUMAN)


class BrowserError(FetchError):
    pass


class Browser:
    """Headed Chrome for sites that refuse scripted HTTP clients.

    The window is opened off-screen. Work.ua, Robota.ua, and Jooble pass their
    browser check there; headless Chrome does not.
    """

    def __init__(self, interactive: bool = True) -> None:
        # With nobody at the machine, a human check fails fast instead of opening a window.
        self.interactive = interactive
        self.cancelled: Callable[[], bool] | None = None
        self._playwright = None
        self._browser = None
        self.page = None

    def __enter__(self) -> Browser:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserError("Playwright is not installed. Run: uv sync") from exc
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(
                channel="chrome",
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--window-position=-2400,-2400",
                    "--window-size=1100,800",
                ],
            )
        except Exception as exc:
            self.close()
            raise BrowserError(
                "Google Chrome is required to read Work.ua, Robota.ua, and Jooble. "
                f"Could not start it: {exc}"
            ) from exc
        self.page = self._browser.new_page()
        self.page.set_default_navigation_timeout(45000)
        return self

    def close(self) -> None:
        try:
            if self._browser is not None:
                self._browser.close()
        except Exception as exc:
            log.warning("Chrome did not close cleanly: %s", exc)
        finally:
            self._browser = None
        try:
            if self._playwright is not None:
                self._playwright.stop()
        except Exception as exc:
            log.warning("Playwright did not stop cleanly: %s", exc)
        finally:
            self._playwright = None
            self.page = None

    def __exit__(self, *_) -> None:
        self.close()

    def goto(self, url: str, selector: str | None = None) -> None:
        assert self.page is not None
        self.page.goto(url, wait_until="domcontentloaded")
        self._wait_for_check(url, selector)
        if selector:
            try:
                self.page.wait_for_selector(selector, timeout=8000)
            except Exception:
                # An empty results page is still a successful load.
                return

    def _wait_for_check(self, url: str, selector: str | None) -> None:
        assert self.page is not None
        ticks = 0
        limit = _AUTO_TICKS
        prompted = False
        try:
            while self._blocked(selector):
                if self.cancelled is not None and self.cancelled():
                    raise FetchError("refresh stopped during the site check")
                if ticks >= _AUTO_TICKS or self._asks_for_human():
                    if not self.interactive:
                        raise FetchError(
                            "the page is asking to verify you are human; "
                            "start refresh with the button when you are at the computer"
                        )
                    if not prompted:
                        prompted = True
                        limit = ticks + _HUMAN_TICKS
                        self._place_window(80, 80)
                        log.warning(
                            "%s is asking to verify you are human. "
                            "Finish the check in the Chrome window.",
                            _host(url),
                        )
                if ticks >= limit:
                    raise FetchError("the page is asking to verify you are human")
                self.page.wait_for_timeout(_TICK_MS)
                ticks += 1
        finally:
            if prompted:
                self._place_window(-2400, -2400)

    def _blocked(self, selector: str | None) -> bool:
        assert self.page is not None
        if selector:
            try:
                if self.page.locator(selector).count() > 0:
                    return False
            except Exception:
                pass
        title = self.page.title()
        body = ""
        try:
            body = self.page.locator("body").inner_text(timeout=1000)
        except Exception:
            body = ""
        if is_browser_check(title, body):
            return True
        try:
            return (
                self.page.locator(
                    "iframe[src*='challenges.cloudflare.com'], "
                    "#challenge-stage, #cf-challenge-running"
                ).count()
                > 0
            )
        except Exception:
            return False

    def _asks_for_human(self) -> bool:
        assert self.page is not None
        body = ""
        try:
            body = self.page.locator("body").inner_text(timeout=1000)
        except Exception:
            body = ""
        if asks_for_human(self.page.title(), body):
            return True
        try:
            return (
                self.page.locator(
                    "iframe[src*='challenges.cloudflare.com'], #challenge-stage"
                ).count()
                > 0
            )
        except Exception:
            return False

    def _place_window(self, left: int, top: int) -> None:
        assert self.page is not None
        try:
            client = self.page.context.new_cdp_session(self.page)
            info = client.send("Browser.getWindowForTarget")
            client.send(
                "Browser.setWindowBounds",
                {
                    "windowId": info["windowId"],
                    "bounds": {
                        "left": left,
                        "top": top,
                        "width": 1100,
                        "height": 800,
                        "windowState": "normal",
                    },
                },
            )
            client.detach()
        except Exception as exc:
            log.warning("Could not move the Chrome window: %s", exc)
        self.page.bring_to_front()

    def evaluate(self, expression: str):
        assert self.page is not None
        return self.page.evaluate(expression)


def _host(url: str) -> str:
    host = urllib.parse.urlparse(url).hostname or ""
    if "jooble" in host:
        return "Jooble"
    if "work.ua" in host:
        return "Work.ua"
    if "robota.ua" in host:
        return "Robota.ua"
    return host or url
