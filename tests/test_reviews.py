"""DOU and Indeed company reviews: parsing, catalog storage, and the company dialog."""

import json
from unittest.mock import patch

from fastapi.testclient import TestClient
from tests.support import sign_in

from core.models import CompanyReview, Job, ReviewSource, SourceStatus
from jobs.refresh import CatalogService
from jobs.reviews import combine_reviews, update_company_reviews
from network.client import FetchError
from sources.indeed import parse_indeed_search
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

MACPAW = [
    {
        "name": "MacPaw",
        "rating": 4.5,
        "reviewsCount": 2,
        "reviewsUrl": "/cmp/Macpaw/reviews",
        "sectors": ["Інформаційні технології"],
    }
]
SOFTSERVE = [
    {
        "name": "SoftServe",
        "rating": 4.1,
        "reviewsCount": 88,
        "reviewsUrl": "/cmp/Softserve/reviews",
        "sectors": ["Інформаційні технології"],
    },
    {
        "name": "SoftServe",
        "rating": 5,
        "reviewsCount": 1,
        "reviewsUrl": "/cmp/Softserve-5/reviews",
        "sectors": ["Освіта"],
    },
]


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
        sources=(
            ReviewSource(
                source="DOU",
                rating=82,
                score="82/100",
                review_count=40,
                voter_count=45,
                reviews_url="https://jobs.dou.ua/companies/macpaw/reviews/",
                poll_url="https://jobs.dou.ua/companies/macpaw/poll/",
            ),
        ),
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
        patch("jobs.reviews._open_browser", return_value=None),
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
        patch("jobs.reviews._open_browser", return_value=None),
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


def test_indeed_human_check_skips_later_companies(tmp_path):
    catalog = Catalog(tmp_path / "catalog.sqlite")
    catalog.merge(
        [
            _job(company="MacPaw"),
            _job(company="Other", url="https://example.com/2", job_id="2"),
        ],
        [SourceStatus("Djinni", True, "ok", fetched=2, kept=2)],
        "2026-10-10 10:00:00",
        "2026-10-10 10:01:00",
    )
    names: list[str] = []

    def fake_indeed(_browser, name: str):
        names.append(name)
        raise FetchError("the page is asking to verify you are human")

    class DummyBrowser:
        closed = False

        def close(self) -> None:
            self.closed = True

    browser = DummyBrowser()
    with (
        patch("jobs.reviews.fetch_company_review", return_value=None),
        patch("jobs.reviews.fetch_indeed_review", side_effect=fake_indeed),
        patch("jobs.reviews._open_browser", return_value=browser),
    ):
        update_company_reviews(catalog)
    assert names == ["MacPaw"]
    assert browser.closed


def test_indeed_uses_one_name_match_and_prefers_the_it_company_when_names_repeat():
    macpaw = parse_indeed_search(_indeed(MACPAW), "MacPaw")
    assert macpaw == ReviewSource(
        source="Indeed",
        rating=90,
        score="4.5/5",
        review_count=2,
        voter_count=0,
        reviews_url="https://ua.indeed.com/cmp/Macpaw/reviews",
    )
    softserve = parse_indeed_search(_indeed(SOFTSERVE), "SoftServe")
    assert softserve is not None
    assert softserve.reviews_url.endswith("/cmp/Softserve/reviews")
    assert softserve.rating == 82
    assert parse_indeed_search(_indeed(SOFTSERVE), "Nobody") is None
    both_it = [dict(row, sectors=["Інформаційні технології"]) for row in SOFTSERVE]
    assert parse_indeed_search(_indeed(both_it), "SoftServe") is None


def test_indeed_without_search_results_is_a_failed_read():
    try:
        parse_indeed_search("<html></html>", "MacPaw")
    except FetchError:
        return
    raise AssertionError("a page without Indeed results should fail the read")


def test_a_failed_source_keeps_its_previous_score_and_the_other_source_is_averaged():
    dou = parse_reviews_page(_REVIEWS, "macpaw")
    assert dou is not None
    indeed = ReviewSource(
        source="Indeed",
        rating=90,
        score="4.5/5",
        review_count=2,
        voter_count=0,
        reviews_url="https://ua.indeed.com/cmp/Macpaw/reviews",
    )
    merged, status = combine_reviews(None, dou, False, indeed, False)
    assert status == "found"
    assert merged is not None and merged.rating == 86
    assert [source.source for source in merged.sources] == ["DOU", "Indeed"]

    kept_indeed, indeed_down = combine_reviews(merged, dou, False, None, True)
    assert indeed_down == "partial"
    assert kept_indeed is not None and kept_indeed.rating == 86
    assert [source.source for source in kept_indeed.sources] == ["DOU", "Indeed"]

    kept, partial = combine_reviews(merged, None, True, None, False)
    assert partial == "partial"
    assert kept is not None
    assert [source.source for source in kept.sources] == ["DOU"]
    assert kept.rating == 82
    assert kept.profile_url.endswith("/macpaw/")

    unchanged, failed = combine_reviews(kept, None, True, None, True)
    assert failed == "error" and unchanged is None


def test_dialog_lists_indeed_beside_dou_and_drops_an_unsafe_link(tmp_path):
    catalog = Catalog(tmp_path / "catalog.sqlite")
    _merge(catalog, company="MacPaw")
    dou = parse_reviews_page(_REVIEWS, "macpaw")
    indeed = ReviewSource(
        source="Indeed",
        rating=90,
        score="4.5/5",
        review_count=2,
        voter_count=0,
        reviews_url="https://ua.indeed.com/cmp/Macpaw/reviews",
    )
    merged, status = combine_reviews(None, dou, False, indeed, False)
    assert merged is not None
    catalog.save_company_review(company_key("MacPaw"), "MacPaw", merged, status)
    listed = catalog.list_jobs(CatalogFilters())[0]
    assert listed.review is not None and listed.review.rating == 86
    page = render_row(listed, translator("en"))
    assert "crate-good" in page
    assert ">86</span>" in page
    assert "https://ua.indeed.com/cmp/Macpaw/reviews" in page
    assert "Reviews on Indeed" in page
    assert "Average employee score" in page
    unsafe = ReviewSource(
        source="Indeed",
        rating=90,
        score="4.5/5",
        review_count=1,
        voter_count=0,
        reviews_url="https://evil.example/cmp/Macpaw/reviews",
    )
    poisoned = CompanyReview(
        rating=90,
        review_count=1,
        voter_count=0,
        reviews_url="",
        poll_url="",
        profile_url="",
        sources=(unsafe,),
    )
    cell = render_row(
        StoredJob(job=_job(), active=True, first_seen="", last_seen="", review=poisoned),
        translator("en"),
    )
    assert "evil.example" not in cell
    assert "company-open" not in cell


def test_an_older_dou_row_still_shows_after_the_sources_column_is_added(tmp_path):
    catalog = Catalog(tmp_path / "catalog.sqlite")
    _merge(catalog, company="MacPaw")
    review = parse_reviews_page(_REVIEWS, "macpaw")
    key = company_key("MacPaw")
    catalog.save_company_review(key, "MacPaw", review, "found")
    connection = connect(catalog.path)
    connection.execute("UPDATE company_reviews SET sources_json = '' WHERE company_key = ?", (key,))
    connection.commit()
    connection.close()
    listed = catalog.list_jobs(CatalogFilters())[0].review
    assert listed is not None
    assert listed.sources[0].source == "DOU"
    assert listed.sources[0].score == "82/100"


def test_a_partial_read_is_tried_again_the_next_day(tmp_path):
    catalog = Catalog(tmp_path / "catalog.sqlite")
    _merge(catalog, company="MacPaw")
    review = parse_reviews_page(_REVIEWS, "macpaw")
    key = company_key("MacPaw")
    catalog.save_company_review(key, "MacPaw", review, "partial")
    assert catalog.companies_due() == []
    connection = connect(catalog.path)
    connection.execute(
        "UPDATE company_reviews SET checked_at = ? WHERE company_key = ?",
        ("2026-10-11 00:00:00", key),
    )
    connection.commit()
    connection.close()
    assert [item.name for item in catalog.companies_due()] == ["MacPaw"]


def _indeed(results: list[dict]) -> str:
    payload = json.dumps({"searchResults": results}, ensure_ascii=False)
    return f'<script id="comp-initialData" type="application/json">{payload}</script>'


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
