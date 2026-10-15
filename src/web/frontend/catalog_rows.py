"""Table rows for the catalog and the saved report."""

from __future__ import annotations

import json
import re
from html import escape
from urllib.parse import urlsplit

from core.models import CompanyReview, ReviewSource
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
    pay_class = "pay" if job.salary_text else "pay none"
    open_attrs = ' data-open target="_blank" rel="noopener noreferrer"' if actions else ""
    cells = [
        f'<td class="when">{escape(job.published or "—")}</td>',
        f'<td class="job"><a class="title" href="{escape(job.url)}"{open_attrs}>'
        f"{escape(job.title)}</a>{_tags(item, change, t)}"
        f'\n        <div class="meta">{_boards(item, open_attrs)}{category}{english}{years}</div></td>',
        _company_cell(item, t, actions=actions),
        f'<td class="where">{escape(remote)}{location}</td>',
        f'<td class="{pay_class}">{escape(salary)}</td>',
        f'<td class="status">{_status(item, t)}</td>',
    ]
    if actions:
        cells.append(_mine(item, t))
    body = "\n      ".join(cells)
    return f"<tr{class_attr}{data}>\n      {body}\n    </tr>"


def _company_cell(item: StoredJob, t: Translator, *, actions: bool) -> str:
    name = item.job.company.strip()
    shown = escape(name) if name else "—"
    review = item.review
    sources = _display_sources(review)
    if review is None or not sources:
        return f'<td class="company">{shown}</td>'
    badge = _rate_badge(review, t)
    if not actions:
        return f'<td class="company">{shown}{badge}</td>'
    payload_sources = []
    for source in sources:
        links = _source_links(source, t)
        if not links:
            continue
        payload_sources.append(
            {
                "name": source.source,
                "score": source.score,
                "reviews": source.review_count,
                "votes": source.voter_count,
                "links": links,
            }
        )
    if not payload_sources:
        return f'<td class="company">{shown}{badge}</td>'
    payload = json.dumps(
        {"name": name, "rating": review.rating, "sources": payload_sources},
        ensure_ascii=False,
    )
    label = escape(t("company_open", name=name))
    button = (
        f'<button type="button" class="company-open" data-review="{escape(payload)}" '
        f'aria-haspopup="dialog" aria-label="{label}">{shown}{badge}</button>'
    )
    return f'<td class="company">{button}</td>'


def _display_sources(review: CompanyReview | None) -> tuple[ReviewSource, ...]:
    if review is None:
        return ()
    if review.sources:
        return review.sources
    if review.rating is None and not review.review_count:
        return ()
    score = f"{review.rating}/100" if review.rating is not None else ""
    return (
        ReviewSource(
            source="DOU",
            rating=review.rating,
            score=score,
            review_count=review.review_count,
            voter_count=review.voter_count,
            reviews_url=review.reviews_url,
            poll_url=review.poll_url,
        ),
    )


def _source_links(source: ReviewSource, t: Translator) -> list[dict[str, str]]:
    links = []
    reviews_url = _review_page(source.reviews_url)
    poll_url = _review_page(source.poll_url)
    if reviews_url and source.source == "DOU":
        links.append({"href": reviews_url, "label": t("link_company_reviews")})
    elif reviews_url and source.source == "Indeed":
        links.append({"href": reviews_url, "label": t("link_indeed_reviews")})
    if poll_url and source.source == "DOU":
        links.append({"href": poll_url, "label": t("link_company_poll")})
    return links


_INDEED_REVIEWS = re.compile(r"/cmp/[A-Za-z0-9_-]+/reviews/?")


def _review_page(url: str) -> str:
    parsed = urlsplit(url or "")
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return ""
    host = (parsed.hostname or "").lower()
    if host == "jobs.dou.ua" and parsed.path.startswith("/companies/"):
        return url
    if host == "ua.indeed.com" and _INDEED_REVIEWS.fullmatch(parsed.path):
        return url
    return ""


def _rate_badge(review: CompanyReview, t: Translator) -> str:
    if review.rating is None:
        return ""
    if review.rating >= 70:
        band = "good"
    elif review.rating >= 50:
        band = "mid"
    else:
        band = "low"
    scored = [source.source for source in _display_sources(review) if source.rating is not None]
    if scored == ["Indeed"]:
        hint_key = "company_rate_hint_indeed"
    elif len(scored) > 1:
        hint_key = "company_rate_hint_avg"
    else:
        hint_key = "company_rate_hint"
    hint = escape(t(hint_key, n=review.rating))
    return (
        f'<span class="crate crate-{band}" title="{hint}" aria-label="{hint}">'
        f"{review.rating}</span>"
    )


def _boards(item: StoredJob, open_attrs: str) -> str:
    listings = item.listings or ((item.job.source, item.job.url),)
    links = []
    for source, url in listings:
        links.append(f'<a class="board" href="{escape(url)}"{open_attrs}>{escape(source)}</a>')
    return " · ".join(links)


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


# One stroke weight, one box. Text glyphs (♥ ✕ ✓) sit at different sizes.
_ICONS = {
    "fav": (
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<path d="M12 20.6 10.7 19.4C5.4 14.6 2 11.5 2 7.8 2 4.8 4.4 2.4 7.4 2.4c1.7 0 3.3.8 4.6 2.1 1.3-1.3 2.9-2.1 4.6-2.1 3 0 5.4 2.4 5.4 5.4 0 3.7-3.4 6.8-8.7 11.6z"/>'
        "</svg>"
    ),
    "hide": (
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<path d="M7 7l10 10M17 7 7 17"/>'
        "</svg>"
    ),
    "seen": (
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<path d="M5.5 12.4 10 16.8 18.5 7.6"/>'
        "</svg>"
    ),
}


def _mine(item: StoredJob, t: Translator) -> str:
    marks = item.marks
    buttons = [
        _action("favorite", "fav", t("act_favorite"), marks.favorite),
        _action("hidden", "hide", t("act_hide"), marks.hidden),
        _action("viewed", "seen", t("act_viewed"), marks.viewed),
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


def _action(name: str, css: str, label: str, pressed: bool) -> str:
    text = escape(label)
    return (
        f'<button type="button" class="act {css}" data-act="{name}" '
        f'aria-pressed="{"true" if pressed else "false"}" aria-label="{text}" '
        f'title="{text}">{_ICONS[css]}</button>'
    )


def _label(t: Translator, prefix: str, value: str) -> str:
    try:
        return t(prefix + value)
    except KeyError:
        return value
