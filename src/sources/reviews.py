"""Company reviews from DOU.

Written reviews on a company page have no numeric mark. The number DOU publishes
is the employee survey, out of 100, shown beside those reviews. A company is
used only when its DOU name matches, or when a vacancy already links to that
company page.
"""

from __future__ import annotations

import re
import urllib.parse

from core.models import CompanyReview, ReviewSource
from network.client import Client

_CARD = re.compile(r'<li class="l-company">(.*?)</li>', re.S)
_NAME = re.compile(
    r'<a class="cn-a" href="https://jobs\.dou\.ua/companies/([^"/]+)/"[^>]*>(.*?)</a>',
    re.S,
)
_COUNT = re.compile(r'id="lblCommentsCount">\s*(\d+)')
_SCORE = re.compile(r"Оцінка компанії:\s*(\d+)\s*/\s*100")
_VOTES = re.compile(r'Проголосувало\s*<a href="[^"]*">\s*(\d+)\s*співробітник', re.S)
_SLUG = re.compile(r"https://jobs\.dou\.ua/companies/([^/?#]+)/", re.I)
_SLUG_TEXT = re.compile(r"[A-Za-z0-9-]{1,120}")
# Legal endings that job boards append and DOU often keeps on the company title.
_SUFFIXES = frozenset(
    {
        "inc",
        "llc",
        "ltd",
        "limited",
        "corp",
        "corporation",
        "gmbh",
        "тов",
        "фоп",
        "прат",
        "пат",
        "ат",
    }
)


def fetch_company_review(client: Client, name: str, dou_url: str = "") -> CompanyReview | None:
    """The DOU survey score and review links, or None when no company matches."""
    slug = slug_from_url(dou_url) or _find_slug(client, name)
    if not slug:
        return None
    page = f"https://jobs.dou.ua/companies/{slug}/reviews/"
    html = client.get_text(page, referer="https://jobs.dou.ua/companies/")
    return parse_reviews_page(html, slug)


def slug_from_url(url: str) -> str:
    match = _SLUG.search(url or "")
    if match is None:
        return ""
    slug = match.group(1)
    if _SLUG_TEXT.fullmatch(slug) is None:
        return ""
    return slug


def match_slug(html: str, name: str) -> str | None:
    """The one company card whose title matches ``name``. Several matches are left unused."""
    wanted = match_key(name)
    if not wanted:
        return None
    found: list[str] = []
    for card in _CARD.findall(html):
        name_match = _NAME.search(card)
        if name_match is None:
            continue
        slug, label = name_match.group(1), _text(name_match.group(2))
        if _SLUG_TEXT.fullmatch(slug) is None or match_key(label) != wanted:
            continue
        if slug not in found:
            found.append(slug)
    if len(found) == 1:
        return found[0]
    return None


def parse_reviews_page(html: str, slug: str) -> CompanyReview | None:
    """Score, review count, and links. None when the page has neither a count nor a score."""
    if _SLUG_TEXT.fullmatch(slug) is None:
        return None
    count_match = _COUNT.search(html)
    score_match = _SCORE.search(html)
    if count_match is None and score_match is None:
        return None
    review_count = int(count_match.group(1)) if count_match else 0
    rating = int(score_match.group(1)) if score_match else None
    if rating is not None and not 0 <= rating <= 100:
        rating = None
    votes_match = _VOTES.search(html)
    voter_count = int(votes_match.group(1)) if votes_match else 0
    base = f"https://jobs.dou.ua/companies/{slug}/"
    reviews_url = base + "reviews/" if review_count else ""
    poll_url = base + "poll/" if rating is not None else ""
    score = f"{rating}/100" if rating is not None else ""
    return CompanyReview(
        rating=rating,
        review_count=review_count,
        voter_count=voter_count,
        reviews_url=reviews_url,
        poll_url=poll_url,
        profile_url=base,
        sources=(
            ReviewSource(
                source="DOU",
                rating=rating,
                score=score,
                review_count=review_count,
                voter_count=voter_count,
                reviews_url=reviews_url,
                poll_url=poll_url,
            ),
        ),
    )


def _find_slug(client: Client, name: str) -> str | None:
    if not name.strip():
        return None
    url = "https://jobs.dou.ua/companies/?" + urllib.parse.urlencode({"name": name})
    html = client.get_text(url, referer="https://jobs.dou.ua/companies/")
    return match_slug(html, name)


def match_key(name: str) -> str:
    folded = name.casefold().replace("\xa0", " ").replace("-", " ")
    folded = re.sub(r"[^\w\s]", " ", folded, flags=re.UNICODE)
    tokens = folded.split()
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _text(fragment: str) -> str:
    stripped = re.sub(r"<[^>]+>", " ", fragment or "")
    return re.sub(r"\s+", " ", stripped).replace("\xa0", " ").strip()
