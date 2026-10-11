"""Session cookie and the sign-in redirect used by every private route."""

from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, quote

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from storage.catalog import Catalog
from web.auth.service import SESSION_COOKIE, SESSION_DAYS, User, safe_next
from web.frontend import i18n
from web.language import LANGUAGE_COOKIE, set_lang_cookie
from web.security import cookie_secure

_MAX_FORM = 10_000


def signed_in(catalog: Catalog, request: Request) -> User | None:
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token:
        return None
    return catalog.user_for_session(token)


def ask_sign_in(request: Request) -> RedirectResponse | JSONResponse:
    if request.url.path.startswith(("/api", "/fragments")):
        return JSONResponse({"detail": "sign in"}, status_code=401)
    nxt = request.url.path
    if request.url.query:
        nxt += "?" + request.url.query
    return RedirectResponse("/login?next=" + quote(safe_next(nxt), safe=""), status_code=303)


def set_session(response: RedirectResponse, token: str, *, secure: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def clear_session(response: RedirectResponse, *, secure: bool) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="lax", secure=secure)


async def form_body(request: Request) -> dict[str, str] | None:
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("application/x-www-form-urlencoded"):
        return None
    raw = await request.body()
    if len(raw) > _MAX_FORM:
        return None
    parsed = parse_qs(raw.decode(errors="replace"), keep_blank_values=True, max_num_fields=12)
    return {key: values[0] if values else "" for key, values in parsed.items()}


async def start_session(
    request: Request,
    catalog: Catalog,
    user: User,
    nxt: str,
    language: str,
    explicit: bool,
) -> RedirectResponse:
    old = request.cookies.get(SESSION_COOKIE, "")
    if old:
        await asyncio.to_thread(catalog.close_session, old)
    token = await asyncio.to_thread(catalog.open_session, user.id)
    cookie_lang = request.cookies.get(LANGUAGE_COOKIE, "")
    if cookie_lang in i18n.LANGUAGES:
        await asyncio.to_thread(catalog.save_language, user.id, cookie_lang)
    response = RedirectResponse(safe_next(nxt), status_code=303)
    response.headers["Cache-Control"] = "no-store"
    secure = cookie_secure(request)
    set_session(response, token, secure=secure)
    if explicit or cookie_lang in i18n.LANGUAGES:
        set_lang_cookie(
            response,
            cookie_lang if cookie_lang in i18n.LANGUAGES else language,
            secure=secure,
        )
    return response
