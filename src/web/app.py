"""FastAPI application. Routes live in domain packages; this module only wires them."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from core.log import configure_logging
from jobs.refresh import CatalogService
from storage.catalog import Catalog
from web.auth.router import router as auth_router
from web.catalog.router import router as catalog_router
from web.frontend.pages import render_error
from web.language import page_language
from web.security import (
    PAGE_HEADERS,
    AllowedHosts,
    SecurityHeaders,
    is_address,
    is_local_bind,
    network_address,
)

log = logging.getLogger("jobsearch")


def create_app(
    catalog: Catalog,
    service: CatalogService,
    start_scheduler: bool = True,
    allow_lan: bool = False,
) -> FastAPI:
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
    app.state.allow_lan = allow_lan
    app.include_router(auth_router)
    app.include_router(catalog_router)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, _exc: Exception) -> HTMLResponse | JSONResponse:
        log.exception("request failed: %s", request.url.path)
        path = request.url.path
        if path.startswith(("/api", "/fragments")) or path == "/health":
            return JSONResponse({"ok": False, "detail": "internal error"}, status_code=500)
        language, _explicit = page_language(request)
        return HTMLResponse(render_error(language), status_code=500, headers=PAGE_HEADERS)

    return app


def serve(
    port: int = 8765,
    interval_hours: float = 6,
    pages: int = 100,
    host: str = "127.0.0.1",
) -> None:
    if not 1 <= port <= 65535:
        raise SystemExit("Port must be from 1 to 65535.")
    if not is_local_bind(host) and not is_address(host):
        raise SystemExit("Host must be localhost or an IP address.")
    configure_logging()
    catalog = Catalog()
    service = CatalogService(catalog, interval_hours=interval_hours, pages=pages)
    open_to_network = not is_local_bind(host)
    app = create_app(catalog, service, allow_lan=open_to_network)
    log.info("Open http://127.0.0.1:%s", port)
    if open_to_network:
        address = network_address() if host in ("0.0.0.0", "::") else host
        if address:
            log.info("On another device in this network open http://%s:%s", address, port)
        log.warning(
            "Anyone who can open this address can create an account and read the shared list. "
            "Marks and saved filters stay with the account. "
            "Refreshing stays limited to this computer."
        )
    log.info(
        "The catalog refreshes every %g h and reads every page until a site runs out (at most %s). "
        "Leave this process running. Ctrl+C finishes the current site, then stops.",
        service.interval_hours,
        service.pages,
    )
    uvicorn.run(app, host=host, port=port, log_level="info")
