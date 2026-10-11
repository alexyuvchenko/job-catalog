"""The list a signed-in person is looking at, ready for the catalog page."""

from __future__ import annotations

from jobs.refresh import CatalogService
from storage.catalog import Catalog
from storage.filters import CatalogFilters
from web.frontend.pages import CatalogView


def catalog_view(
    catalog: Catalog,
    service: CatalogService,
    filters: CatalogFilters,
    page: int,
    per_page: int,
    *,
    user_id: int | None = None,
    clamp: bool = True,
) -> CatalogView:
    stored = catalog.list_jobs(filters, user_id)
    if clamp:
        page = min(page, max(1, -(-len(stored) // per_page)))
    active_count, inactive_count = catalog.counts()
    statuses, finished, added, updated, deactivated = catalog.latest_statuses()
    return CatalogView(
        items=stored[(page - 1) * per_page : page * per_page],
        total=len(stored),
        page=page,
        per_page=per_page,
        filters=filters,
        statuses=statuses,
        active_count=active_count,
        inactive_count=inactive_count,
        user_count=catalog.user_count(),
        new_count=sum(1 for item in stored if item.active and item.change == "added"),
        running=service.running,
        last_finished=finished,
        next_run=service.next_run,
        added=added,
        updated=updated,
        deactivated=deactivated,
        error=service.last_error,
    )
