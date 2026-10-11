import re
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.support import sign_in

from core.classify import detect_language
from core.models import Job, SourceStatus
from jobs.refresh import CatalogService
from storage.catalog import Catalog
from storage.filters import CatalogFilters
from web.app import create_app
from web.frontend import i18n
from web.frontend.pages import CatalogView, render_catalog
from web.frontend.report import render_page

DJINNI = SourceStatus("Djinni", True, "ok", fetched=3, kept=3)
ENGLISH_TEXT = (
    "We are looking for a senior backend engineer to build and run our payments platform. "
    "You will design services, review code and mentor the team."
)
UKRAINIAN_TEXT = (
    "Шукаємо досвідченого розробника для розвитку нашої платіжної платформи. "
    "Ви будете проєктувати сервіси, переглядати код і допомагати команді."
)


class TestText:
    def test_every_text_has_both_languages_and_matching_placeholders(self):
        for key in i18n.keys():
            uk, en = i18n.raw(key, "uk"), i18n.raw(key, "en")
            assert uk.strip() and en.strip(), key
            assert _placeholders(uk) == _placeholders(en), key

    def test_language_choice_order(self):
        assert i18n.pick_language("en", "uk", "uk") == "en"
        assert i18n.pick_language("", "en", "uk") == "en"
        assert i18n.pick_language("", "", "en-US,en;q=0.9") == "en"
        assert i18n.pick_language("", "", "uk-UA,uk;q=0.9,en;q=0.5") == "uk"
        assert i18n.pick_language("xx", "yy", "") == "uk"
        assert i18n.pick_language("", "", "en", "uk") == "uk"
        assert i18n.pick_language("", "en", "", "uk") == "en"
        assert i18n.pick_language("uk", "en", "en", "en") == "uk"

    def test_description_language(self):
        assert detect_language(ENGLISH_TEXT) == "en"
        assert detect_language(UKRAINIAN_TEXT) == "uk"
        assert detect_language("Python") == ""
        assert detect_language("") == ""


class TestMarks:
    def test_marks_filter_and_survive_a_refresh(self, tmp_path):
        catalog = _catalog(tmp_path, [_job("1"), _job("2"), _job("3")])
        user = catalog.create_user("ada", "password-1").id
        assert catalog.set_marks("https://example.com/missing", user, favorite=True) is None
        with pytest.raises(ValueError):
            catalog.set_marks("https://example.com/1", user, rating=6)

        catalog.set_marks("https://example.com/1", user, favorite=True, rating=4)
        catalog.set_marks("https://example.com/2", user, hidden=True)
        catalog.set_marks("https://example.com/3", user, viewed=True)

        def urls(**filters):
            return sorted(
                item.job.url[-1] for item in catalog.list_jobs(CatalogFilters(**filters), user)
            )

        assert urls() == ["1", "3"]  # "not for me" is hidden by default
        assert urls(mine="all") == ["1", "2", "3"]
        assert urls(mine="hidden") == ["2"]
        assert urls(mine="favorites") == ["1"]
        assert urls(mine="viewed") == ["3"]
        assert urls(mine="unviewed") == ["1"]
        assert urls(mine="rated") == ["1"]
        assert urls(min_rating=5) == []
        assert urls(min_rating=4) == ["1"]

        # Favorite and "not for me" exclude each other, and viewing keeps the first time.
        marks = catalog.set_marks("https://example.com/1", user, hidden=True)
        assert marks.hidden and not marks.favorite
        first = catalog.set_marks("https://example.com/3", user, viewed=True).viewed_at
        assert catalog.set_marks("https://example.com/3", user, viewed=True).viewed_at == first
        assert not (catalog.set_marks("https://example.com/3", user, viewed=False).viewed)

        # A new refresh must not wipe the notes.
        catalog.merge(
            [_job("1"), _job("2"), _job("3")],
            [DJINNI],
            "2026-10-11 10:00:00",
            "2026-10-11 10:01:00",
        )
        assert next(
            item
            for item in catalog.list_jobs(CatalogFilters(mine="all"), user)
            if item.job.url.endswith("/2")
        ).marks.hidden

    def test_quick_changes_to_one_vacancy_do_not_overwrite_each_other(self, tmp_path):
        catalog = _catalog(tmp_path, [_job("1")])
        user = catalog.create_user("ada", "password-1").id
        url = "https://example.com/1"
        for _ in range(15):
            catalog.set_marks(url, user, favorite=False, rating=0, viewed=False)
            changes = [
                {"favorite": True},
                {"rating": 4},
                {"viewed": True},
            ]
            threads = [
                threading.Thread(target=lambda c=change: catalog.set_marks(url, user, **c))
                for change in changes
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            marks = catalog.list_jobs(CatalogFilters(), user)[0].marks
            assert marks.favorite and marks.viewed and marks.rating == 4

    def test_added_changed_and_closed_are_told_apart(self, tmp_path):
        catalog = _catalog(tmp_path, [_job("1"), _job("2"), _job("3", snippet=UKRAINIAN_TEXT)])
        catalog.merge(
            [
                _job("1", salary_max=4000, salary_text="до $4000"),
                _job("3", snippet=ENGLISH_TEXT),
                _job("4"),
            ],
            [DJINNI],
            "2026-10-11 10:00:00",
            "2026-10-11 10:01:00",
        )
        by_id = {
            item.job.job_id: item
            for item in catalog.list_jobs(CatalogFilters(include_inactive=True))
        }
        assert by_id["4"].change == "added"
        assert by_id["1"].change == "changed"
        assert "salary_max" in by_id["1"].changes
        assert by_id["2"].change == "closed"
        assert by_id["3"].change == ""  # the snippet alone is not a change
        assert by_id["3"].language == "en"

        def ids(**filters):
            return sorted(item.job.job_id for item in catalog.list_jobs(CatalogFilters(**filters)))

        assert ids(change="added") == ["4"]
        assert ids(change="changed") == ["1"]
        assert ids(change="closed") == ["2"]
        assert ids(language="en") == ["3"]

    def test_first_refresh_marks_nothing_as_new(self, tmp_path):
        catalog = _catalog(tmp_path, [_job("1")])
        assert [item.change for item in catalog.list_jobs(CatalogFilters())] == [""]

    def test_a_vacancy_that_comes_back_counts_as_changed(self, tmp_path):
        catalog = _catalog(tmp_path, [_job("1"), _job("2")])
        catalog.merge([_job("1")], [DJINNI], "2026-10-11 10:00:00", "2026-10-11 10:01:00")
        catalog.merge(
            [_job("1"), _job("2")], [DJINNI], "2026-10-12 10:00:00", "2026-10-12 10:01:00"
        )
        back = next(item for item in catalog.list_jobs(CatalogFilters()) if item.job.job_id == "2")
        assert back.change == "changed"
        assert "active" in back.changes


class TestWeb:
    @pytest.fixture(autouse=True)
    def _client(self, tmp_path):
        jobs = [
            _job(str(n), title=f"Engineer {n:03d}", published=f"2026-10-{n % 28 + 1:02d}")
            for n in range(1, 61)
        ]
        self.catalog = _catalog(tmp_path, jobs)
        service = CatalogService(self.catalog, interval_hours=24, pages=1)
        service.running = True
        self.client = TestClient(
            create_app(self.catalog, service, start_scheduler=False),
            base_url="http://127.0.0.1",
            raise_server_exceptions=False,
        )
        sign_in(self.client, self.catalog)

    def test_state_api(self):
        url = "https://example.com/1"
        ok = self.client.post("/api/jobs/state", json={"url": url, "favorite": True, "rating": 3})
        assert ok.status_code == 200
        assert ok.json() == {"favorite": True, "hidden": False, "rating": 3, "viewed": False}
        shown = {item["url"]: item for item in self.client.get("/api/jobs").json()}
        assert shown[url]["favorite"]
        assert shown[url]["rating"] == 3

        def post(body, **kwargs):
            return self.client.post("/api/jobs/state", json=body, **kwargs).status_code

        assert post({"url": "https://example.com/none", "viewed": True}) == 404
        assert post({"url": url, "rating": 9}) == 422
        assert post({"url": url, "color": "red"}) == 422
        assert post({"url": url, "viewed": True}, headers={"Origin": "https://evil.example"}) == 403
        form = self.client.post(
            "/api/jobs/state", content="url=x", headers={"Content-Type": "text/plain"}
        )
        assert form.status_code in (415, 422)

    def test_paging_and_show_more_do_not_repeat_or_lose_rows(self):
        first = self.client.get("/", params={"per_page": 25})
        assert len(re.findall(r'<tr[^>]* data-url="', first.text)) == 25
        assert "1–25" in first.text
        assert 'id="more"' in first.text
        assert 'aria-current="page"' in first.text

        seen = set(re.findall(r'data-url="([^"]+)"', first.text))
        page = 2
        while True:
            part = self.client.get("/fragments/rows", params={"per_page": 25, "page": page}).json()
            found = set(re.findall(r'data-url="([^"]+)"', part["html"]))
            assert not (seen & found)
            seen |= found
            if not part["next"]:
                break
            page = part["next"]
        assert len(seen) == 60
        assert part["last"] == 60
        beyond = self.client.get("/fragments/rows", params={"per_page": 25, "page": 9}).json()
        assert (beyond["html"], beyond["next"]) == ("", None)
        # An out-of-range or junk page falls back instead of failing.
        assert self.client.get("/", params={"page": "999", "per_page": "25"}).status_code == 200
        assert self.client.get("/", params={"page": "x", "per_page": "7"}).status_code == 200

    def test_language_switch_is_remembered(self):
        assert '<html lang="uk">' in self.client.get("/").text
        english = self.client.get("/", params={"lang": "en"})
        assert '<html lang="en">' in english.text
        assert "Remote IT jobs with reservation" in english.text
        assert "lang=en" in english.headers["set-cookie"]
        # The cookie carries the choice to the next page, and to the "show more" rows.
        assert '<html lang="en">' in self.client.get("/").text
        assert "My rating" in self.client.get("/fragments/rows").json()["html"]
        other = TestClient(
            create_app(self.catalog, CatalogService(self.catalog), start_scheduler=False),
            base_url="http://127.0.0.1",
        )
        sign_in(other, self.catalog, "ben", "password-2")
        assert (
            '<html lang="en">' in other.get("/", headers={"Accept-Language": "en-GB,en;q=0.8"}).text
        )

    def test_filter_form_keeps_its_values(self):
        page = self.client.get(
            "/",
            params={
                "mine": "favorites",
                "min_rating": "3",
                "change": "added",
                "language": "en",
                "per_page": "100",
            },
        ).text
        for expected in (
            '<option value="favorites" selected>',
            '<option value="3" selected>',
            '<option value="added" selected>',
            '<option value="en" selected>',
            '<option value="100" selected>',
        ):
            assert expected in page
        # Unknown values are dropped instead of echoed.
        junk = self.client.get("/", params={"mine": "<script>", "change": "x"}).text
        assert "<script>alert" not in junk
        assert '<option value="" selected>' in junk


class TestRender:
    def test_rows_show_state_marks_and_english_chip(self, tmp_path):
        catalog = _catalog(tmp_path, [_job("1"), _job("2"), _job("3", snippet=ENGLISH_TEXT)])
        catalog.merge(
            [
                _job("1", salary_max=4000, salary_text="до $4000"),
                _job("3", snippet=ENGLISH_TEXT),
                _job("4"),
            ],
            [DJINNI],
            "2026-10-11 10:00:00",
            "2026-10-11 10:01:00",
        )
        user = catalog.create_user("ada", "password-1").id
        catalog.set_marks("https://example.com/3", user, viewed=True, favorite=True, rating=2)
        items = catalog.list_jobs(CatalogFilters(include_inactive=True), user)
        view = CatalogView(
            items=items, total=len(items), page=1, per_page=50, filters=CatalogFilters()
        )
        uk = render_catalog(view)
        for expected in ("tag-new", "tag-changed", "tag-closed", "chip-en", "viewed", "is-fav"):
            assert expected in uk
        assert "нова" in uk
        assert "Змінилось: зарплата" in uk
        view.language = "en"
        en = render_catalog(view)
        assert "Changed: salary" in en
        assert "Not for me" in en
        assert "Мої позначки" not in en

    def test_report_page_has_no_actions_and_speaks_both_languages(self):
        for language, title in (("uk", "Віддалені IT-вакансії"), ("en", "Remote IT jobs")):
            page = render_page([_job("1")], [DJINNI], language)
            assert title in page
            assert 'data-act="favorite"' not in page
            assert 'class="static"' in page


def _placeholders(text: str) -> set[str]:
    return set(re.findall(r"\{(\w+)\}", text))


def _catalog(tmp_path: Path, jobs: list[Job]) -> Catalog:
    catalog = Catalog(tmp_path / "catalog.sqlite")
    catalog.merge(jobs, [DJINNI], "2026-10-10 10:00:00", "2026-10-10 10:01:00")
    return catalog


def _job(number: str, **overrides) -> Job:
    data = dict(
        source="Djinni",
        job_id=number,
        title=f"Developer {number}",
        company="Example",
        company_url="",
        url=f"https://example.com/{number}",
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
