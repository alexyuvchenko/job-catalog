from __future__ import annotations

import re
import urllib.parse

from jobsearch.classify import parse_relative_date, parse_salary, parse_years
from jobsearch.http.browser import Browser
from jobsearch.http.client import FetchError
from jobsearch.models import Job, Listing

_CARDS = """() => [...document.querySelectorAll('.job-link')].map((card) => {
  const link = card.querySelector('h2 a');
  if (!link) return null;
  const company = card.querySelector('.strong-600');
  const time = card.querySelector('time');
  const lines = [...card.querySelectorAll('.text-indent')].map((el) => el.innerText.replace(/\\s+/g, ' ').trim());
  const snippet = card.querySelector('p');
  return {
    href: link.getAttribute('href') || '',
    title: link.innerText.replace(/\\s+/g, ' ').trim(),
    company: company ? company.innerText.replace(/\\s+/g, ' ').trim() : '',
    lines,
    published: time ? (time.getAttribute('datetime') || '') : '',
    salary: (card.innerText.match(/\\d[\\d\\s]{0,12}(?:грн|₴|\\$|USD)/i) || [''])[0],
    snippet: snippet ? snippet.innerText.replace(/\\s+/g, ' ').trim() : '',
    reserved: !!card.querySelector('.glyphicon-deferment')
  };
}).filter(Boolean)"""


def search_url(keyword: str, page: int) -> str:
    if keyword.strip():
        params = {
            "search": keyword.strip(),
            "region": "60",
            "industry": "21331",
            "deferment": "1",
        }
    else:
        params = {"deferment": "1"}
    if page > 1:
        params["page"] = str(page)
    base = (
        "https://www.work.ua/jobs/"
        if keyword.strip()
        else "https://www.work.ua/jobs-remote-industry-it/"
    )
    return base + "?" + urllib.parse.urlencode(params)


def fetch_jobs(browser: Browser, keyword: str, pages: int) -> Listing:
    found: list[Job] = []
    seen: set[str] = set()
    stopped = False
    for page in range(1, pages + 1):
        try:
            browser.goto(search_url(keyword, page), selector=".job-link")
        except FetchError:
            if page == 1:
                raise
            stopped = True
            break
        cards = browser.evaluate(_CARDS) or []
        fresh = []
        for card in cards:
            job = job_from_card(card)
            if job is None or job.job_id in seen:
                continue
            seen.add(job.job_id)
            fresh.append(job)
        if not fresh:
            break
        found.extend(fresh)
    message = f"прочитано {len(found)} за фільтром «Бронювання працівників»"
    if stopped:
        message += "; наступні сторінки не відкрились, тож попередні вакансії Work.ua не знімаються"
    return Listing(found, message, complete=not stopped)


def job_from_card(card: dict) -> Job | None:
    if not card.get("reserved"):
        return None
    href = card.get("href") or ""
    match = re.search(r"/jobs/(\d+)", href)
    if not match:
        return None
    location = _location(card.get("lines") or [])
    conditions = _conditions(card.get("lines") or [])
    salary_text = (card.get("salary") or "").strip()
    salary_min, salary_max, currency = parse_salary(salary_text)
    url = "https://www.work.ua" + href if href.startswith("/") else href.split("?")[0]
    return Job(
        source="Work.ua",
        job_id=match.group(1),
        title=card.get("title") or "",
        company=card.get("company") or "",
        company_url="",
        url=url,
        location=location,
        remote=_remote(location),
        salary_min=salary_min,
        salary_max=salary_max,
        currency=currency,
        salary_text=salary_text,
        category="IT",
        english="",
        years=parse_years(conditions),
        published=parse_relative_date(card.get("published") or ""),
        reservation="confirmed",
        evidence="",
        snippet=(card.get("snippet") or "")[:280],
    )


def _location(lines: list[str]) -> str:
    for line in lines:
        if re.search(r"дистанц|віддален|remote", line, re.I):
            return re.sub(r"\s+", " ", line).strip()
    return lines[0].strip() if lines else ""


def _conditions(lines: list[str]) -> str:
    for line in lines:
        if re.search(r"досвід|рок", line, re.I):
            return line
    return ""


def _remote(location: str) -> str:
    text = location.lower()
    if "дистанц" not in text and "віддален" not in text and "remote" not in text:
        return "remote"
    rest = re.sub(r"дистанційно|віддалено|remote", "", text, flags=re.I)
    rest = re.sub(r"[\s,·]+", "", rest)
    return "hybrid" if rest else "full"
