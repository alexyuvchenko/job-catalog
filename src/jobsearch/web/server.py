from __future__ import annotations

import ipaddress
import logging
import socket
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from jobsearch.constants import ENGLISH_LEVELS, SOURCE_NAMES
from jobsearch.db.catalog import (
    CHANGE_CHOICES,
    LANGUAGE_CHOICES,
    MAX_RATING,
    MINE_CHOICES,
    Catalog,
    CatalogFilters,
)
from jobsearch.log import configure_logging
from jobsearch.service import CatalogService
from jobsearch.web import i18n
from jobsearch.web.pages import (
    DEFAULT_PER_PAGE,
    PER_PAGE_CHOICES,
    CatalogView,
    render_catalog,
)
from jobsearch.web.rows import render_rows

log = logging.getLogger("jobsearch")

_SOURCES = {"", *SOURCE_NAMES}
_ENGLISH = {"", *ENGLISH_LEVELS}
_LANGUAGE_COOKIE = "lang"
_LOCAL_NAMES = {"localhost", "127.0.0.1", "::1"}
# Tailscale and other carrier-grade NAT addresses are private to the tunnel, but Python
# does not count 100.64.0.0/10 as private.
_SHARED_RANGE = ipaddress.ip_network("100.64.0.0/10")
_PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
        "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
}
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
}


def host_allowed(header: str, allow_lan: bool) -> bool:
    """Accept only this machine, or, on a trusted network, a private IP address.

    Names other than localhost are never accepted, so a web page cannot point its own
    domain at this service (DNS rebinding).
    """
    name = _host_name(header)
    if name in _LOCAL_NAMES:
        return True
    if not allow_lan:
        return False
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address in _SHARED_RANGE
    )


def _host_name(header: str) -> str:
    value = header.strip().lower()
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end > 0 else ""
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


class AllowedHosts:
    def __init__(self, app: ASGIApp, allow_lan: bool) -> None:
        self.app = app
        self.allow_lan = allow_lan

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            if not host_allowed(Headers(scope=scope).get("host", ""), self.allow_lan):
                if scope["type"] == "http":
                    await PlainTextResponse("Invalid host header", status_code=400)(
                        scope, receive, send
                    )
                return
        await self.app(scope, receive, send)


class SecurityHeaders:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in _SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


def create_app(
    catalog: Catalog,
    service: CatalogService,
    start_scheduler: bool = True,
    allow_lan: bool = False,
) -> FastAPI:
    def can_refresh(request: Request) -> bool:
        # A refresh opens Chrome on this machine, so other devices only read.
        return not allow_lan or _is_local_client(request)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if start_scheduler:
            service.start()
        yield
        service.stop()

    app = FastAPI(title="Віддалені IT-вакансії з бронюванням", lifespan=lifespan)
    app.add_middleware(AllowedHosts, allow_lan=allow_lan)
    app.add_middleware(SecurityHeaders)
    app.state.catalog = catalog
    app.state.service = service

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> HTMLResponse | JSONResponse:
        log.exception("request failed: %s", request.url.path)
        path = request.url.path
        if path.startswith(("/api", "/fragments")) or path == "/health":
            return JSONResponse({"ok": False, "detail": "internal error"}, status_code=500)
        language, _explicit = _language(request)
        return HTMLResponse(_error_page(language), status_code=500, headers=_PAGE_HEADERS)

    @app.get("/", response_class=HTMLResponse)
    def home(
        request: Request,
        filters: CatalogFilters = Depends(read_filters),
        paging: tuple[int, int] = Depends(read_paging),
    ) -> HTMLResponse:
        language, explicit = _language(request)
        view = _view(catalog, service, filters, *paging)
        view.can_refresh = can_refresh(request)
        view.language = language
        response = HTMLResponse(render_catalog(view), headers=_PAGE_HEADERS)
        if explicit:
            response.set_cookie(
                _LANGUAGE_COOKIE, language, max_age=365 * 24 * 3600, samesite="lax", httponly=True
            )
        return response

    @app.get("/fragments/rows", response_model=None)
    def rows(
        request: Request,
        filters: CatalogFilters = Depends(read_filters),
        paging: tuple[int, int] = Depends(read_paging),
    ) -> JSONResponse:
        """The next batch of table rows, for the "show more" button."""
        language, _explicit = _language(request)
        # A page past the end is empty, so a stale "show more" never repeats rows.
        view = _view(catalog, service, filters, *paging, clamp=False)
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

    @app.post("/api/jobs/state", response_model=None)
    def set_state(request: Request, update: MarksUpdate):
        """Mark a vacancy: favorite, not for me, viewed, or a rating from 1 to 5."""
        if not _same_origin(request):
            return JSONResponse({"detail": "only accepted from this site"}, status_code=403)
        if not request.headers.get("content-type", "").startswith("application/json"):
            return JSONResponse({"detail": "send application/json"}, status_code=415)
        marks = catalog.set_marks(
            update.url,
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

    @app.get("/health", response_model=None)
    @app.get("/api/status", response_model=None)
    def health():
        try:
            active, inactive = catalog.counts()
            _statuses, finished, _added, _updated, _deactivated = catalog.latest_statuses()
        except Exception:
            log.exception("health check failed")
            return JSONResponse({"ok": False}, status_code=503)
        return {
            "ok": True,
            "running": service.running,
            "active": active,
            "inactive": inactive,
            "last_finished": finished,
            "next_run": service.next_run,
            "last_error": service.last_error,
        }

    @app.get("/api/jobs")
    def jobs(filters: CatalogFilters = Depends(read_filters)) -> list[dict]:
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
            }
            for item in catalog.list_jobs(filters)
        ]

    @app.post("/refresh", status_code=303, response_model=None)
    def refresh(request: Request):
        if not _same_origin(request):
            return JSONResponse(
                {"detail": "refresh is only accepted from this site"}, status_code=403
            )
        if not can_refresh(request):
            return JSONResponse(
                {"detail": "refresh can only be started on the computer that runs the service"},
                status_code=403,
            )
        service.request_refresh()
        return RedirectResponse("/", status_code=303)

    return app


def serve(
    port: int = 8765,
    interval_hours: float = 6,
    pages: int = 100,
    host: str = "127.0.0.1",
) -> None:
    if not 1 <= port <= 65535:
        raise SystemExit("Port must be from 1 to 65535.")
    if not is_local_bind(host) and not _is_address(host):
        raise SystemExit("Host must be localhost or an IP address.")
    configure_logging()
    catalog = Catalog()
    service = CatalogService(catalog, interval_hours=interval_hours, pages=pages)
    open_to_network = not is_local_bind(host)
    app = create_app(catalog, service, allow_lan=open_to_network)
    log.info("Open http://127.0.0.1:%s", port)
    if open_to_network:
        address = _network_address() if host in ("0.0.0.0", "::") else host
        if address:
            log.info("On another device in this network open http://%s:%s", address, port)
        log.warning(
            "The page has no login. Anyone on this network can read the list. "
            "Refreshing stays limited to this computer."
        )
    log.info(
        "The catalog refreshes every %g h and reads every page until a site runs out (at most %s). "
        "Leave this process running. Ctrl+C finishes the current site, then stops.",
        service.interval_hours,
        service.pages,
    )
    uvicorn.run(app, host=host, port=port, log_level="info")


def is_local_bind(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _network_address() -> str:
    """The address other devices use to reach this machine. Nothing is sent."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]
    except OSError:
        return ""
    finally:
        probe.close()


def _is_local_client(request: Request) -> bool:
    client = request.client
    if client is None:
        return False
    try:
        if ipaddress.ip_address(client.host).is_loopback:
            return True
    except ValueError:
        return False
    # Opening the page through this machine's own network address still counts as local.
    server = request.scope.get("server")
    return bool(server) and server[0] == client.host


def _same_origin(request: Request) -> bool:
    host = request.headers.get("host", "")
    origin = request.headers.get("origin")
    if origin:
        return urlsplit(origin).netloc == host
    referer = request.headers.get("referer")
    if referer:
        return urlsplit(referer).netloc == host
    return True


class MarksUpdate(BaseModel):
    """A change to your own notes about one vacancy. Omitted fields stay as they are."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2000)
    favorite: bool | None = None
    hidden: bool | None = None
    rating: int | None = Field(default=None, ge=0, le=MAX_RATING)
    viewed: bool | None = None


def _language(request: Request) -> tuple[str, bool]:
    """The page language, and whether the visitor just picked it (so it should be saved)."""
    chosen = request.query_params.get("lang", "")
    language = i18n.pick_language(
        chosen,
        request.cookies.get(_LANGUAGE_COOKIE, ""),
        request.headers.get("accept-language", ""),
    )
    return language, chosen in i18n.LANGUAGES


def _error_page(language: str) -> str:
    t = i18n.translator(language)
    return f"""<!DOCTYPE html>
<html lang="{language}">
<head>
  <meta charset="utf-8">
  <title>{t("error_title")}</title>
</head>
<body>
  <p>{t("error_body")}</p>
</body>
</html>
"""


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
) -> CatalogFilters:
    level = english.strip().upper()
    chosen = source.strip()
    rating = _int(min_rating)
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
    )


def read_paging(page: str = "", per_page: str = "") -> tuple[int, int]:
    size = _int(per_page)
    number = _int(page)
    return (
        number if number is not None and number >= 1 else 1,
        size if size in PER_PAGE_CHOICES else DEFAULT_PER_PAGE,
    )


def _view(
    catalog: Catalog,
    service: CatalogService,
    filters: CatalogFilters,
    page: int,
    per_page: int,
    *,
    clamp: bool = True,
) -> CatalogView:
    stored = catalog.list_jobs(filters)
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
        new_count=sum(1 for item in stored if item.active and item.change == "added"),
        running=service.running,
        last_finished=finished,
        next_run=service.next_run,
        added=added,
        updated=updated,
        deactivated=deactivated,
        error=service.last_error,
    )


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
