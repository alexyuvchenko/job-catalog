import re
import tempfile
import threading
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from jobsearch.classify import detect_language
from jobsearch.db.catalog import Catalog, CatalogFilters
from jobsearch.models import Job, SourceStatus
from jobsearch.service import CatalogService
from jobsearch.web import i18n
from jobsearch.web.pages import CatalogView, render_catalog
from jobsearch.web.report import render_page
from jobsearch.web.server import create_app

DJINNI = SourceStatus("Djinni", True, "ok", fetched=3, kept=3)
ENGLISH_TEXT = (
    "We are looking for a senior backend engineer to build and run our payments platform. "
    "You will design services, review code and mentor the team."
)
UKRAINIAN_TEXT = (
    "Шукаємо досвідченого розробника для розвитку нашої платіжної платформи. "
    "Ви будете проєктувати сервіси, переглядати код і допомагати команді."
)


class TextTests(unittest.TestCase):
    def test_every_text_has_both_languages_and_matching_placeholders(self):
        for key in i18n.keys():
            uk, en = i18n.raw(key, "uk"), i18n.raw(key, "en")
            self.assertTrue(uk.strip() and en.strip(), key)
            self.assertEqual(_placeholders(uk), _placeholders(en), key)

    def test_language_choice_order(self):
        self.assertEqual(i18n.pick_language("en", "uk", "uk"), "en")
        self.assertEqual(i18n.pick_language("", "en", "uk"), "en")
        self.assertEqual(i18n.pick_language("", "", "en-US,en;q=0.9"), "en")
        self.assertEqual(i18n.pick_language("", "", "uk-UA,uk;q=0.9,en;q=0.5"), "uk")
        self.assertEqual(i18n.pick_language("xx", "yy", ""), "uk")

    def test_description_language(self):
        self.assertEqual(detect_language(ENGLISH_TEXT), "en")
        self.assertEqual(detect_language(UKRAINIAN_TEXT), "uk")
        self.assertEqual(detect_language("Python"), "")
        self.assertEqual(detect_language(""), "")


class MarksTests(unittest.TestCase):
    def test_marks_filter_and_survive_a_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = _catalog(folder, [_job("1"), _job("2"), _job("3")])
            self.assertIsNone(catalog.set_marks("https://example.com/missing", favorite=True))
            with self.assertRaises(ValueError):
                catalog.set_marks("https://example.com/1", rating=6)

            catalog.set_marks("https://example.com/1", favorite=True, rating=4)
            catalog.set_marks("https://example.com/2", hidden=True)
            catalog.set_marks("https://example.com/3", viewed=True)

            def urls(**filters):
                return sorted(
                    item.job.url[-1] for item in catalog.list_jobs(CatalogFilters(**filters))
                )

            self.assertEqual(urls(), ["1", "3"])  # "not for me" is hidden by default
            self.assertEqual(urls(mine="all"), ["1", "2", "3"])
            self.assertEqual(urls(mine="hidden"), ["2"])
            self.assertEqual(urls(mine="favorites"), ["1"])
            self.assertEqual(urls(mine="viewed"), ["3"])
            self.assertEqual(urls(mine="unviewed"), ["1"])
            self.assertEqual(urls(mine="rated"), ["1"])
            self.assertEqual(urls(min_rating=5), [])
            self.assertEqual(urls(min_rating=4), ["1"])

            # Favorite and "not for me" exclude each other, and viewing keeps the first time.
            marks = catalog.set_marks("https://example.com/1", hidden=True)
            self.assertTrue(marks.hidden and not marks.favorite)
            first = catalog.set_marks("https://example.com/3", viewed=True).viewed_at
            self.assertEqual(
                catalog.set_marks("https://example.com/3", viewed=True).viewed_at, first
            )
            self.assertFalse(catalog.set_marks("https://example.com/3", viewed=False).viewed)

            # A new refresh must not wipe the notes.
            catalog.merge(
                [_job("1"), _job("2"), _job("3")],
                [DJINNI],
                "2026-10-11 10:00:00",
                "2026-10-11 10:01:00",
            )
            self.assertTrue(
                next(
                    item
                    for item in catalog.list_jobs(CatalogFilters(mine="all"))
                    if item.job.url.endswith("/2")
                ).marks.hidden
            )

    def test_quick_changes_to_one_vacancy_do_not_overwrite_each_other(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = _catalog(folder, [_job("1")])
            url = "https://example.com/1"
            for _ in range(15):
                catalog.set_marks(url, favorite=False, rating=0, viewed=False)
                changes = [
                    {"favorite": True},
                    {"rating": 4},
                    {"viewed": True},
                ]
                threads = [
                    threading.Thread(target=lambda c=change: catalog.set_marks(url, **c))
                    for change in changes
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
                marks = catalog.list_jobs(CatalogFilters())[0].marks
                self.assertTrue(marks.favorite and marks.viewed and marks.rating == 4)

    def test_added_changed_and_closed_are_told_apart(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = _catalog(folder, [_job("1"), _job("2"), _job("3", snippet=UKRAINIAN_TEXT)])
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
            self.assertEqual(by_id["4"].change, "added")
            self.assertEqual(by_id["1"].change, "changed")
            self.assertIn("salary_max", by_id["1"].changes)
            self.assertEqual(by_id["2"].change, "closed")
            self.assertEqual(by_id["3"].change, "")  # the snippet alone is not a change
            self.assertEqual(by_id["3"].language, "en")

            def ids(**filters):
                return sorted(
                    item.job.job_id for item in catalog.list_jobs(CatalogFilters(**filters))
                )

            self.assertEqual(ids(change="added"), ["4"])
            self.assertEqual(ids(change="changed"), ["1"])
            self.assertEqual(ids(change="closed"), ["2"])
            self.assertEqual(ids(language="en"), ["3"])

    def test_first_refresh_marks_nothing_as_new(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = _catalog(folder, [_job("1")])
            self.assertEqual([item.change for item in catalog.list_jobs(CatalogFilters())], [""])

    def test_a_vacancy_that_comes_back_counts_as_changed(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = _catalog(folder, [_job("1"), _job("2")])
            catalog.merge([_job("1")], [DJINNI], "2026-10-11 10:00:00", "2026-10-11 10:01:00")
            catalog.merge(
                [_job("1"), _job("2")], [DJINNI], "2026-10-12 10:00:00", "2026-10-12 10:01:00"
            )
            back = next(
                item for item in catalog.list_jobs(CatalogFilters()) if item.job.job_id == "2"
            )
            self.assertEqual(back.change, "changed")
            self.assertIn("active", back.changes)


class WebTests(unittest.TestCase):
    def setUp(self):
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        jobs = [
            _job(str(n), title=f"Engineer {n:03d}", published=f"2026-10-{n % 28 + 1:02d}")
            for n in range(1, 61)
        ]
        self.catalog = _catalog(self._folder.name, jobs)
        service = CatalogService(self.catalog, interval_hours=24, pages=1)
        service.running = True
        self.client = TestClient(
            create_app(self.catalog, service, start_scheduler=False),
            base_url="http://127.0.0.1",
            raise_server_exceptions=False,
        )

    def test_state_api(self):
        url = "https://example.com/1"
        ok = self.client.post("/api/jobs/state", json={"url": url, "favorite": True, "rating": 3})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(
            ok.json(), {"favorite": True, "hidden": False, "rating": 3, "viewed": False}
        )
        shown = {item["url"]: item for item in self.client.get("/api/jobs").json()}
        self.assertTrue(shown[url]["favorite"])
        self.assertEqual(shown[url]["rating"], 3)

        def post(body, **kwargs):
            return self.client.post("/api/jobs/state", json=body, **kwargs).status_code

        self.assertEqual(post({"url": "https://example.com/none", "viewed": True}), 404)
        self.assertEqual(post({"url": url, "rating": 9}), 422)
        self.assertEqual(post({"url": url, "color": "red"}), 422)
        self.assertEqual(
            post({"url": url, "viewed": True}, headers={"Origin": "https://evil.example"}), 403
        )
        form = self.client.post(
            "/api/jobs/state", content="url=x", headers={"Content-Type": "text/plain"}
        )
        self.assertIn(form.status_code, (415, 422))

    def test_paging_and_show_more_do_not_repeat_or_lose_rows(self):
        first = self.client.get("/", params={"per_page": 25})
        self.assertEqual(len(re.findall(r'<tr[^>]* data-url="', first.text)), 25)
        self.assertIn("1–25", first.text)
        self.assertIn('id="more"', first.text)
        self.assertIn('aria-current="page"', first.text)

        seen = set(re.findall(r'data-url="([^"]+)"', first.text))
        page = 2
        while True:
            part = self.client.get("/fragments/rows", params={"per_page": 25, "page": page}).json()
            found = set(re.findall(r'data-url="([^"]+)"', part["html"]))
            self.assertFalse(seen & found)
            seen |= found
            if not part["next"]:
                break
            page = part["next"]
        self.assertEqual(len(seen), 60)
        self.assertEqual(part["last"], 60)
        beyond = self.client.get("/fragments/rows", params={"per_page": 25, "page": 9}).json()
        self.assertEqual((beyond["html"], beyond["next"]), ("", None))
        # An out-of-range or junk page falls back instead of failing.
        self.assertEqual(
            self.client.get("/", params={"page": "999", "per_page": "25"}).status_code, 200
        )
        self.assertEqual(
            self.client.get("/", params={"page": "x", "per_page": "7"}).status_code, 200
        )

    def test_language_switch_is_remembered(self):
        self.assertIn('<html lang="uk">', self.client.get("/").text)
        english = self.client.get("/", params={"lang": "en"})
        self.assertIn('<html lang="en">', english.text)
        self.assertIn("Remote IT jobs with reservation", english.text)
        self.assertIn("lang=en", english.headers["set-cookie"])
        # The cookie carries the choice to the next page, and to the "show more" rows.
        self.assertIn('<html lang="en">', self.client.get("/").text)
        self.assertIn("My rating", self.client.get("/fragments/rows").json()["html"])
        self.assertIn(
            '<html lang="en">',
            TestClient(
                create_app(self.catalog, CatalogService(self.catalog), start_scheduler=False),
                base_url="http://127.0.0.1",
            )
            .get("/", headers={"Accept-Language": "en-GB,en;q=0.8"})
            .text,
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
            self.assertIn(expected, page)
        # Unknown values are dropped instead of echoed.
        junk = self.client.get("/", params={"mine": "<script>", "change": "x"}).text
        self.assertNotIn("<script>alert", junk)
        self.assertIn('<option value="" selected>', junk)


class RenderTests(unittest.TestCase):
    def test_rows_show_state_marks_and_english_chip(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = _catalog(folder, [_job("1"), _job("2"), _job("3", snippet=ENGLISH_TEXT)])
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
            catalog.set_marks("https://example.com/3", viewed=True, favorite=True, rating=2)
            items = catalog.list_jobs(CatalogFilters(include_inactive=True))
            view = CatalogView(
                items=items, total=len(items), page=1, per_page=50, filters=CatalogFilters()
            )
            uk = render_catalog(view)
            for expected in ("tag-new", "tag-changed", "tag-closed", "chip-en", "viewed", "is-fav"):
                self.assertIn(expected, uk)
            self.assertIn("нова", uk)
            self.assertIn("Змінилось: зарплата", uk)
            view.language = "en"
            en = render_catalog(view)
            self.assertIn("Changed: salary", en)
            self.assertIn("Not for me", en)
            self.assertNotIn("Мої позначки", en)

    def test_report_page_has_no_actions_and_speaks_both_languages(self):
        for language, title in (("uk", "Віддалені IT-вакансії"), ("en", "Remote IT jobs")):
            page = render_page([_job("1")], [DJINNI], language)
            self.assertIn(title, page)
            self.assertNotIn('data-act="favorite"', page)
            self.assertIn('class="static"', page)


def _placeholders(text: str) -> set[str]:
    return set(re.findall(r"\{(\w+)\}", text))


def _catalog(folder: str, jobs: list[Job]) -> Catalog:
    catalog = Catalog(Path(folder) / "catalog.sqlite")
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


if __name__ == "__main__":
    unittest.main()
