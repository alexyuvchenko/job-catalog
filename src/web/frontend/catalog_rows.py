"""Table rows for the catalog and the saved report."""

from __future__ import annotations

from html import escape

from storage.filters import MAX_RATING
from storage.records import StoredJob
from web.frontend.i18n import Translator

# Tracked field -> the word shown in the "changed" tooltip.
_CHANGE_KEYS = {
    "title": "change_title",
    "company": "change_company",
    "location": "change_location",
    "remote": "change_remote",
    "salary_min": "change_salary",
    "salary_max": "change_salary",
    "currency": "change_salary",
    "salary_text": "change_salary",
    "reservation": "change_reservation",
    "english": "change_english",
    "years": "change_years",
    "category": "change_category",
    "active": "change_active",
}


def render_rows(items: list[StoredJob], t: Translator, *, actions: bool) -> str:
    return "\n".join(render_row(item, t, actions=actions) for item in items)


def render_row(item: StoredJob, t: Translator, *, actions: bool = True) -> str:
    job = item.job
    marks = item.marks
    change = item.change
    classes = []
    if not item.active:
        classes.append("closed")
    if change == "added":
        classes.append("is-new")
    elif change == "changed":
        classes.append("is-changed")
    if marks.viewed:
        classes.append("viewed")
    if marks.hidden:
        classes.append("is-hidden")
    if marks.favorite:
        classes.append("is-fav")
    data = ""
    if actions:
        data = f' data-url="{escape(job.url)}" data-rating="{marks.rating}"'
    class_attr = f' class="{" ".join(classes)}"' if classes else ""

    salary = job.salary_text or "—"
    remote = _label(t, "remote_", job.remote)
    location = f" · {escape(job.location)}" if job.location else ""
    category = f" · {escape(job.category)}" if job.category else ""
    english = (
        f" · {escape(t('english_in_text', level=job.english))}"
        if job.english and job.english != "none"
        else ""
    )
    years = ""
    if job.years is not None:
        number = str(int(job.years)) if job.years == int(job.years) else str(job.years)
        years = f" · {escape(t('years_experience', n=number))}"
    company = escape(job.company) if job.company else "—"
    pay_class = "pay" if job.salary_text else "pay none"
    open_attrs = ' data-open target="_blank" rel="noopener noreferrer"' if actions else ""
    cells = [
        f'<td class="when">{escape(job.published or "—")}</td>',
        f'<td class="job"><a class="title" href="{escape(job.url)}"{open_attrs}>'
        f"{escape(job.title)}</a>{_tags(item, change, t)}"
        f'\n        <div class="meta">{escape(job.source)}{category}{english}{years}</div></td>',
        f'<td class="company">{company}</td>',
        f'<td class="where">{escape(remote)}{location}</td>',
        f'<td class="{pay_class}">{escape(salary)}</td>',
        f'<td class="status">{_status(item, t)}</td>',
    ]
    if actions:
        cells.append(_mine(item, t))
    body = "\n      ".join(cells)
    return f"<tr{class_attr}{data}>\n      {body}\n    </tr>"


def _tags(item: StoredJob, change: str, t: Translator) -> str:
    tags = []
    if change == "added":
        tags.append(f'<span class="tag tag-new">{escape(t("tag_new"))}</span>')
    elif change == "changed":
        fields = ", ".join(
            dict.fromkeys(t(_CHANGE_KEYS[name]) for name in item.changes if name in _CHANGE_KEYS)
        )
        hint = f' title="{escape(t("changed_fields", fields=fields))}"' if fields else ""
        tags.append(f'<span class="tag tag-changed"{hint}>{escape(t("tag_changed"))}</span>')
    elif change == "closed":
        tags.append(f'<span class="tag tag-closed">{escape(t("tag_closed"))}</span>')
    if item.language == "en":
        text = escape(t("description_english"))
        tags.append(f'<span class="chip-en" title="{text}" aria-label="{text}">EN</span>')
    return "".join(tags)


def _status(item: StoredJob, t: Translator) -> str:
    job = item.job
    if not item.active:
        return f'<span class="badge warn">{escape(t("tag_closed"))}</span>'
    confirmed = job.reservation == "confirmed"
    text = _label(t, "reservation_", job.reservation)
    hint = f' title="{escape(job.evidence)}"' if job.evidence else ""
    css = "badge" if confirmed else "badge warn"
    return f'<span class="{css}"{hint}>{escape(text)}</span>'


def _mine(item: StoredJob, t: Translator) -> str:
    marks = item.marks
    buttons = [
        _action("favorite", "fav", "♥", t("act_favorite"), marks.favorite),
        _action("hidden", "hide", "✕", t("act_hide"), marks.hidden),
        _action("viewed", "seen", "✓", t("act_viewed"), marks.viewed),
    ]
    stars = []
    for value in range(1, MAX_RATING + 1):
        label = escape(t("act_star", n=value))
        on = " on" if value <= marks.rating else ""
        pressed = "true" if value == marks.rating else "false"
        stars.append(
            f'<button type="button" class="star{on}" data-act="rating" data-value="{value}" '
            f'aria-pressed="{pressed}" aria-label="{label}" title="{label}">★</button>'
        )
    return (
        '<td class="mine">'
        f'<div class="acts">{"".join(buttons)}</div>'
        f'<div class="stars" role="group" aria-label="{escape(t("act_rating"))}">'
        f"{''.join(stars)}</div></td>"
    )


def _action(name: str, css: str, symbol: str, label: str, pressed: bool) -> str:
    text = escape(label)
    return (
        f'<button type="button" class="act {css}" data-act="{name}" '
        f'aria-pressed="{"true" if pressed else "false"}" aria-label="{text}" '
        f'title="{text}">{symbol}</button>'
    )


def _label(t: Translator, prefix: str, value: str) -> str:
    try:
        return t(prefix + value)
    except KeyError:
        return value
