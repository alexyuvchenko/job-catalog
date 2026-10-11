"""Sign-in and registration pages."""

from __future__ import annotations

from html import escape
from urllib.parse import urlencode

from web.frontend.assets.styles import CSS
from web.frontend.i18n import LANGUAGES, translator


def render_auth(
    language: str,
    mode: str,
    *,
    error: str = "",
    username: str = "",
    next_path: str = "/",
    allow_register: bool = True,
) -> str:
    """``mode`` is ``login`` or ``register``."""
    t = translator(language)
    title = t("login_title" if mode == "login" else "register_title")
    lead = t("login_lead" if mode == "login" else "register_lead")
    action = "/login" if mode == "login" else "/register"
    password_auto = "current-password" if mode == "login" else "new-password"
    submit = t("sign_in" if mode == "login" else "register_submit")
    alert = f'<p class="banner problem" role="alert">{escape(t(error))}</p>' if error else ""
    again = ""
    if mode == "register":
        again = (
            f"<label>{escape(t('password_again'))}"
            f'<input name="password2" type="password" autocomplete="new-password" '
            f'required minlength="8" maxlength="200"></label>'
        )
    hidden_next = ""
    if mode == "login":
        hidden_next = f'<input type="hidden" name="next" value="{escape(next_path)}">'
    if mode == "login" and allow_register:
        switch = (
            f'<p class="switch">{escape(t("need_account"))} '
            f'<a href="{_href("/register", language)}">{escape(t("go_register"))}</a></p>'
        )
    elif mode == "login":
        switch = ""
    else:
        switch = (
            f'<p class="switch">{escape(t("have_account"))} '
            f'<a href="{_href("/login", language)}">{escape(t("go_login"))}</a></p>'
        )
    return f"""<!DOCTYPE html>
<html lang="{language}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>{CSS}</style>
</head>
<body class="auth-page">
<main>
  <div class="topbar">
    <h1>{escape(title)}</h1>
    {_langs(language, t, action, next_path if mode == "login" else "")}
  </div>
  <p class="lede">{escape(lead)}</p>
  <form class="panel auth" method="post" action="{action}">
    {hidden_next}
    {alert}
    <label>{escape(t("username"))}
      <input name="username" autocomplete="username" required maxlength="64" spellcheck="false" value="{escape(username)}">
    </label>
    <label>{escape(t("password"))}
      <input name="password" type="password" autocomplete="{password_auto}" required minlength="8" maxlength="200">
    </label>
    {again}
    <div class="actions">
      <button type="submit">{escape(submit)}</button>
    </div>
    {switch}
  </form>
  <p class="note">{escape(t("auth_note"))}</p>
</main>
</body>
</html>
"""


def _href(path: str, language: str, next_path: str = "") -> str:
    params = [("lang", language)]
    if next_path and next_path != "/":
        params.append(("next", next_path))
    return escape(path + "?" + urlencode(params))


def _langs(language: str, t, path: str, next_path: str) -> str:
    links = []
    for code in LANGUAGES:
        current = ' aria-current="true"' if code == language else ""
        links.append(
            f'<a href="{_href(path, code, next_path)}" hreflang="{code}" lang="{code}"{current}>'
            f"{code.upper()}</a>"
        )
    return f'<nav class="langs" aria-label="{escape(t("language_switch"))}">{"".join(links)}</nav>'
