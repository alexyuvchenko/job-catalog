from __future__ import annotations

import http.client
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

try:
    import certifi
except ImportError:  # pragma: no cover - exercised only when the dep is missing
    certifi = None

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


class FetchError(RuntimeError):
    pass


class Client:
    """Polite HTTP client. One request at a time, with a pause between calls."""

    def __init__(self, delay: float = 0.35, timeout: float = 25.0) -> None:
        self.delay = delay
        self.timeout = timeout
        self._last_request = 0.0
        self._cookies = CookieJar()
        if certifi is None:
            context = ssl.create_default_context()
        else:
            context = ssl.create_default_context(cafile=certifi.where())
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=context),
            urllib.request.HTTPCookieProcessor(self._cookies),
        )

    def cookie(self, name: str, domain: str = "") -> str:
        host = domain.lower().lstrip(".")
        chosen = ""
        best = -1
        for item in self._cookies:
            if item.name != name:
                continue
            cookie_domain = (item.domain or "").lower().lstrip(".")
            if host and cookie_domain != host and not host.endswith("." + cookie_domain):
                continue
            if len(cookie_domain) >= best:
                best = len(cookie_domain)
                chosen = item.value
        return chosen

    def get_text(self, url: str, referer: str | None = None) -> str:
        return self._request(url, method="GET", referer=referer).decode("utf-8", "replace")

    def post_json(self, url: str, data: dict, referer: str) -> dict:
        body = urllib.parse.urlencode(data).encode("utf-8")
        raw = self._request(
            url,
            method="POST",
            data=body,
            referer=referer,
            extra={"Content-Type": "application/x-www-form-urlencoded"},
            ajax=True,
        )
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError as exc:
            raise FetchError(f"Expected JSON from {url}") from exc

    def _request(
        self,
        url: str,
        method: str,
        data: bytes | None = None,
        referer: str | None = None,
        extra: dict | None = None,
        ajax: bool = False,
    ) -> bytes:
        self._wait()
        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Language": "uk,en;q=0.8",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        }
        if referer:
            headers["Referer"] = referer
        if ajax:
            headers["X-Requested-With"] = "XMLHttpRequest"
        if extra:
            headers.update(extra)
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                payload = response.read()
                final_url = response.geturl()
        except urllib.error.HTTPError as exc:
            raise FetchError(f"{exc.code} for {url}") from exc
        except urllib.error.URLError as exc:
            raise FetchError(f"Could not reach {url}: {exc.reason}") from exc
        except (OSError, http.client.HTTPException) as exc:
            # A timeout or a dropped connection while the body is being read.
            raise FetchError(f"Could not read {url}: {exc}") from exc
        finally:
            self._last_request = time.monotonic()
        if "cdn-cgi/challenge" in final_url or b"cf-browser-verification" in payload[:4000]:
            raise FetchError(f"Blocked by a browser check at {url}")
        head = payload[:8000].decode("utf-8", "replace")
        if "Перевірка надійності підключення" in head:
            raise FetchError(f"Blocked by a browser check at {url}")
        return payload

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if self._last_request and elapsed < self.delay:
            time.sleep(self.delay - elapsed)
