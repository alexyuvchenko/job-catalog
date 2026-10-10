from __future__ import annotations

import re
import sqlite3
import urllib.parse
from dataclasses import dataclass
from html import unescape
from pathlib import Path

from jobsearch.classify import dou_remote_mode, evidence_sentence, parse_dou_date, parse_salary
from jobsearch.db.sqlite import connect
from jobsearch.http.client import Client, FetchError
from jobsearch.models import Job, Listing

_BADGE_FOUND_TTL = "-7 days"
_BADGE_MISSING_TTL = "-1 day"

_ITEM = re.compile(r'<li class="l-vacancy[^"]*">(.*?)</li>', re.S)
_BADGE = re.compile(
    r'href="https://jobs\.dou\.ua/vacancies/\?search=(?:бронювання|%D0%B1%D1%80%D0%BE%D0%BD%D1%8E%D0%B2%D0%B0%D0%BD%D0%BD%D1%8F)(?:&|&amp;)from=badge"',
    re.I,
)


def search_url(keyword: str) -> str:
    query = "бронювання" if not keyword.strip() else f"бронювання {keyword.strip()}"
    return "https://jobs.dou.ua/vacancies/?" + urllib.parse.urlencode(
        {"remote": "", "search": query}
    )


def fetch_jobs(client: Client, keyword: str, pages: int) -> Listing:
    page_url = search_url(keyword)
    html = client.get_text(page_url)
    jobs = parse_dou_html(html)
    seen = {job.job_id for job in jobs}
    total_match = re.search(r"<h1>\s*(\d+)", html)
    total = int(total_match.group(1)) if total_match else None
    shown = len(re.findall(r'class="l-vacancy', html))
    loaded_pages = 1
    last = False
    stopped = ""
    while loaded_pages < pages and not last:
        try:
            host = urllib.parse.urlsplit(page_url).hostname or ""
            payload = client.post_json(
                _xhr_url(page_url),
                {"csrfmiddlewaretoken": client.cookie("csrftoken", host), "count": str(shown)},
                referer=page_url,
            )
        except FetchError as exc:
            stopped = str(exc)
            break
        fragment = payload.get("html") or ""
        batch = parse_dou_html(fragment)
        added = 0
        for job in batch:
            if job.job_id in seen:
                continue
            seen.add(job.job_id)
            jobs.append(job)
            added += 1
        shown += int(payload.get("num") or added or 0)
        last = bool(payload.get("last")) or added == 0
        loaded_pages += 1
    if total is not None:
        message = f"прочитано {len(jobs)} із близько {total} згадок «бронювання»"
    else:
        message = f"прочитано {len(jobs)} згадок «бронювання»"
    if stopped:
        message += "; наступні сторінки не відкрились, тож попередні вакансії DOU не знімаються"
    return Listing(jobs, message, complete=not stopped)


def verify_reservation(
    client: Client, jobs: list[Job], cache_path: Path, refresh: bool
) -> tuple[list[Job], int]:
    """Keep DOU jobs whose vacancy page carries the official бронювання badge."""
    connection = connect(cache_path)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dou_check (
            vacancy_id TEXT PRIMARY KEY,
            has_badge INTEGER NOT NULL,
            evidence TEXT NOT NULL,
            checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    kept: list[Job] = []
    dropped = 0
    try:
        for job in jobs:
            if job.source != "DOU":
                kept.append(job)
                continue
            cached = None if refresh else _cached(connection, job.job_id)
            if cached is not None and not cached.stale:
                has_badge, evidence = cached.has_badge, cached.evidence
            else:
                try:
                    html = client.get_text(job.url, referer="https://jobs.dou.ua/vacancies/")
                except FetchError:
                    if cached is None:
                        job.reservation = "unverified"
                        kept.append(job)
                        continue
                    # The page did not open; the older answer is better than none.
                    has_badge, evidence = cached.has_badge, cached.evidence
                else:
                    has_badge = bool(_BADGE.search(html))
                    evidence = evidence_sentence(_visible_text(html))
                    _store(connection, job.job_id, has_badge, evidence)
            if has_badge:
                job.reservation = "confirmed"
                if evidence:
                    job.evidence = evidence
                kept.append(job)
            else:
                dropped += 1
    finally:
        connection.close()
    return kept, dropped


def parse_dou_html(html: str) -> list[Job]:
    jobs: list[Job] = []
    for body in _ITEM.findall(html):
        href = _first(r'class="vt" href="([^"]+)"', body)
        job_id_match = re.search(r"/vacancies/(\d+)/", href)
        if not job_id_match:
            continue
        title = _text(_first(r'class="vt"[^>]*>(.*?)</a>', body))
        company = _text(_first(r'class="company"[^>]*>(.*?)</a>', body))
        company_url = _first(r'class="company" href="([^"]+)"', body)
        salary_text = _text(_first(r'class="salary"[^>]*>(.*?)</span>', body))
        cities = _text(_first(r'class="cities[^"]*"[^>]*>(.*?)</span>', body))
        snippet = _text(_first(r'class="sh-info"[^>]*>(.*?)</div>', body))
        published = parse_dou_date(_text(_first(r'class="date"[^>]*>(.*?)</div>', body)))
        salary_min, salary_max, currency = parse_salary(salary_text)
        clean_url = href.split("?")[0]
        jobs.append(
            Job(
                source="DOU",
                job_id=job_id_match.group(1),
                title=title,
                company=company,
                company_url=company_url,
                url=clean_url,
                location=cities,
                remote=dou_remote_mode(cities),
                salary_min=salary_min,
                salary_max=salary_max,
                currency=currency,
                salary_text=salary_text,
                category="",
                english="",
                years=None,
                published=published,
                reservation="unverified",
                evidence="",
                snippet=snippet[:280],
            )
        )
    return jobs


def has_reservation_badge(html: str) -> bool:
    return _BADGE.search(html) is not None


def _xhr_url(page_url: str) -> str:
    parsed = urllib.parse.urlsplit(page_url)
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, "/vacancies/xhr-load/", parsed.query, "")
    )


@dataclass
class _Checked:
    has_badge: bool
    evidence: str
    stale: bool


def _cached(connection: sqlite3.Connection, vacancy_id: str) -> _Checked | None:
    """A saved badge answer. A missing badge is rechecked daily, a found one weekly."""
    row = connection.execute(
        """
        SELECT has_badge, evidence,
               checked_at < datetime('now', CASE has_badge WHEN 1 THEN ? ELSE ? END)
        FROM dou_check WHERE vacancy_id = ?
        """,
        (_BADGE_FOUND_TTL, _BADGE_MISSING_TTL, vacancy_id),
    ).fetchone()
    if row is None:
        return None
    return _Checked(bool(row[0]), row[1] or "", bool(row[2]))


def _store(connection: sqlite3.Connection, vacancy_id: str, has_badge: bool, evidence: str) -> None:
    connection.execute(
        """
        INSERT INTO dou_check (vacancy_id, has_badge, evidence)
        VALUES (?, ?, ?)
        ON CONFLICT(vacancy_id) DO UPDATE SET
            has_badge = excluded.has_badge,
            evidence = excluded.evidence,
            checked_at = CURRENT_TIMESTAMP
        """,
        (vacancy_id, int(has_badge), evidence),
    )
    connection.commit()


def _first(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.S)
    return match.group(1) if match else ""


def _text(fragment: str) -> str:
    stripped = re.sub(r"<[^>]+>", " ", fragment or "")
    return unescape(re.sub(r"\s+", " ", stripped)).replace("\xa0", " ").strip()


def _visible_text(html: str) -> str:
    without_scripts = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    without_styles = re.sub(r"<style[\s\S]*?</style>", " ", without_scripts, flags=re.I)
    return _text(without_styles)
