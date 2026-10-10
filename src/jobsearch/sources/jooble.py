from __future__ import annotations

import re
import urllib.parse

from jobsearch.classify import evidence_sentence, parse_relative_date, parse_salary
from jobsearch.http.browser import Browser
from jobsearch.http.client import FetchError
from jobsearch.models import Job, Listing

_CARDS = """() => [...document.querySelectorAll('a.job_card_link')].map((link) => {
  let root = link;
  for (let step = 0; step < 8 && root.parentElement; step += 1) {
    if (root.parentElement.querySelectorAll('a.job_card_link').length !== 1) break;
    root = root.parentElement;
  }
  return {
    title: link.innerText.replace(/\\s+/g, ' ').trim(),
    href: link.href,
    text: root.innerText.replace(/\\u00a0/g, ' ')
  };
}).filter((card) => card.title)"""


def search_url(keyword: str, page: int) -> str:
    phrase = "бронювання працівників"
    ukw = phrase if not keyword.strip() else f"{keyword.strip()} {phrase}"
    params = {"rgns": "віддалено", "ukw": ukw, "p": str(page)}
    return "https://ua.jooble.org/SearchResult?" + urllib.parse.urlencode(params)


def fetch_jobs(browser: Browser, keyword: str, pages: int) -> Listing:
    found: list[Job] = []
    seen: set[str] = set()
    scanned = 0
    stopped = False
    for page in range(1, pages + 1):
        try:
            browser.goto(search_url(keyword, page), selector="a.job_card_link")
        except FetchError:
            if page == 1:
                raise
            stopped = True
            break
        cards = browser.evaluate(_CARDS) or []
        scanned += len(cards)
        fresh = []
        for card in cards:
            job = job_from_card(card)
            if job is None or job.job_id in seen:
                continue
            seen.add(job.job_id)
            fresh.append(job)
        if not cards:
            break
        found.extend(fresh)
    message = f"прочитано {scanned} карток; залишено {len(found)}, де в тексті є бронювання"
    if stopped:
        message += "; наступні сторінки не відкрились, тож попередні вакансії Jooble не знімаються"
    return Listing(found, message, complete=not stopped)


def job_from_card(card: dict) -> Job | None:
    text = card.get("text") or ""
    evidence = _reservation_evidence(text)
    if not evidence:
        return None
    href = card.get("href") or ""
    match = re.search(r"/(?:desc|jdp)/(-?\d+)", href)
    if not match:
        return None
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    salary_line = next(
        (line for line in lines if re.search(r"\$|₴|грн|USD|EUR", line) and len(line) <= 40), ""
    )
    salary_min, salary_max, currency = parse_salary(salary_line)
    location = _location(lines)
    published = next(
        (line for line in lines if re.search(r"тому|назад|сьогодні|вчора", line, re.I)), ""
    )
    company = _company(lines, card.get("title") or "")
    return Job(
        source="Jooble",
        job_id=match.group(1),
        title=card.get("title") or "",
        company=company,
        company_url="",
        url=f"https://ua.jooble.org/desc/{match.group(1)}",
        location=location,
        remote="hybrid" if re.search(r"гібрид|hybrid", text, re.I) else "full",
        salary_min=salary_min,
        salary_max=salary_max,
        currency=currency,
        salary_text=salary_line,
        category="",
        english="",
        years=None,
        published=parse_relative_date(published),
        reservation="confirmed",
        evidence=evidence,
        snippet=_snippet(lines, card.get("title") or ""),
    )


def _reservation_evidence(text: str) -> str:
    evidence = evidence_sentence(text)
    if evidence:
        return evidence
    for line in text.splitlines():
        label = line.strip()
        if re.fullmatch(r"бронювання|бронирование(?:\s+сотрудников)?", label, flags=re.I):
            return label
    return ""


def _location(lines: list[str]) -> str:
    for line in lines:
        if re.fullmatch(r"(?:віддалено|дистанційно|remote|віддалена робота)", line, flags=re.I):
            return "Віддалено"
    for line in lines:
        if re.search(r"віддален|дистанц|remote", line, re.I) and len(line) <= 80:
            return line
    return "Віддалено"


def _company(lines: list[str], title: str) -> str:
    for index, line in enumerate(lines):
        if re.fullmatch(r"віддалено|дистанційно|remote", line, flags=re.I) and index:
            candidate = lines[index - 1]
            if candidate != title and not re.search(r"\$|₴|грн|тому|назад", candidate, re.I):
                return candidate
    return ""


def _snippet(lines: list[str], title: str) -> str:
    body = [line for line in lines if line != title and len(line) > 40]
    return (body[0] if body else " ".join(lines))[:280]
