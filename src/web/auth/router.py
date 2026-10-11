"""Sign in, register, and sign out."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from storage.catalog import Catalog
from web.auth.dependencies import clear_session, form_body, signed_in, start_session
from web.auth.service import SESSION_COOKIE, AccountError, safe_next
from web.frontend.account_page import render_auth
from web.language import page_language, set_lang_cookie
from web.security import PAGE_HEADERS, cookie_secure, same_origin

router = APIRouter()


def _auth_page(
    request: Request, language: str, explicit: bool, mode: str, **kwargs: str
) -> HTMLResponse:
    allow_register = bool(request.app.state.allow_register)
    response = HTMLResponse(
        render_auth(language, mode, allow_register=allow_register, **kwargs),
        headers=PAGE_HEADERS,
    )
    if explicit:
        set_lang_cookie(response, language, secure=cookie_secure(request))
    return response


@router.get("/login", response_class=HTMLResponse, response_model=None)
def login_form(request: Request, next: str = ""):
    catalog: Catalog = request.app.state.catalog
    if signed_in(catalog, request) is not None:
        return RedirectResponse(safe_next(next), status_code=303)
    language, explicit = page_language(request)
    return _auth_page(request, language, explicit, "login", next_path=safe_next(next))


@router.post("/login", response_model=None)
async def login_submit(request: Request):
    if not same_origin(request):
        return JSONResponse({"detail": "only accepted from this site"}, status_code=403)
    catalog: Catalog = request.app.state.catalog
    language, explicit = page_language(request)
    fields = await form_body(request)
    if fields is None:
        return PlainTextResponse("send application/x-www-form-urlencoded", status_code=415)
    username = fields.get("username", "")
    nxt = safe_next(fields.get("next", ""))
    user = await asyncio.to_thread(catalog.authenticate, username, fields.get("password", ""))
    if user is None:
        return _auth_page(
            request,
            language,
            explicit,
            "login",
            error="auth_failed",
            username=username.strip()[:64],
            next_path=nxt,
        )
    return await start_session(request, catalog, user, nxt, language, explicit)


@router.get("/register", response_class=HTMLResponse)
def register_form(request: Request) -> HTMLResponse:
    language, explicit = page_language(request)
    if not request.app.state.allow_register:
        return _auth_page(request, language, explicit, "login", error="register_closed")
    return _auth_page(request, language, explicit, "register")


@router.post("/register", response_model=None)
async def register_submit(request: Request):
    if not same_origin(request):
        return JSONResponse({"detail": "only accepted from this site"}, status_code=403)
    catalog: Catalog = request.app.state.catalog
    language, explicit = page_language(request)
    if not request.app.state.allow_register:
        return _auth_page(request, language, explicit, "login", error="register_closed")
    fields = await form_body(request)
    if fields is None:
        return PlainTextResponse("send application/x-www-form-urlencoded", status_code=415)
    username = fields.get("username", "")
    password = fields.get("password", "")
    shown = username.strip()[:64]
    if password != fields.get("password2", ""):
        return _auth_page(
            request, language, explicit, "register", error="password_mismatch", username=shown
        )
    try:
        user = await asyncio.to_thread(catalog.create_user, username, password)
    except AccountError as exc:
        return _auth_page(language, explicit, "register", error=exc.code, username=shown)
    return await start_session(request, catalog, user, "/", language, explicit)


@router.post("/logout", response_model=None)
async def logout(request: Request):
    if not same_origin(request):
        return JSONResponse({"detail": "only accepted from this site"}, status_code=403)
    catalog: Catalog = request.app.state.catalog
    token = request.cookies.get(SESSION_COOKIE, "")
    if token:
        await asyncio.to_thread(catalog.close_session, token)
    response = RedirectResponse("/login", status_code=303)
    response.headers["Cache-Control"] = "no-store"
    clear_session(response, secure=cookie_secure(request))
    return response
