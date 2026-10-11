from fastapi.testclient import TestClient
from tests.support import sign_in

from core.models import Job, SourceStatus
from jobs.refresh import CatalogService
from storage.catalog import Catalog
from storage.filters import CatalogFilters
from web.app import create_app
from web.catalog.dependencies import read_filters
from web.frontend.pages import CatalogView, render_catalog


class TestCatalog:
    def test_sorting_by_column_and_direction(self, tmp_path):
        catalog = Catalog(tmp_path / "catalog.sqlite")
        jobs = [
            _job(url="https://example.com/1", job_id="1", title="b", company="Zeta"),
            _job(url="https://example.com/2", job_id="2", title="A", company="alpha"),
        ]
        status = SourceStatus("Djinni", True, "ok", fetched=2, kept=2)
        catalog.merge(jobs, [status], "2026-10-10 10:00:00", "2026-10-10 10:01:00")

        def titles(**kwargs):
            return [s.job.title for s in catalog.list_jobs(CatalogFilters(**kwargs))]

        assert titles(sort="job") == ["A", "b"]
        assert titles(sort="job", descending=True) == ["b", "A"]
        assert titles(sort="company") == ["A", "b"]
        assert titles(sort="company", descending=True) == ["b", "A"]

    def test_date_sort_direction_blanks_and_ukrainian_names(self, tmp_path):
        catalog = Catalog(tmp_path / "catalog.sqlite")
        jobs = [
            _job(url="https://example.com/1", job_id="1", title="Old", published="2026-10-01"),
            _job(
                url="https://example.com/2",
                job_id="2",
                title="New",
                company="Ялина",
                published="2026-10-09",
                salary_max=1000,
            ),
            _job(
                url="https://example.com/3",
                job_id="3",
                title="New",
                company="Ідея",
                published="2026-10-09",
                salary_max=5000,
            ),
            _job(url="https://example.com/4", job_id="4", title="Undated", published=""),
        ]
        catalog.merge(
            jobs,
            [SourceStatus("Djinni", True, "ok", fetched=4, kept=4)],
            "2026-10-10 10:00:00",
            "2026-10-10 10:01:00",
        )

        def titles(**kwargs):
            return [item.job.title for item in catalog.list_jobs(CatalogFilters(**kwargs))]

        def companies(**kwargs):
            return [item.job.company for item in catalog.list_jobs(CatalogFilters(**kwargs))]

        # Same day keeps the query order: higher salary first. A blank date stays last.
        assert companies() == ["Ідея", "Ялина", "Example", "Example"]
        assert titles(sort="date", descending=False) == ["Old", "New", "New", "Undated"]
        assert companies(sort="", descending=False) == ["Example", "Ідея", "Ялина", "Example"]
        # Equal titles keep the newer-first order the query already produced.
        assert companies(sort="job") == ["Ідея", "Ялина", "Example", "Example"]
        # "і" sorts before "я", and a Latin name sorts before either.
        assert companies(sort="company") == ["Example", "Example", "Ідея", "Ялина"]

    def test_sort_headers_follow_the_active_column(self):
        page = render_catalog(
            CatalogView(
                items=[], total=0, page=1, per_page=50, filters=CatalogFilters(), language="en"
            )
        )
        assert page.count('aria-sort="descending"') == 1
        assert "sort=date&amp;dir=asc" in page
        assert "sort=company&amp;dir=asc" in page
        assert 'aria-sort="ascending"' not in page

        company = render_catalog(
            CatalogView(
                items=[],
                total=0,
                page=1,
                per_page=50,
                filters=CatalogFilters(sort="company", descending=False),
                language="en",
            )
        )
        assert company.count('aria-sort="ascending"') == 1
        assert 'aria-sort="descending"' not in company
        assert "sort=company&amp;dir=desc" in company
        assert 'name="sort" value="company"' in company
        assert 'name="dir" value="asc"' in company

    def test_sort_query_is_normalized(self):
        chosen = read_filters(sort=" JOB ", dir="DESC")
        assert (chosen.sort, chosen.descending) == ("job", True)
        omitted = read_filters(dir="asc")
        assert (omitted.sort, omitted.descending) == ("", False)
        unknown = read_filters(sort="salary", dir="sideways")
        assert (unknown.sort, unknown.descending) == ("", None)

    def test_merge_updates_keeps_failures_and_marks_only_new_rows(self, tmp_path):
        catalog = Catalog(tmp_path / "catalog.sqlite")
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
            item.job.url: item for item in catalog.list_jobs(CatalogFilters(include_inactive=True))
        }
        assert listed["https://example.com/1"].job.salary_max == 3000
        assert listed["https://example.com/1"].first_seen == "2026-10-10 10:01:00"
        assert not (listed["https://example.com/1"].job.is_new)
        assert not (listed["https://example.com/2"].active)
        assert listed["https://example.com/3"].job.is_new
        assert "https://example.com/dou" not in listed

        active = catalog.list_jobs(CatalogFilters(text="qa"))
        assert [item.job.title for item in active] == ["QA Engineer"]
        assert catalog.counts() == (2, 1)

        extra = _job(url="https://example.com/4", job_id="4", title="Data Engineer")
        partial = SourceStatus(
            "Djinni", True, "наступні сторінки не відкрились", fetched=1, kept=1, complete=False
        )
        catalog.merge([extra], [partial], "2026-10-10 18:00:00", "2026-10-10 18:01:00")
        again = {
            item.job.url: item for item in catalog.list_jobs(CatalogFilters(include_inactive=True))
        }
        assert again["https://example.com/1"].active
        assert again["https://example.com/4"].active
        assert not (again["https://example.com/2"].active)

    def test_catalog_page_lists_a_stored_job(self):
        page = render_catalog(
            CatalogView(
                items=[], total=0, page=1, per_page=50, filters=CatalogFilters(), running=True
            )
        )
        assert "Каталог ще порожній" in page
        assert 'data-refreshing="1"' in page
        assert "http-equiv" not in page

    def test_fastapi_lists_jobs_and_filters_them(self, tmp_path):
        catalog = Catalog(tmp_path / "catalog.sqlite")
        catalog.merge(
            [
                _job(title="Python Developer"),
                _job(url="https://example.com/2", job_id="2", title="Go Engineer", category="Go"),
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
        sign_in(client, catalog)
        page = client.get("/")
        assert page.status_code == 200
        assert "Python Developer" in page.text
        assert "Go Engineer" in page.text
        listed = client.get("/api/jobs", params={"q": "python"}).json()
        assert [item["title"] for item in listed] == ["Python Developer"]
        refresh = client.post("/refresh", follow_redirects=False)
        assert refresh.status_code == 303
        assert refresh.headers["location"] == "/"


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
