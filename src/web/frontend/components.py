"""Page pieces shared by the catalog and the saved report."""

from __future__ import annotations

from html import escape

from core.models import SourceStatus
from web.frontend.i18n import Translator

# Name, address, and the i18n key of the note shown next to it.
MANUAL_LINKS = (
    (
        "Djinni",
        "https://djinni.co/jobs/?employment=remote&editorial=reservation",
        "link_djinni",
    ),
    (
        "DOU",
        "https://jobs.dou.ua/vacancies/?remote=&search=%D0%B1%D1%80%D0%BE%D0%BD%D1%8E%D0%B2%D0%B0%D0%BD%D0%BD%D1%8F",
        "link_dou",
    ),
    (
        "Work.ua",
        "https://www.work.ua/jobs-remote-industry-it/?deferment=1",
        "link_workua",
    ),
    (
        "Robota.ua",
        "https://robota.ua/zapros/ukraine/params;rubrics=1",
        "link_robota",
    ),
    (
        "Jooble",
        "https://ua.jooble.org/SearchResult?rgns=%D0%B2%D1%96%D0%B4%D0%B4%D0%B0%D0%BB%D0%B5%D0%BD%D0%BE&ukw=%D0%B1%D1%80%D0%BE%D0%BD%D1%8E%D0%B2%D0%B0%D0%BD%D0%BD%D1%8F%20%D0%BF%D1%80%D0%B0%D1%86%D1%96%D0%B2%D0%BD%D0%B8%D0%BA%D1%96%D0%B2",
        "link_jooble",
    ),
)


def source_chips(statuses: list[SourceStatus], t: Translator) -> str:
    if not statuses:
        return ""
    return '<ul class="sources">' + "".join(_chip(status, t) for status in statuses) + "</ul>"


def _chip(status: SourceStatus, t: Translator) -> str:
    if not status.ok:
        css, detail = "bad", t("chip_error")
    elif not status.complete:
        css, detail = "warn", str(status.kept)
    else:
        css, detail = "ok", str(status.kept)
    return (
        f'<li class="{css}" title="{escape(status.message)}">'
        f"<strong>{escape(status.name)}</strong> {escape(detail)}</li>"
    )


def manual_links(t: Translator) -> str:
    items = "".join(
        f'<li><a href="{escape(url)}">{escape(name)}</a> — {escape(t(note))}</li>'
        for name, url, note in MANUAL_LINKS
    )
    return f'<h2>{escape(t("manual_title"))}</h2>\n  <ul class="links">{items}</ul>'
