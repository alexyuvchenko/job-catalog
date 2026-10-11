import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from jobsearch.db.catalog import Catalog, CatalogFilters
from jobsearch.models import Job, SourceStatus
from jobsearch.service import CatalogService
from jobsearch.web.pages import CatalogView, render_catalog
from jobsearch.web.server import create_app


class CatalogTests(unittest.TestCase):
    def test_sorting_by_column_and_direction(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = Catalog(Path(folder) / "catalog.sqlite")
            jobs = [
                _job(url="https://example.com/1", job_id="1", title="b", company="Zeta"),
                _job(url="https://example.com/2", job_id="2", title="A", company="alpha"),
            ]
            status = SourceStatus("Djinni", True, "ok", fetched=2, kept=2)
            catalog.merge(jobs, [status], "2026-10-10 10:00:00", "2026-10-10 10:01:00")

            def titles(**kwargs):
                return [s.job.title for s in catalog.list_jobs(CatalogFilters(**kwargs))]

            self.assertEqual(titles(sort="job"), ["A", "b"])
            self.assertEqual(titles(sort="job", descending=True), ["b", "A"])
            self.assertEqual(titles(sort="company"), ["A", "b"])
            self.assertEqual(titles(sort="company", descending=True), ["b", "A"])

    def test_merge_updates_keeps_failures_and_marks_only_new_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = Catalog(Path(folder) / "catalog.sqlite")
            first = _job(url="https://example.com/1", title="Python Developer")
            gone = _job(url="https://example.com/2", job_id="2", title="Go Engineer")
            djinni = SourceStatus("Djinni", True, "ok", fetched=2, kept=2)
            catalog.merge([first, gone], [djinni], "2026-10-10 10:00:00", "2026-10-10 10:01:00")

            changed = _job(
                url="https://example.com/1",
                title="Python Developer",
                salary_text="до $3000",
                salary_max=3000,
            )
            fresh = _job(url="https://example.com/3", job_id="3", title="QA Engineer")
            failed = SourceStatus("DOU", False, "timeout", fetched=0, kept=0)
            empty = SourceStatus("Work.ua", True, "порожньо", fetched=0, kept=0)
            catalog.merge(
                [changed, fresh],
                [djinni, failed, empty],
                "2026-10-10 16:00:00",
                "2026-10-10 16:05:00",
            )

            listed = {
                item.job.url: item
                for item in catalog.list_jobs(CatalogFilters(include_inactive=True))
            }
            self.assertEqual(listed["https://example.com/1"].job.salary_max, 3000)
            self.assertEqual(listed["https://example.com/1"].first_seen, "2026-10-10 10:01:00")
            self.assertFalse(listed["https://example.com/1"].job.is_new)
            self.assertFalse(listed["https://example.com/2"].active)
            self.assertTrue(listed["https://example.com/3"].job.is_new)
            self.assertNotIn("https://example.com/dou", listed)

            active = catalog.list_jobs(CatalogFilters(text="qa"))
            self.assertEqual([item.job.title for item in active], ["QA Engineer"])
            self.assertEqual(catalog.counts(), (2, 1))

            extra = _job(url="https://example.com/4", job_id="4", title="Data Engineer")
            partial = SourceStatus(
                "Djinni", True, "наступні сторінки не відкрились", fetched=1, kept=1, complete=False
            )
            catalog.merge([extra], [partial], "2026-10-10 18:00:00", "2026-10-10 18:01:00")
            again = {
                item.job.url: item
                for item in catalog.list_jobs(CatalogFilters(include_inactive=True))
            }
            self.assertTrue(again["https://example.com/1"].active)
            self.assertTrue(again["https://example.com/4"].active)
            self.assertFalse(again["https://example.com/2"].active)

    def test_catalog_page_lists_a_stored_job(self):
        page = render_catalog(
            CatalogView(
                items=[], total=0, page=1, per_page=50, filters=CatalogFilters(), running=True
            )
        )
        self.assertIn("Каталог ще порожній", page)
        self.assertIn('data-refreshing="1"', page)
        self.assertNotIn("http-equiv", page)

    def test_fastapi_lists_jobs_and_filters_them(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = Catalog(Path(folder) / "catalog.sqlite")
            catalog.merge(
                [
                    _job(title="Python Developer"),
                    _job(
                        url="https://example.com/2", job_id="2", title="Go Engineer", category="Go"
                    ),
                ],
                [SourceStatus("Djinni", True, "ok", fetched=2, kept=2)],
                "2026-10-10 10:00:00",
                "2026-10-10 10:01:00",
            )
            service = CatalogService(catalog, interval_hours=24, pages=1)
            service.running = True
            client = TestClient(
                create_app(catalog, service, start_scheduler=False), base_url="http://127.0.0.1"
            )
            page = client.get("/")
            self.assertEqual(page.status_code, 200)
            self.assertIn("Python Developer", page.text)
            self.assertIn("Go Engineer", page.text)
            listed = client.get("/api/jobs", params={"q": "python"}).json()
            self.assertEqual([item["title"] for item in listed], ["Python Developer"])
            refresh = client.post("/refresh", follow_redirects=False)
            self.assertEqual(refresh.status_code, 303)
            self.assertEqual(refresh.headers["location"], "/")


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


if __name__ == "__main__":
    unittest.main()
