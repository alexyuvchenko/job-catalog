"""Employee reviews from Indeed.

The company search page lists a star rating out of 5. A company is used only
when one result has the same name. When several results share that name, the
one in an information-technology sector is used, and only when it is the only
such result. The stars are also stored out of 100 so they can sit beside DOU.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from html import unescape

from core.models import ReviewSource
from network.browser import Browser, is_browser_check
from network.client import FetchError
from sources.reviews import match_key

_REVIEWS = re.compile(r"/cmp/[A-Za-z0-9_-]+/reviews")
_INITIAL = re.compile(
    r'<script id="comp-initialData" type="application/json">(.*?)</script>',
    re.S,
)
# Indeed's Ukrainian and English labels for an IT employer. A second company
# with the same name is usually in another sector, such as education.
_IT_SECTOR = ("інформац", "information technology", "програмн", "software")


def fetch_indeed_review(browser: Browser, name: str) -> ReviewSource | None:
    """The Indeed star rating and reviews link, or None when no company matches."""
    if not name.strip():
        return None
    query = urllib.parse.urlencode({"q": name, "l": ""})
    browser.goto(
        f"https://ua.indeed.com/companies/search?{query}",
        selector="#comp-initialData",
        human=False,
    )
    if browser.page is None:
        raise FetchError("Indeed did not open")
    html = browser.page.content()
    title = ""
    try:
        title = browser.page.title()
    except Exception:
        title = ""
    if is_browser_check(title, html):
        raise FetchError("the page is asking to verify you are human")
    return parse_indeed_search(html, name)


def parse_indeed_search(html: str, name: str) -> ReviewSource | None:
    """The one matching company, or None when the page lists none or several."""
    data = _initial_data(html)
    if "searchResults" not in data:
        raise FetchError("Indeed did not return company search results")
    wanted = match_key(name)
    if not wanted:
        return None
    matches = []
    for row in data["searchResults"] or []:
        if isinstance(row, dict) and match_key(str(row.get("name") or "")) == wanted:
            matches.append(row)
    chosen = _choose(matches)
    if chosen is None:
        return None
    return _source(chosen)


def _choose(matches: list[dict]) -> dict | None:
    if len(matches) == 1:
        return matches[0]
    it_matches = [row for row in matches if _is_it(row)]
    if len(it_matches) == 1:
        return it_matches[0]
    return None


def _is_it(row: dict) -> bool:
    sectors = " ".join(str(item) for item in row.get("sectors") or []).casefold()
    return any(token in sectors for token in _IT_SECTOR)


def _source(row: dict) -> ReviewSource | None:
    path = str(row.get("reviewsUrl") or "")
    if _REVIEWS.fullmatch(path) is None:
        return None
    review_count = _count(row.get("reviewsCount"))
    rating, score = _hundred(row.get("rating"))
    if rating is None and not review_count:
        return None
    return ReviewSource(
        source="Indeed",
        rating=rating,
        score=score,
        review_count=review_count,
        voter_count=0,
        reviews_url=f"https://ua.indeed.com{path}",
    )


def _initial_data(html: str) -> dict:
    match = _INITIAL.search(html or "")
    if match is None:
        return {}
    try:
        data = json.loads(unescape(match.group(1)))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _count(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    count = int(value)
    if count < 0 or count != value:
        return 0
    return count


def _hundred(value) -> tuple[int | None, str]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, ""
    stars = float(value)
    if not 0 < stars <= 5:
        return None, ""
    rating = round(stars / 5 * 100)
    if not 0 <= rating <= 100:
        return None, ""
    text = f"{stars:.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return rating, f"{text}/5"
