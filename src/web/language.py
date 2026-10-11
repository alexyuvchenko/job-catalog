"""The language of a page, and the cookie that remembers a visitor's choice."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from storage.catalog import Catalog
from web.auth.service import User
from web.frontend import i18n
from web.security import cookie_secure

LANGUAGE_COOKIE = "lang"


def page_language(request: Request, saved: str = "") -> tuple[str, bool]:
    """The page language, and whether the visitor just picked it (so it should be saved)."""
    chosen = request.query_params.get("lang", "")
    language = i18n.pick_language(
        chosen,
        request.cookies.get(LANGUAGE_COOKIE, ""),
        request.headers.get("accept-language", ""),
        saved,
    )
    return language, chosen in i18n.LANGUAGES


def set_lang_cookie(
    response: HTMLResponse | RedirectResponse, language: str, *, secure: bool = False
) -> None:
    response.set_cookie(
        LANGUAGE_COOKIE,
        language,
        max_age=365 * 24 * 3600,
        samesite="lax",
        httponly=True,
        secure=secure,
    )


def stick_language(
    response: HTMLResponse | RedirectResponse,
    request: Request,
    catalog: Catalog,
    user: User,
    language: str,
    explicit: bool,
) -> None:
    secure = cookie_secure(request)
    if explicit:
        catalog.save_language(user.id, language)
        set_lang_cookie(response, language, secure=secure)
        return
    cookie = request.cookies.get(LANGUAGE_COOKIE, "")
    if language in i18n.LANGUAGES and cookie not in i18n.LANGUAGES:
        if catalog.saved_language(user.id) == language:
            set_lang_cookie(response, language, secure=secure)
