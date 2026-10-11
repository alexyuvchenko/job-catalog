"""Query parsing for the catalog page and the jobs API."""

from __future__ import annotations

import json
from collections.abc import Mapping

from fastapi import Request

from core.constants import ENGLISH_LEVELS, SOURCE_NAMES
from storage.catalog import Catalog
from storage.filters import (
    CHANGE_CHOICES,
    LANGUAGE_CHOICES,
    MAX_RATING,
    MINE_CHOICES,
    SORT_CHOICES,
    CatalogFilters,
)
from web.auth.service import User
from web.frontend.pages import DEFAULT_PER_PAGE, PER_PAGE_CHOICES, filter_params

_SOURCES = {"", *SOURCE_NAMES}
_ENGLISH = {"", *ENGLISH_LEVELS}
FILTER_KEYS = frozenset(
    {
        "q",
        "source",
        "mine",
        "min_rating",
        "change",
        "language",
        "min_salary",
        "english",
        "min_years",
        "full_remote_only",
        "include_inactive",
        "per_page",
        "sort",
        "dir",
    }
)


def read_filters(
    q: str = "",
    source: str = "",
    min_salary: str = "",
    english: str = "",
    min_years: str = "",
    full_remote_only: str = "",
    include_inactive: str = "",
    mine: str = "",
    min_rating: str = "",
    change: str = "",
    language: str = "",
    sort: str = "",
    dir: str = "",
) -> CatalogFilters:
    level = english.strip().upper()
    chosen = source.strip()
    rating = _int(min_rating)
    column = sort.strip().lower()
    direction = dir.strip().lower()
    return CatalogFilters(
        text=q.strip()[:80],
        source=chosen if chosen in _SOURCES else "",
        full_remote_only=full_remote_only == "1",
        min_salary=_int(min_salary),
        english=level if level in _ENGLISH else "",
        min_years=_float(min_years),
        include_inactive=include_inactive == "1",
        mine=mine if mine in MINE_CHOICES else "",
        min_rating=rating if rating is not None and 1 <= rating <= MAX_RATING else None,
        change=change if change in CHANGE_CHOICES else "",
        language=language if language in LANGUAGE_CHOICES else "",
        sort=column if column in SORT_CHOICES else "",
        descending={"asc": False, "desc": True}.get(direction),
    )


def read_paging(page: str = "", per_page: str = "") -> tuple[int, int]:
    size = _int(per_page)
    number = _int(page)
    return (
        number if number is not None and number >= 1 else 1,
        size if size in PER_PAGE_CHOICES else DEFAULT_PER_PAGE,
    )


def filters_from(params: Mapping[str, str]) -> CatalogFilters:
    def text(name: str) -> str:
        value = params.get(name, "")
        return value if isinstance(value, str) else ""

    return read_filters(
        q=text("q"),
        source=text("source"),
        min_salary=text("min_salary"),
        english=text("english"),
        min_years=text("min_years"),
        full_remote_only=text("full_remote_only"),
        include_inactive=text("include_inactive"),
        mine=text("mine"),
        min_rating=text("min_rating"),
        change=text("change"),
        language=text("language"),
        sort=text("sort"),
        dir=text("dir"),
    )


def encode_view(filters: CatalogFilters, per_page: int) -> str:
    return json.dumps(
        dict(filter_params(filters, per_page)), ensure_ascii=False, separators=(",", ":")
    )


def decode_view(raw: str) -> tuple[CatalogFilters, int]:
    if not raw:
        return CatalogFilters(), DEFAULT_PER_PAGE
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return CatalogFilters(), DEFAULT_PER_PAGE
    if not isinstance(data, dict):
        return CatalogFilters(), DEFAULT_PER_PAGE

    def text(name: str) -> str:
        value = data.get(name, "")
        return value if isinstance(value, str) else ""

    _page, per_page = read_paging(per_page=text("per_page"))
    return filters_from({name: text(name) for name in FILTER_KEYS}), per_page


def bound_view(request: Request, catalog: Catalog, user: User) -> tuple[CatalogFilters, int, int]:
    """Filters from the query, or the ones this account last applied."""
    params = request.query_params
    page, per_page = read_paging(params.get("page", ""), params.get("per_page", ""))
    if FILTER_KEYS & set(params):
        return filters_from(params), page, per_page
    filters, saved_per_page = decode_view(catalog.saved_filters(user.id))
    if "per_page" not in params:
        per_page = saved_per_page
    return filters, page, per_page


def _int(value: str) -> int | None:
    if not value.strip():
        return None
    try:
        number = int(value)
    except ValueError:
        return None
    if number < 0 or number > 100_000:
        return None
    return number


def _float(value: str) -> float | None:
    if not value.strip():
        return None
    try:
        number = float(value.replace(",", "."))
    except ValueError:
        return None
    if number < 0 or number > 40:
        return None
    return number
