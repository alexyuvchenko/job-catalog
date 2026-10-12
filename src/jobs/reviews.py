"""Look up DOU company reviews for the companies already in the catalog."""

from __future__ import annotations

import logging
from collections.abc import Callable

from network.client import Client, FetchError
from sources.reviews import fetch_company_review
from storage.catalog import Catalog

log = logging.getLogger("jobsearch")


def update_company_reviews(
    catalog: Catalog,
    client: Client | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    """Save a DOU score and review links for each active company that is due.

    A company that fails to load keeps the score it already had. One failure
    does not stop the rest.
    """
    if cancelled is not None and cancelled():
        log.info("company reviews skipped because the refresh is stopping")
        return
    due = catalog.companies_due()
    if not due:
        return
    client = client or Client()
    found = missing = failed = 0
    for target in due:
        if cancelled is not None and cancelled():
            log.info("company reviews stopped")
            break
        try:
            review = fetch_company_review(client, target.name, target.dou_url)
        except FetchError as exc:
            log.warning("company review failed for %s: %s", target.name, exc)
            catalog.save_company_review(target.key, target.name, None, "error")
            failed += 1
            continue
        if review is None:
            catalog.save_company_review(target.key, target.name, None, "missing")
            missing += 1
        else:
            catalog.save_company_review(target.key, target.name, review, "found")
            found += 1
    log.info(
        "company reviews checked %s, found %s, not listed %s, failed %s",
        found + missing + failed,
        found,
        missing,
        failed,
    )
