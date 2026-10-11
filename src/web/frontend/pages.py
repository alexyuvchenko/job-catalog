"""The catalog page."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from html import escape
from urllib.parse import urlencode

from core.constants import SOURCE_NAMES
from core.models import SourceStatus
from storage.filters import (
    CHANGE_CHOICES,
    LANGUAGE_CHOICES,
    MAX_RATING,
    MINE_CHOICES,
    CatalogFilters,
    active_sort,
    default_descending,
)
from storage.records import StoredJob
from web.frontend.assets.favicon import FAVICON_LINK
from web.frontend.assets.script import CATALOG_JS
from web.frontend.assets.styles import CSS
from web.frontend.catalog_rows import render_rows
from web.frontend.components import manual_links, source_chips
from web.frontend.i18n import LANGUAGES, Translator, translator

PER_PAGE_CHOICES = (25, 50, 100, 200)
DEFAULT_PER_PAGE = 50
_ENGLISH_OPTIONS = ("A2", "B1", "B2", "C1", "C2")
_CLIENT_TEXT = {
    "toastHidden": "toast_hidden",
    "toastError": "toast_error",
    "loading": "loading",
    "loadError": "load_error",
    "showing": "showing",
}


@dataclass
class CatalogView:
    """Everything the catalog page shows. The server fills it, the page only draws it."""

    items: list[StoredJob]
    total: int
    page: int
    per_page: int
    filters: CatalogFilters
    statuses: list[SourceStatus] = field(default_factory=list)
    active_count: int = 0
    inactive_count: int = 0
    user_count: int = 0
    new_count: int = 0
    running: bool = False
    last_finished: str = ""
    next_run: str = ""
    added: int = 0
    updated: int = 0
    deactivated: int = 0
    error: str = ""
    can_refresh: bool = True
    language: str = "uk"
    username: str = ""

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.per_page))

    @property
    def first(self) -> int:
        return (self.page - 1) * self.per_page + 1 if self.items else 0

    @property
    def last(self) -> int:
        return (self.page - 1) * self.per_page + len(self.items)


def filter_params(
    filters: CatalogFilters, per_page: int = DEFAULT_PER_PAGE
) -> list[tuple[str, str]]:
    """The query string that reproduces these filters. Defaults are left out."""
    params = [
        ("q", filters.text),
        ("source", filters.source),
        ("mine", filters.mine),
        ("min_rating", "" if filters.min_rating is None else str(filters.min_rating)),
        ("change", filters.change),
        ("language", filters.language),
        ("min_salary", "" if filters.min_salary is None else str(filters.min_salary)),
        ("english", filters.english),
        ("min_years", "" if filters.min_years is None else f"{filters.min_years:g}"),
        ("full_remote_only", "1" if filters.full_remote_only else ""),
        ("include_inactive", "1" if filters.include_inactive else ""),
        ("per_page", "" if per_page == DEFAULT_PER_PAGE else str(per_page)),
        ("sort", filters.sort),
        ("dir", "" if filters.descending is None else ("desc" if filters.descending else "asc")),
    ]
    return [(name, value) for name, value in params if value]


def render_catalog(view: CatalogView) -> str:
    t = translator(view.language)
    filters = view.filters
    rows = render_rows(view.items, t, actions=True)
    if not rows:
        message = t("empty_running") if view.running and not view.total else t("empty_filters")
        rows = f'<tr><td colspan="7" class="empty">{escape(message)}</td></tr>'
    notices = []
    if view.running:
        notices.append(f'<p class="banner">{escape(t("banner_running"))}</p>')
    if view.error:
        notices.append(f'<p class="banner problem">{escape(view.error)}</p>')
    shows_hidden = "1" if filters.mine in ("all", "hidden") else "0"
    note = t("new_note", n=view.new_count) if view.new_count else ""
    if view.items:
        shown = t("showing", first=view.first, last=view.last, total=view.total)
    else:
        shown = t("showing_none")
    client = {name: t(key) for name, key in _CLIENT_TEXT.items()}
    # "</" cannot appear in the block, or the page would end the script early.
    client_json = json.dumps(client, ensure_ascii=False).replace("<", "\\u003c")
    return f"""<!DOCTYPE html>
<html lang="{view.language}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(t("title"))}</title>
  {FAVICON_LINK}
  <style>{CSS}</style>
</head>
<body data-refreshing="{"1" if view.running else "0"}" data-shows-hidden="{shows_hidden}">
<main>
  <div class="topbar">
    <h1>{escape(t("title"))}</h1>
    <div class="who">{_language_switch(view, t)}{_account(view, t)}</div>
  </div>
  <p class="lede">{escape(t("lede_catalog"))}</p>
  {"".join(notices)}
  <p class="statusline">{_statusline(view, t)}</p>
  {_form(view, t)}
  {source_chips(view.statuses, t)}
  {_legend(t)}
  <div class="toolbar">
    <div class="count" id="shown" data-first="{view.first}" data-note="{escape(note)}">{escape(shown)}{escape(note)}</div>
  </div>
  <div class="table-wrap">
  <table>
    <caption>{escape(t("table_caption"))}</caption>
    <thead>
      <tr>
        {_sort_header(view, t, "date")}
        {_sort_header(view, t, "job")}
        {_sort_header(view, t, "company")}
        <th>{escape(t("th_format"))}</th>
        <th>{escape(t("th_salary"))}</th>
        <th>{escape(t("th_reservation"))}</th>
        <th>{escape(t("th_mine"))}</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
  </div>
  {_paging(view, t)}
  {manual_links(t)}
  <p class="note">{escape(t("note_catalog"))}</p>
</main>
<div id="toast" role="status" aria-live="polite" hidden><span></span><button type="button">{escape(t("toast_undo"))}</button></div>
<script type="application/json" id="i18n">{client_json}</script>
<script>{CATALOG_JS}</script>
</body>
</html>
"""


def _sort_header(view: CatalogView, t: Translator, column: str) -> str:
    """A column title that sorts by that column; a second click reverses the order."""
    filters = view.filters
    current, descending = active_sort(filters)
    active = current == column
    next_desc = not descending if active else default_descending(column)
    params = [
        (name, value)
        for name, value in filter_params(filters, view.per_page)
        if name not in ("sort", "dir")
    ]
    params += [("sort", column), ("dir", "desc" if next_desc else "asc")]
    href = escape("/?" + urlencode(params))
    arrow = ' <span class="idle" aria-hidden="true">⇅</span>'
    state = ""
    if active:
        arrow = (
            ' <span aria-hidden="true">▼</span>'
            if descending
            else ' <span aria-hidden="true">▲</span>'
        )
        state = f' aria-sort="{"descending" if descending else "ascending"}"'
    label = escape(t(f"th_{column}"))
    return f'<th{state}><a class="sort" href="{href}">{label}{arrow}</a></th>'


def _statusline(view: CatalogView, t: Translator) -> str:
    if not view.last_finished:
        progress = escape(t("never_refreshed"))
    else:
        stats = [
            _stat(view, t("stat_added", n=view.added), view.added, "added"),
            _stat(view, t("stat_changed", n=view.updated), view.updated, "changed"),
            _stat(view, t("stat_closed", n=view.deactivated), view.deactivated, "closed"),
        ]
        progress = f"{escape(t('refreshed_at', when=view.last_finished))} {', '.join(stats)}."
        if view.next_run and not view.running:
            progress += f" {escape(t('next_refresh', when=view.next_run))}"
    closed = t("in_catalog_closed", n=view.inactive_count) if view.inactive_count else ""
    return (
        f"{progress} {escape(t('in_catalog', active=view.active_count, closed=closed))} "
        f"{escape(t('users_count', n=view.user_count))}"
    )


def _stat(view: CatalogView, text: str, count: int, change: str) -> str:
    if not count:
        return escape(text)
    params = [
        (name, value)
        for name, value in filter_params(view.filters, view.per_page)
        if name != "change"
    ]
    params.append(("change", change))
    return f'<a class="stat" href="/?{escape(urlencode(params))}">{escape(text)}</a>'


def _account(view: CatalogView, t: Translator) -> str:
    if not view.username:
        return ""
    return (
        f'<div class="account" aria-label="{escape(t("account_label"))}">'
        f'<span class="name">{escape(view.username)}</span>'
        f'<form class="bare" action="/logout" method="post">'
        f'<button class="secondary" type="submit">{escape(t("sign_out"))}</button>'
        f"</form></div>"
    )


def _language_switch(view: CatalogView, t: Translator) -> str:
    params = filter_params(view.filters, view.per_page)
    if view.page > 1:
        params.append(("page", str(view.page)))
    links = []
    for code in LANGUAGES:
        href = "/?" + urlencode([*params, ("lang", code)])
        current = ' aria-current="true"' if code == view.language else ""
        links.append(
            f'<a href="{escape(href)}" hreflang="{code}" lang="{code}"{current}>{code.upper()}</a>'
        )
    return f'<nav class="langs" aria-label="{escape(t("language_switch"))}">{"".join(links)}</nav>'


def _legend(t: Translator) -> str:
    items = [
        ("sw-new", "", "legend_new"),
        ("sw-changed", "", "legend_changed"),
        ("sw-closed", "", "legend_closed"),
        ("sw-viewed", "", "legend_viewed"),
        ("sw-en", "EN", "legend_en"),
    ]
    body = "".join(
        f'<li><span class="swatch {css}" aria-hidden="true">{text}</span>{escape(t(key))}</li>'
        for css, text, key in items
    )
    return (
        f'<details class="legend-box" open><summary>{escape(t("legend_title"))}</summary>'
        f'<ul class="legend">{body}</ul></details>'
    )


def _options(pairs: list[tuple[str, str]], current: str) -> str:
    return "".join(
        f'<option value="{escape(value)}"{" selected" if value == current else ""}>'
        f"{escape(label)}</option>"
        for value, label in pairs
    )


def _form(view: CatalogView, t: Translator) -> str:
    filters = view.filters
    sources = [("", t("all_sources")), *((name, name) for name in SOURCE_NAMES)]
    english = [("", t("any")), *((level, f"{level}+") for level in _ENGLISH_OPTIONS)]
    mine = [
        (choice, t("mine_default" if not choice else f"mine_{choice}")) for choice in MINE_CHOICES
    ]
    rating = [
        ("", t("any")),
        *((str(n), t("rating_from", n=f"{n}★")) for n in range(1, MAX_RATING + 1)),
    ]
    change = [
        (choice, t("all_changes" if not choice else f"change_{choice}"))
        for choice in CHANGE_CHOICES
    ]
    language = [
        (choice, t("any" if not choice else f"lang_{choice}")) for choice in LANGUAGE_CHOICES
    ]
    per_page = [(str(n), str(n)) for n in PER_PAGE_CHOICES]
    salary = "" if filters.min_salary is None else str(filters.min_salary)
    years = "" if filters.min_years is None else f"{filters.min_years:g}"
    min_rating = "" if filters.min_rating is None else str(filters.min_rating)
    full = " checked" if filters.full_remote_only else ""
    closed = " checked" if filters.include_inactive else ""
    if not view.can_refresh:
        button = t("refresh_local")
    else:
        button = t("refresh_running") if view.running else t("refresh_now")
    disabled = " disabled" if view.running or not view.can_refresh else ""
    active = sum(
        1
        for name, _ in filter_params(filters, view.per_page)
        if name not in ("per_page", "sort", "dir")
    )
    hidden_sort = "".join(
        f'<input type="hidden" name="{name}" value="{escape(value)}">'
        for name, value in filter_params(filters, view.per_page)
        if name in ("sort", "dir")
    )
    summary = escape(t("filters"))
    if active:
        summary += f' <span class="badge">{escape(t("filters_active", n=active))}</span>'
    return f"""<details class="panel" id="filter-panel" open>
  <summary>{summary}</summary>
  <form id="filters" class="bare" action="/" method="get">
    {hidden_sort}
    <div class="grid">
      <label>{escape(t("f_q"))}
        <input name="q" type="search" value="{escape(filters.text)}" placeholder="{escape(t("f_q_hint"))}">
      </label>
      <label>{escape(t("f_source"))}
        <select name="source">{_options(sources, filters.source)}</select>
      </label>
      <label>{escape(t("f_mine"))}
        <select name="mine">{_options(mine, filters.mine)}</select>
      </label>
      <label>{escape(t("f_rating"))}
        <select name="min_rating">{_options(rating, min_rating)}</select>
      </label>
      <label>{escape(t("f_change"))}
        <select name="change">{_options(change, filters.change)}</select>
      </label>
      <label>{escape(t("f_language"))}
        <select name="language">{_options(language, filters.language)}</select>
      </label>
      <label>{escape(t("f_salary"))}
        <input name="min_salary" inputmode="numeric" value="{escape(salary)}">
      </label>
      <label>{escape(t("f_english"))}
        <select name="english">{_options(english, filters.english)}</select>
      </label>
      <label>{escape(t("f_years"))}
        <input name="min_years" inputmode="decimal" value="{escape(years)}">
      </label>
      <label>{escape(t("f_per_page"))}
        <select name="per_page">{_options(per_page, str(view.per_page))}</select>
      </label>
    </div>
    <div class="options">
      <label class="checks"><input type="checkbox" name="full_remote_only" value="1"{full}>{escape(t("f_full_remote"))}</label>
      <label class="checks"><input type="checkbox" name="include_inactive" value="1"{closed}>{escape(t("f_inactive"))}</label>
    </div>
  </form>
  <div class="actions">
    <button type="submit" form="filters">{escape(t("apply"))}</button>
    <a class="button secondary" href="/?reset=1">{escape(t("reset"))}</a>
    <form class="bare" action="/refresh" method="post">
      <button class="secondary" type="submit"{disabled}>{escape(button)}</button>
    </form>
  </div>
</details>"""


def _paging(view: CatalogView, t: Translator) -> str:
    if view.pages <= 1:
        return ""
    base = filter_params(view.filters, view.per_page)

    def link(page: int) -> str:
        params = base + ([("page", str(page))] if page > 1 else [])
        return escape("/?" + urlencode(params) if params else "/")

    parts = []
    if view.page > 1:
        parts.append(f'<a href="{link(view.page - 1)}" rel="prev">‹ {escape(t("page_prev"))}</a>')
    else:
        parts.append(f'<a aria-disabled="true">‹ {escape(t("page_prev"))}</a>')
    shown = sorted(
        {
            n
            for n in (1, view.page - 1, view.page, view.page + 1, view.pages)
            if 1 <= n <= view.pages
        }
    )
    previous = 0
    for number in shown:
        if number - previous > 1:
            parts.append('<span class="gap num">…</span>')
        if number == view.page:
            parts.append(f'<a class="num" aria-current="page">{number}</a>')
        else:
            parts.append(f'<a class="num" href="{link(number)}">{number}</a>')
        previous = number
    label = escape(t("page_of", page=view.page, pages=view.pages))
    parts.append(f'<span class="where-label">{label}</span>')
    if view.page < view.pages:
        parts.append(f'<a href="{link(view.page + 1)}" rel="next">{escape(t("page_next"))} ›</a>')
    else:
        parts.append(f'<a aria-disabled="true">{escape(t("page_next"))} ›</a>')
    more = ""
    if view.page < view.pages:
        left = view.total - view.page * view.per_page
        text = t("show_more", n=min(view.per_page, left))
        more = (
            f'<button type="button" id="more" class="secondary" data-next="{view.page + 1}">'
            f"{escape(text)}</button>"
        )
    return (
        f'<div class="paging">{more}'
        f'<nav class="pager" aria-label="{escape(t("page_nav"))}">{"".join(parts)}</nav></div>'
    )


def render_error(language: str) -> str:
    t = translator(language)
    return f"""<!DOCTYPE html>
<html lang="{language}">
<head>
  <meta charset="utf-8">
  <title>{t("error_title")}</title>
  {FAVICON_LINK}
</head>
<body>
  <p>{t("error_body")}</p>
</body>
</html>
"""
