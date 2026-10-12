"""Look up DOU and Indeed company reviews for the companies already in the catalog."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from core.models import CompanyReview, ReviewSource
from network.browser import Browser, BrowserError
from network.client import Client, FetchError
from sources.indeed import fetch_indeed_review
from sources.reviews import fetch_company_review
from storage.catalog import Catalog

log = logging.getLogger("jobsearch")

# A short pause between Indeed pages. DOU already pauses inside the HTTP client.
_INDEED_PAUSE = 0.6


def update_company_reviews(
    catalog: Catalog,
    client: Client | None = None,
    cancelled: Callable[[], bool] | None = None,
    interactive: bool = False,
) -> None:
    """Save DOU and Indeed scores for each active company that is due.

    A source that fails to load keeps the score it already had. One failure
    does not stop the rest, and a review failure does not change the vacancies.
    """
    if cancelled is not None and cancelled():
        log.info("company reviews skipped because the refresh is stopping")
        return
    due = catalog.companies_due()
    if not due:
        return
    client = client or Client()
    browser = _open_browser(interactive, cancelled)
    found = missing = failed = indeed_found = 0
    indeed_index = 0
    try:
        for target in due:
            if cancelled is not None and cancelled():
                log.info("company reviews stopped")
                break
            previous = catalog.saved_company_review(target.key)
            dou, dou_failed = _dou(client, target.name, target.dou_url)
            indeed, indeed_failed, indeed_blocked = _indeed(browser, target.name, indeed_index)
            if indeed_blocked and browser is not None:
                log.warning(
                    "Indeed asked to verify you are human; later companies skip Indeed this refresh"
                )
                browser.close()
                browser = None
            elif browser is not None:
                indeed_index += 1
            review, status = combine_reviews(previous, dou, dou_failed, indeed, indeed_failed)
            if status == "error":
                log.warning("company review failed for %s", target.name)
                failed += 1
            elif status == "missing":
                missing += 1
            else:
                found += 1
                if any(source.source == "Indeed" for source in review.sources):
                    indeed_found += 1
            catalog.save_company_review(target.key, target.name, review, status)
    finally:
        if browser is not None:
            browser.close()
    log.info(
        "company reviews checked %s, found %s, not listed %s, failed %s, indeed %s",
        found + missing + failed,
        found,
        missing,
        failed,
        indeed_found,
    )


def combine_reviews(
    previous: CompanyReview | None,
    dou: CompanyReview | None,
    dou_failed: bool,
    indeed: ReviewSource | None,
    indeed_failed: bool,
) -> tuple[CompanyReview | None, str]:
    """The merged score, and whether the read is complete, partial, missing, or failed.

    A failed source keeps the previous copy of that source. ``error`` means
    nothing new was read and the caller should leave the saved row alone.
    """
    dou_source = _named(previous, "DOU") if dou_failed else _named(dou, "DOU")
    indeed_source = _named(previous, "Indeed") if indeed_failed else indeed
    sources = tuple(source for source in (dou_source, indeed_source) if source is not None)
    if dou_failed and indeed_failed:
        return None, "error"
    if not sources:
        return None, "missing"
    profile = ""
    if dou_source is not None and not dou_failed and dou is not None:
        profile = dou.profile_url
    elif dou_failed and previous is not None:
        profile = previous.profile_url
    scores = [source.rating for source in sources if source.rating is not None]
    rating = round(sum(scores) / len(scores)) if scores else None
    review = CompanyReview(
        rating=rating,
        review_count=sum(source.review_count for source in sources),
        voter_count=dou_source.voter_count if dou_source is not None else 0,
        reviews_url=dou_source.reviews_url if dou_source is not None else "",
        poll_url=dou_source.poll_url if dou_source is not None else "",
        profile_url=profile,
        sources=sources,
    )
    if dou_failed or indeed_failed:
        return review, "partial"
    return review, "found"


def _dou(client: Client, name: str, dou_url: str) -> tuple[CompanyReview | None, bool]:
    try:
        return fetch_company_review(client, name, dou_url), False
    except FetchError as exc:
        log.warning("DOU review failed for %s: %s", name, exc)
        return None, True


def _indeed(
    browser: Browser | None, name: str, index: int
) -> tuple[ReviewSource | None, bool, bool]:
    if browser is None:
        return None, True, False
    if index:
        time.sleep(_INDEED_PAUSE)
    try:
        return fetch_indeed_review(browser, name), False, False
    except FetchError as exc:
        log.warning("Indeed review failed for %s: %s", name, exc)
        return None, True, _human_check(exc)


def _human_check(exc: FetchError) -> bool:
    return "verify you are human" in str(exc).lower()


def _named(review: CompanyReview | None, source: str) -> ReviewSource | None:
    if review is None:
        return None
    for item in review.sources:
        if item.source == source:
            return item
    return None


def _open_browser(interactive: bool, cancelled: Callable[[], bool] | None) -> Browser | None:
    try:
        browser = Browser(interactive=interactive).__enter__()
    except BrowserError as exc:
        log.warning("Indeed reviews skipped because Chrome did not start: %s", exc)
        return None
    browser.cancelled = cancelled
    return browser
