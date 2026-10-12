from __future__ import annotations

import json
import re
import urllib.parse
from html import unescape

from core.classify import (
    evidence_sentence,
    is_it_title,
    parse_english,
    parse_salary,
    parse_years,
    remote_mode_from_meta,
)
from core.models import Job, Listing
from network.client import Client, FetchError

_JSONLD = re.compile(r'<script type="application/ld\+json">', re.I)
_CARD = re.compile(
    r'<div id="job-item-(\d+)" class="job-item\b[^>]*>(.*?)(?=<div id="job-item-|\Z)', re.S
)
_COUNT = re.compile(r"fs-1 fw-bold text-muted[^>]*>\s*(\d+)")


def search_url(page: int, keyword: str) -> str:
    params = {
        "employment": "remote",
        "editorial": "reservation",
        "page": str(page),
    }
    if keyword.strip():
        params["all_keywords"] = keyword.strip()
    return "https://djinni.co/jobs/?" + urllib.parse.urlencode(params)


def fetch_jobs(client: Client, keyword: str, pages: int) -> Listing:
    found: list[Job] = []
    seen_ids: set[str] = set()
    total: int | None = None
    stopped = False
    for page in range(1, pages + 1):
        url = search_url(page, keyword)
        try:
            html = client.get_text(url)
        except FetchError:
            if page == 1:
                raise
            stopped = True
            break
        jobs, page_total = parse_djinni_html(html)
        if page_total is not None:
            total = page_total
        fresh = [job for job in jobs if job.job_id not in seen_ids]
        if not fresh:
            break
        seen_ids.update(job.job_id for job in fresh)
        found.extend(job for job in fresh if is_it_title(job.title))
        if total is not None and len(seen_ids) >= total:
            break
        if len(jobs) < 10:
            break
    if total is not None:
        message = f"read {len(found)} IT jobs from about {total} remote jobs with reservation"
    else:
        message = f"read {len(found)} remote IT jobs with reservation"
    if stopped:
        message += "; later pages did not open, so previous Djinni vacancies are not closed"
    return Listing(found, message, complete=not stopped)


def parse_djinni_html(html: str) -> tuple[list[Job], int | None]:
    postings = _load_postings(html)
    cards = {job_id: body for job_id, body in _CARD.findall(html)}
    count_match = _COUNT.search(html)
    total = int(count_match.group(1)) if count_match else None
    jobs: list[Job] = []
    for posting in postings:
        if posting.get("@type") != "JobPosting":
            continue
        url = posting.get("url") or ""
        job_id = str(posting.get("identifier") or _id_from_url(url))
        card = cards.get(job_id, "")
        meta = _meta_text(card)
        location = _location_text(card) or _region(posting)
        organization = posting.get("hiringOrganization") or {}
        company = _clean(organization.get("name") or "")
        if not company:
            company = _company_from_card(card)
        description = _clean(posting.get("description") or "")
        salary_text = _salary_text(card)
        salary_min, salary_max, currency = _salary_from_posting(posting)
        if salary_min is None and salary_max is None:
            salary_min, salary_max, currency = parse_salary(salary_text)
        elif not salary_text:
            salary_text = _format_salary(salary_min, salary_max, currency)
        months = _months(posting.get("experienceRequirements"))
        years = round(months / 12.0, 1) if months else parse_years(meta)
        published = (posting.get("datePosted") or "")[:10]
        jobs.append(
            Job(
                source="Djinni",
                job_id=job_id,
                title=_clean(posting.get("title") or "") or _title_from_card(card),
                company=company,
                company_url=organization.get("sameAs") or "",
                url=url,
                location=location,
                remote=_remote_mode(meta, location),
                salary_min=salary_min,
                salary_max=salary_max,
                currency=currency,
                salary_text=salary_text,
                category=_clean(posting.get("category") or ""),
                english=parse_english(meta),
                years=years,
                published=published,
                reservation="confirmed",
                evidence=evidence_sentence(description),
                snippet=description[:280],
            )
        )
    return jobs, total


def _load_postings(html: str) -> list[dict]:
    postings: list[dict] = []
    decoder = json.JSONDecoder()
    for match in _JSONLD.finditer(html):
        rest = html[match.end() :].lstrip()
        try:
            payload, _ = decoder.raw_decode(rest)
        except json.JSONDecodeError:
            continue
        items = payload if isinstance(payload, list) else [payload]
        postings.extend(
            item for item in items if isinstance(item, dict) and item.get("@type") == "JobPosting"
        )
    return postings


def _id_from_url(url: str) -> str:
    match = re.search(r"/jobs/(\d+)", url)
    return match.group(1) if match else url


def _meta_text(card: str) -> str:
    match = re.search(r'class="fw-medium[^"]*"(.*?)</div>', card, re.S)
    return _clean(match.group(1) if match else card[:1500])


def _location_text(card: str) -> str:
    match = re.search(r'class="location-text">([^<]+)', card)
    return _clean(match.group(1) if match else "")


def _company_from_card(card: str) -> str:
    match = re.search(r'font-weight-500">(.*?)</span>', card, re.S)
    return _clean(match.group(1) if match else "")


def _title_from_card(card: str) -> str:
    match = re.search(r"job-item__position[^>]*>(.*?)</h2>", card, re.S)
    return _clean(match.group(1) if match else "")


def _salary_text(card: str) -> str:
    match = re.search(r'text-success text-nowrap">(.*?)</span>', card, re.S)
    return _clean(match.group(1) if match else "")


def _remote_mode(meta: str, location: str) -> str:
    # The request already asks Djinni for remote jobs. A missing label still
    # means the posting passed that filter; hybrid and office labels stay as written.
    mode = remote_mode_from_meta(meta, location)
    return "remote" if mode == "unknown" else mode


def _region(posting: dict) -> str:
    requirements = posting.get("applicantLocationRequirements") or {}
    address = requirements.get("address") or {}
    return _clean(address.get("addressRegion") or address.get("addressCountry") or "")


def _months(value) -> float | None:
    if isinstance(value, dict):
        months = value.get("monthsOfExperience")
        if isinstance(months, (int, float)):
            return float(months)
    return None


def _salary_from_posting(posting: dict) -> tuple[int | None, int | None, str | None]:
    base = posting.get("baseSalary") or {}
    value = base.get("value") or {}
    currency = base.get("currency") or None
    minimum = _amount(value.get("minValue"))
    maximum = _amount(value.get("maxValue"))
    if minimum is None and maximum is None:
        minimum = maximum = _amount(value.get("value"))
    return minimum, maximum, currency


def _amount(value) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _format_salary(minimum: int | None, maximum: int | None, currency: str | None) -> str:
    symbol = {"USD": "$", "EUR": "€", "UAH": "₴"}.get(currency or "", "")
    if minimum and maximum and minimum != maximum:
        return f"{symbol}{minimum}–{maximum}"
    if maximum and not minimum:
        return f"до {symbol}{maximum}"
    if minimum and not maximum:
        return f"від {symbol}{minimum}"
    if minimum:
        return f"{symbol}{minimum}"
    return ""


def _clean(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return unescape(re.sub(r"\s+", " ", text)).strip()
