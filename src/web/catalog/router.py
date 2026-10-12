"""The vacancy list, marks, and a refresh started from this computer."""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from core.models import CompanyReview, ReviewSource
from jobs.refresh import CatalogService
from storage.catalog import Catalog
from storage.filters import CatalogFilters
from web.auth.dependencies import ask_sign_in, signed_in
from web.catalog.dependencies import (
    FILTER_KEYS,
    bound_view,
    decode_view,
    encode_view,
    filters_from,
    read_paging,
)
from web.catalog.schemas import MarksUpdate
from web.catalog.view import catalog_view
from web.frontend import i18n
from web.frontend.assets.favicon import FAVICON_SVG
from web.frontend.catalog_rows import render_rows
from web.frontend.pages import filter_params, render_catalog
from web.language import page_language, stick_language
from web.security import PAGE_HEADERS, is_local_client, same_origin

log = logging.getLogger("jobsearch")

router = APIRouter()
_FAVICON_HEADERS = {"Cache-Control": "public, max-age=86400"}


def _can_refresh(request: Request) -> bool:
    # A refresh opens Chrome on this machine, so other devices only read.
    return not request.app.state.allow_lan or is_local_client(request)


def _catalog_location(filters: CatalogFilters, per_page: int, page: int, lang: str) -> str:
    params = filter_params(filters, per_page)
    if page > 1:
        params.append(("page", str(page)))
    if lang:
        params.append(("lang", lang))
    return "/" if not params else "/?" + urlencode(params)


def _current_location(request: Request) -> str:
    return "/" if not request.url.query else "/?" + request.url.query


@router.get("/favicon.svg")
@router.get("/favicon.ico")
def favicon() -> Response:
    return Response(FAVICON_SVG, media_type="image/svg+xml", headers=_FAVICON_HEADERS)


@router.get("/", response_class=HTMLResponse, response_model=None)
def home(request: Request):
    catalog: Catalog = request.app.state.catalog
    service: CatalogService = request.app.state.service
    user = signed_in(catalog, request)
    if user is None:
        return ask_sign_in(request)
    saved_lang = catalog.saved_language(user.id)
    language, explicit = page_language(request, saved_lang)
    if request.query_params.get("reset") == "1":
        catalog.save_filters(user.id, "")
        response = RedirectResponse("/", status_code=303)
        response.headers["Cache-Control"] = "no-store"
        stick_language(response, request, catalog, user, language, explicit)
        return response
    params = request.query_params
    page, query_per_page = read_paging(params.get("page", ""), params.get("per_page", ""))
    if FILTER_KEYS & set(params):
        filters = filters_from(params)
        per_page = query_per_page
        catalog.save_filters(user.id, encode_view(filters, per_page))
    else:
        filters, per_page = decode_view(catalog.saved_filters(user.id))
        page, _query_size = read_paging(params.get("page", ""), "")
        target = _catalog_location(filters, per_page, page, language if explicit else "")
        if target != _current_location(request) and filter_params(filters, per_page):
            response = RedirectResponse(target, status_code=303)
            response.headers["Cache-Control"] = "no-store"
            stick_language(response, request, catalog, user, language, explicit)
            return response
    view = catalog_view(catalog, service, filters, page, per_page, user_id=user.id)
    view.can_refresh = _can_refresh(request)
    view.language = language
    view.username = user.username
    response = HTMLResponse(render_catalog(view), headers=PAGE_HEADERS)
    stick_language(response, request, catalog, user, language, explicit)
    return response


@router.get("/fragments/rows", response_model=None)
def rows(request: Request) -> JSONResponse:
    """The next batch of table rows, for the "show more" button."""
    catalog: Catalog = request.app.state.catalog
    service: CatalogService = request.app.state.service
    user = signed_in(catalog, request)
    if user is None:
        return JSONResponse({"detail": "sign in"}, status_code=401)
    language, _explicit = page_language(request, catalog.saved_language(user.id))
    filters, page, per_page = bound_view(request, catalog, user)
    # A page past the end is empty, so a stale "show more" never repeats rows.
    view = catalog_view(catalog, service, filters, page, per_page, user_id=user.id, clamp=False)
    t = i18n.translator(language)
    left = view.total - view.page * view.per_page
    return JSONResponse(
        {
            "html": render_rows(view.items, t, actions=True),
            "last": view.last,
            "total": view.total,
            "next": view.page + 1 if left > 0 else None,
            "more_label": t("show_more", n=min(view.per_page, left)) if left > 0 else "",
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/jobs/state", response_model=None)
def set_state(request: Request, update: MarksUpdate):
    """Mark a vacancy: favorite, not for me, viewed, or a rating from 1 to 5."""
    catalog: Catalog = request.app.state.catalog
    user = signed_in(catalog, request)
    if user is None:
        return JSONResponse({"detail": "sign in"}, status_code=401)
    if not same_origin(request):
        return JSONResponse({"detail": "only accepted from this site"}, status_code=403)
    if not request.headers.get("content-type", "").startswith("application/json"):
        return JSONResponse({"detail": "send application/json"}, status_code=415)
    marks = catalog.set_marks(
        update.url,
        user.id,
        favorite=update.favorite,
        hidden=update.hidden,
        rating=update.rating,
        viewed=update.viewed,
    )
    if marks is None:
        return JSONResponse({"detail": "unknown vacancy"}, status_code=404)
    return {
        "favorite": marks.favorite,
        "hidden": marks.hidden,
        "rating": marks.rating,
        "viewed": marks.viewed,
    }


@router.get("/health", response_model=None)
@router.get("/api/status", response_model=None)
def health(request: Request):
    catalog: Catalog = request.app.state.catalog
    service: CatalogService = request.app.state.service
    try:
        active, inactive = catalog.counts()
        users = catalog.user_count()
        _statuses, finished, _added, _updated, _deactivated = catalog.latest_statuses()
    except Exception:
        log.exception("health check failed")
        return JSONResponse({"ok": False}, status_code=503)
    return {
        "ok": True,
        "running": service.running,
        "active": active,
        "inactive": inactive,
        "users": users,
        "last_finished": finished,
        "next_run": service.next_run,
        "last_error": service.last_error,
    }


@router.get("/api/jobs", response_model=None)
def jobs(request: Request):
    catalog: Catalog = request.app.state.catalog
    user = signed_in(catalog, request)
    if user is None:
        return JSONResponse({"detail": "sign in"}, status_code=401)
    filters, _page, _per_page = bound_view(request, catalog, user)
    return [
        item.job.as_dict()
        | {
            "active": item.active,
            "first_seen": item.first_seen,
            "last_seen": item.last_seen,
            "change": item.change,
            "changes": list(item.changes),
            "language": item.language,
            "favorite": item.marks.favorite,
            "hidden": item.marks.hidden,
            "rating": item.marks.rating,
            "viewed": item.marks.viewed,
            "listings": [{"source": source, "url": url} for source, url in item.listings],
            "company_review": _review_json(item.review),
        }
        for item in catalog.list_jobs(filters, user.id)
    ]


def _review_json(review: CompanyReview | None) -> dict | None:
    if review is None:
        return None
    return {
        "rating": review.rating,
        "review_count": review.review_count,
        "voter_count": review.voter_count,
        "reviews_url": review.reviews_url,
        "poll_url": review.poll_url,
        "profile_url": review.profile_url,
        "sources": [_source_json(source) for source in review.sources],
    }


def _source_json(source: ReviewSource) -> dict:
    return {
        "source": source.source,
        "rating": source.rating,
        "score": source.score,
        "review_count": source.review_count,
        "voter_count": source.voter_count,
        "reviews_url": source.reviews_url,
        "poll_url": source.poll_url,
    }


@router.post("/refresh", status_code=303, response_model=None)
def refresh(request: Request):
    catalog: Catalog = request.app.state.catalog
    service: CatalogService = request.app.state.service
    if not same_origin(request):
        return JSONResponse({"detail": "refresh is only accepted from this site"}, status_code=403)
    if signed_in(catalog, request) is None:
        return ask_sign_in(request)
    if not _can_refresh(request):
        return JSONResponse(
            {"detail": "refresh can only be started on the computer that runs the service"},
            status_code=403,
        )
    service.request_refresh()
    return RedirectResponse("/", status_code=303)
