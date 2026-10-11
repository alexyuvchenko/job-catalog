import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.models import Job
from network.browser import Browser
from network.client import Client, FetchError
from sources.djinni import fetch_jobs as fetch_djinni
from sources.dou import verify_reservation

BADGE = '<a href="https://jobs.dou.ua/vacancies/?search=бронювання&amp;from=badge">Бронювання</a>'


class TestClientRead:
    def test_timeout_while_reading_the_body_is_a_fetch_error(self):
        class Body:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                raise TimeoutError("timed out")

            def geturl(self):
                return "https://example.com/"

        client = Client(delay=0)
        client._opener = SimpleNamespace(open=lambda request, timeout=None: Body())
        with pytest.raises(FetchError):
            client.get_text("https://example.com/")


class TestPartialRead:
    def test_djinni_that_stops_after_page_one_is_not_complete(self):
        pages = []

        class Fake:
            def get_text(self, url, referer=None):
                pages.append(url)
                if len(pages) > 1:
                    raise FetchError("503")
                return "page"

        first_page = [_job(job_id=str(number), url=f"https://x/{number}") for number in range(10)]
        with patch("sources.djinni.parse_djinni_html", return_value=(first_page, 30)):
            listing = fetch_djinni(Fake(), "", 5)
        assert len(listing.jobs) == 10
        assert not (listing.complete)
        assert "не знімаються" in listing.message

    def test_djinni_that_reads_everything_is_complete(self):
        first_page = [_job(job_id=str(number), url=f"https://x/{number}") for number in range(3)]

        class Fake:
            def get_text(self, url, referer=None):
                return "page"

        with patch("sources.djinni.parse_djinni_html", return_value=(first_page, 3)):
            listing = fetch_djinni(Fake(), "", 5)
        assert listing.complete


class TestDouBadgeCache:
    def test_badge_answers_expire_and_survive_a_failed_recheck(self, tmp_path):
        class Fake:
            def __init__(self, html):
                self.html = html
                self.calls = 0

            def get_text(self, url, referer=None):
                self.calls += 1
                if isinstance(self.html, Exception):
                    raise self.html
                return self.html

        cache = tmp_path / "cache.sqlite"

        def run(client, job_id="1"):
            job = _job(source="DOU", job_id=job_id, url=f"https://jobs.dou.ua/vacancies/{job_id}/")
            return verify_reservation(client, [job], cache, refresh=False)

        def age(days):
            with sqlite3.connect(cache) as connection:
                connection.execute(
                    "UPDATE dou_check SET checked_at = datetime('now', ?)", (f"-{days} days",)
                )

        # A missing badge is rechecked after a day, so a later badge is picked up.
        nothing = Fake("<html>no badge</html>")
        kept, dropped = run(nothing)
        assert (len(kept), dropped) == (0, 1)
        run(nothing)
        assert nothing.calls == 1
        age(2)
        gained = Fake(BADGE)
        kept, dropped = run(gained)
        assert (len(kept), dropped, gained.calls) == (1, 0, 1)
        assert kept[0].reservation == "confirmed"

        # A found badge is trusted for a week, then rechecked.
        run(gained)
        assert gained.calls == 1
        age(3)
        run(gained)
        assert gained.calls == 1
        age(8)
        lost = Fake("<html>gone</html>")
        kept, dropped = run(lost)
        assert (len(kept), dropped, lost.calls) == (0, 1, 1)

        # When the page does not open, the older answer is used.
        age(8)
        down = Fake(FetchError("503"))
        kept, dropped = run(down)
        assert (len(kept), dropped, down.calls) == (0, 1, 1)

        # A vacancy never checked before stays as unverified.
        kept, dropped = run(down, job_id="2")
        assert (len(kept), dropped) == (1, 0)
        assert kept[0].reservation == "unverified"


class TestHumanCheckWait:
    def test_unattended_run_fails_fast_and_never_opens_a_window(self):
        browser, moves = _browser(["Verify you are human"] * 50, interactive=False)
        with pytest.raises(FetchError):
            browser._wait_for_check("https://ua.jooble.org/", None)
        assert moves == []

    def test_attended_run_waits_then_hides_the_window_again(self):
        browser, moves = _browser(["Verify you are human"] * 3 + ["Python Developer"])
        browser._wait_for_check("https://ua.jooble.org/", None)
        assert moves == [(80, 80), (-2400, -2400)]

    def test_waiting_gives_up_and_hides_the_window(self):
        browser, moves = _browser(["Verify you are human"] * 1000)
        with pytest.raises(FetchError):
            browser._wait_for_check("https://ua.jooble.org/", None)
        assert moves[-1] == (-2400, -2400)

    def test_a_stopped_refresh_does_not_keep_waiting(self):
        browser, moves = _browser(["Verify you are human"] * 1000)
        browser.cancelled = lambda: True
        with pytest.raises(FetchError) as caught:
            browser._wait_for_check("https://ua.jooble.org/", None)
        assert "зупинено" in str(caught.value)
        assert moves == []


def _browser(bodies: list[str], interactive: bool = True):
    class Locator:
        def __init__(self, page):
            self.page = page

        def count(self):
            return 0

        def inner_text(self, timeout=0):
            return self.page.body()

    class Page:
        def __init__(self):
            self.waits = 0

        def body(self):
            return bodies[min(self.waits, len(bodies) - 1)]

        def title(self):
            return "Jooble"

        def locator(self, _selector):
            return Locator(self)

        def wait_for_timeout(self, _ms):
            self.waits += 1

    moves: list[tuple[int, int]] = []
    browser = Browser(interactive=interactive)
    browser.page = Page()
    browser._place_window = lambda left, top: moves.append((left, top))
    return browser, moves


def _job(**overrides) -> Job:
    data = dict(
        source="Djinni",
        job_id="1",
        title="Python Developer",
        company="Example",
        company_url="",
        url="https://example.com/1",
        location="Україна",
        remote="full",
        salary_min=None,
        salary_max=None,
        currency=None,
        salary_text="",
        category="Python",
        english="B2",
        years=3,
        published="2026-10-09",
        reservation="confirmed",
        evidence="",
        snippet="",
    )
    data.update(overrides)
    return Job(**data)
