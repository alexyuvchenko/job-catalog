"""DOU company reviews: parsing, catalog storage, and the company dialog."""

from unittest.mock import patch

from fastapi.testclient import TestClient
from tests.support import sign_in

from core.models import CompanyReview, Job, SourceStatus
from jobs.refresh import CatalogService
from network.client import FetchError
from sources.reviews import fetch_company_review, match_slug, parse_reviews_page, slug_from_url
from storage.catalog import Catalog
from storage.filters import CatalogFilters
from storage.group import company_key
from storage.records import StoredJob
from storage.sqlite import connect
from web.app import create_app
from web.frontend.catalog_rows import render_row
from web.frontend.i18n import translator

_SEARCH = """
<ul>
<li class="l-company"><a class="cn-a" href="https://jobs.dou.ua/companies/macpaw/">MacPaw</a></li>
<li class="l-company"><a class="cn-a" href="https://jobs.dou.ua/companies/svitla-systems-inc/">Svitla Systems, Inc.</a></li>
<li class="l-company"><a class="cn-a" href="https://jobs.dou.ua/companies/other/">Other</a>
  <a href="https://jobs.dou.ua/companies/not-a-card/reviews/">Відгуки</a></li>
</ul>
"""

_REVIEWS = """
<h3 id="lblCommentsCount">40 відгуків</h3>
<h3 class="g-h3">Оцінка компанії: 82/100</h3>
<div class="ps">Проголосувало <a href="https://jobs.dou.ua/companies/macpaw/poll/">45 співробітників</a></div>
"""

_REVIEWS_ONLY = '<h3 id="lblCommentsCount">3 відгуки</h3>'


class _Client:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.urls: list[str] = []

    def get_text(self, url: str, referer: str | None = None) -> str:
        self.urls.append(url)
        if url not in self.pages:
            raise FetchError(f"missing {url}")
        return self.pages[url]


def test_slug_and_name_matching():
    assert slug_from_url("https://jobs.dou.ua/companies/macpaw/vacancies/") == "macpaw"
    assert slug_from_url("https://macpaw.com") == ""
    assert match_slug(_SEARCH, "MacPaw") == "macpaw"
    assert match_slug(_SEARCH, "Svitla Systems") == "svitla-systems-inc"
    assert match_slug(_SEARCH, "Nobody") is None
    assert match_slug(_SEARCH + _SEARCH, "MacPaw") == "macpaw"


def test_two_titles_that_fold_together_are_not_used():
    html = """
    <li class="l-company"><a class="cn-a" href="https://jobs.dou.ua/companies/one/">Acme Inc</a></li>
    <li class="l-company"><a class="cn-a" href="https://jobs.dou.ua/companies/two/">Acme</a></li>
    """
    assert match_slug(html, "Acme") is None


def test_reviews_page_keeps_the_survey_score_and_links():
    review = parse_reviews_page(_REVIEWS, "macpaw")
    assert review == CompanyReview(
        rating=82,
        review_count=40,
        voter_count=45,
        reviews_url="https://jobs.dou.ua/companies/macpaw/reviews/",
        poll_url="https://jobs.dou.ua/companies/macpaw/poll/",
        profile_url="https://jobs.dou.ua/companies/macpaw/",
    )
    comments = parse_reviews_page(_REVIEWS_ONLY, "macpaw")
    assert comments is not None
    assert comments.rating is None
    assert comments.review_count == 3
    assert comments.reviews_url.endswith("/reviews/")
    assert comments.poll_url == ""
    assert parse_reviews_page("<html></html>", "macpaw") is None


def test_known_company_url_skips_the_name_search():
    client = _Client(
        {"https://jobs.dou.ua/companies/macpaw/reviews/": _REVIEWS},
    )
    review = fetch_company_review(
        client, "Whatever", "https://jobs.dou.ua/companies/macpaw/vacancies/"
    )
    assert review is not None and review.rating == 82
    assert client.urls == ["https://jobs.dou.ua/companies/macpaw/reviews/"]


def test_name_search_uses_the_one_matching_card():
    client = _Client(
        {
            "https://jobs.dou.ua/companies/?name=MacPaw": _SEARCH,
            "https://jobs.dou.ua/companies/macpaw/reviews/": _REVIEWS,
        }
    )
    review = fetch_company_review(client, "MacPaw", "")
    assert review is not None and review.review_count == 40
    assert client.urls[0].endswith("name=MacPaw")


def test_catalog_shows_a_saved_score_and_keeps_it_when_a_later_read_fails(tmp_path):
    catalog = Catalog(tmp_path / "catalog.sqlite")
    _merge(catalog, company="MacPaw", company_url="https://jobs.dou.ua/companies/macpaw/vacancies/")
    review = parse_reviews_page(_REVIEWS, "macpaw")
    assert review is not None
    key = company_key("MacPaw")
    catalog.save_company_review(key, "MacPaw", review, "found")
    assert catalog.companies_due() == []
    listed = catalog.list_jobs(CatalogFilters())
    assert listed[0].review == review

    catalog.save_company_review(key, "MacPaw", None, "error")
    assert catalog.list_jobs(CatalogFilters())[0].review == review
    assert catalog.companies_due() == []

    connection = connect(catalog.path)
    connection.execute(
        "UPDATE company_reviews SET checked_at = ? WHERE company_key = ?",
        ("2020-01-01 00:00:00", key),
    )
    connection.commit()
    connection.close()
    due = catalog.companies_due()
    assert [item.name for item in due] == ["MacPaw"]
    assert due[0].dou_url.endswith("/vacancies/")


def test_score_band_follows_the_survey_number():
    t = translator("uk")

    def cell(rating: int) -> str:
        review = CompanyReview(
            rating=rating,
            review_count=1,
            voter_count=0,
            reviews_url="https://jobs.dou.ua/companies/macpaw/reviews/",
            poll_url="",
            profile_url="https://jobs.dou.ua/companies/macpaw/",
        )
        item = StoredJob(job=_job(), active=True, first_seen="", last_seen="", review=review)
        return render_row(item, t)

    assert "crate-good" in cell(70)
    assert "crate-mid" in cell(50)
    assert "crate-low" in cell(49)


def test_a_closed_company_is_not_looked_up_again(tmp_path):
    catalog = Catalog(tmp_path / "catalog.sqlite")
    _merge(catalog, company="Gone")
    catalog.merge(
        [_job(company="Other", url="https://example.com/2", job_id="2")],
        [SourceStatus("Djinni", True, "ok", fetched=1, kept=1)],
        "2026-10-11 10:00:00",
        "2026-10-11 10:01:00",
    )
    assert [item.name for item in catalog.companies_due()] == ["Other"]


def test_refresh_saves_reviews_and_a_failed_lookup_does_not_drop_the_vacancy(tmp_path):
    catalog = Catalog(tmp_path / "catalog.sqlite")
    service = CatalogService(catalog, interval_hours=24, pages=1)
    status = SourceStatus("Djinni", True, "ok", fetched=1, kept=1)
    review = parse_reviews_page(_REVIEWS, "macpaw")
    job = _job(company="MacPaw")
    with (
        patch("jobs.refresh.run_search", return_value=([job], [status])),
        patch("jobs.refresh.write_outputs"),
        patch("jobs.reviews.fetch_company_review", return_value=review) as fetch,
    ):
        stats = service.refresh()
        again = service.refresh()
    assert stats is not None and stats.added == 1
    assert again is not None
    assert fetch.call_count == 1
    assert catalog.list_jobs(CatalogFilters())[0].review == review

    connection = connect(catalog.path)
    connection.execute("UPDATE company_reviews SET checked_at = ?", ("2020-01-01 00:00:00",))
    connection.commit()
    connection.close()
    with (
        patch("jobs.refresh.run_search", return_value=([job], [status])),
        patch("jobs.refresh.write_outputs"),
        patch("jobs.reviews.fetch_company_review", side_effect=FetchError("down")),
    ):
        failed = service.refresh()
    assert failed is not None and failed.added == 0
    assert catalog.counts() == (1, 0)
    assert catalog.list_jobs(CatalogFilters())[0].review == review


def test_company_name_opens_a_dialog_with_the_score_and_links(tmp_path):
    catalog = Catalog(tmp_path / "catalog.sqlite")
    _merge(catalog, company="MacPaw")
    review = parse_reviews_page(_REVIEWS, "macpaw")
    catalog.save_company_review(company_key("MacPaw"), "MacPaw", review, "found")
    service = CatalogService(catalog, interval_hours=24, pages=1)
    client = TestClient(
        create_app(catalog, service, start_scheduler=False), base_url="http://127.0.0.1"
    )
    sign_in(client, catalog)
    page = client.get("/")
    assert page.status_code == 200
    assert 'class="company-open"' in page.text
    assert 'class="crate crate-good"' in page.text
    assert ">82</span>" in page.text
    assert "https://jobs.dou.ua/companies/macpaw/reviews/" in page.text
    assert "https://jobs.dou.ua/companies/macpaw/poll/" in page.text
    assert 'id="company-reviews"' in page.text
    assert "Відгуки на DOU" in page.text
    english = client.get("/", params={"lang": "en"})
    assert "Reviews on DOU" in english.text
    assert "out of 100" in english.text
    payload = client.get("/api/jobs").json()
    assert payload[0]["company_review"]["rating"] == 82
    assert payload[0]["company_review"]["review_count"] == 40
    plain = Catalog(tmp_path / "other.sqlite")
    _merge(plain, company="Quiet")
    quiet = TestClient(
        create_app(plain, CatalogService(plain, interval_hours=24, pages=1), start_scheduler=False),
        base_url="http://127.0.0.1",
    )
    sign_in(quiet, plain, username="bea")
    assert 'class="company-open"' not in quiet.get("/").text
    assert quiet.get("/api/jobs").json()[0]["company_review"] is None


def _merge(catalog: Catalog, company: str = "Example", company_url: str = "") -> None:
    incoming = [_job(company=company, company_url=company_url)]
    status = SourceStatus("Djinni", True, "ok", fetched=1, kept=1)
    catalog.merge(incoming, [status], "2026-10-10 10:00:00", "2026-10-10 10:01:00")


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
