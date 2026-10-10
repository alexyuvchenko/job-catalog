from __future__ import annotations

import json

from jobsearch.classify import evidence_sentence, parse_relative_date, parse_salary
from jobsearch.http.browser import Browser
from jobsearch.http.client import FetchError
from jobsearch.models import Job, Listing

_QUERY = """
query getPublishedVacanciesList(
  $filter: PublishedVacanciesFilterInput!,
  $pagination: PublishedVacanciesPaginationInput!,
  $sort: PublishedVacanciesSortType!
) {
  publishedVacancies(filter: $filter, pagination: $pagination, sort: $sort) {
    totalCount
    items {
      id
      title
      sortDateText
      description
      city { name }
      company { id name }
      salary { amountFrom amountTo comment }
      badges { name }
      schedules { id name }
    }
  }
}
"""

_FETCH = """async ({ query, variables }) => {
  const response = await fetch('https://dracula.robota.ua/graphql', {
    method: 'POST',
    credentials: 'include',
    headers: {
      'content-type': 'application/json',
      'apollo-require-preflight': 'true'
    },
    body: JSON.stringify({
      operationName: 'getPublishedVacanciesList',
      query,
      variables
    })
  });
  return await response.text();
}"""


def fetch_jobs(browser: Browser, keyword: str, pages: int) -> Listing:
    browser.goto("https://robota.ua/zapros/ukraine/params;rubrics=1")
    found: list[Job] = []
    seen: set[str] = set()
    total = None
    stopped = False
    for page in range(pages):
        try:
            payload = _search(browser, keyword, page, with_it_rubric=True)
            if payload is None:
                payload = _search(browser, keyword, page, with_it_rubric=False)
        except FetchError:
            if page == 0:
                raise
            stopped = True
            break
        if payload is None:
            break
        block = (payload.get("data") or {}).get("publishedVacancies") or {}
        if total is None:
            total = block.get("totalCount")
        fresh = []
        for item in block.get("items") or []:
            job = job_from_item(item)
            if job is None or job.job_id in seen:
                continue
            seen.add(job.job_id)
            fresh.append(job)
        if not fresh:
            break
        found.extend(fresh)
        if total is not None and len(found) >= int(total):
            break
    if total is not None:
        message = f"прочитано {len(found)} із близько {total} віддалених вакансій із бронюванням"
    else:
        message = f"прочитано {len(found)} віддалених вакансій із бронюванням"
    if stopped:
        message += (
            "; наступні сторінки не відкрились, тож попередні вакансії Robota.ua не знімаються"
        )
    return Listing(found, message, complete=not stopped)


def job_from_item(item: dict) -> Job | None:
    job_id = str(item.get("id") or "")
    title = (item.get("title") or "").strip()
    if not job_id or not title:
        return None
    schedules = [str((row or {}).get("name") or "") for row in item.get("schedules") or []]
    if "remote" not in schedules:
        return None
    company = item.get("company") or {}
    company_id = str(company.get("id") or "")
    company_name = (company.get("name") or "").strip()
    url = f"https://robota.ua/company{company_id or '0'}/vacancy{job_id}"
    salary = item.get("salary") or {}
    salary_min = _amount(salary.get("amountFrom"))
    salary_max = _amount(salary.get("amountTo"))
    comment = (salary.get("comment") or "").strip()
    parsed_min, parsed_max, parsed_currency = (
        parse_salary(comment) if comment else (None, None, None)
    )
    if salary_min is None and salary_max is None:
        salary_min, salary_max = parsed_min, parsed_max
    salary_text = comment or _salary_text(salary_min, salary_max)
    currency = parsed_currency if comment else ("UAH" if salary_text else None)
    badges = " ".join((badge or {}).get("name") or "" for badge in item.get("badges") or [])
    description = item.get("description") or ""
    city = ((item.get("city") or {}).get("name") or "").strip()
    return Job(
        source="Robota.ua",
        job_id=job_id,
        title=title,
        company=company_name,
        company_url=f"https://robota.ua/company{company_id}" if company_id else "",
        url=url,
        location=city,
        remote="hybrid" if "hybrid" in schedules or "office" in schedules else "full",
        salary_min=salary_min,
        salary_max=salary_max,
        currency=currency,
        salary_text=salary_text,
        category="IT",
        english="",
        years=None,
        published=parse_relative_date(item.get("sortDateText") or ""),
        reservation="confirmed",
        evidence=evidence_sentence(f"{badges} {description}"),
        snippet=_clean(description)[:280],
    )


def _search(browser: Browser, keyword: str, page: int, with_it_rubric: bool) -> dict | None:
    vacancy_filter: dict = {"scheduleIds": ["3"], "isReservation": True}
    if keyword.strip():
        vacancy_filter["keywords"] = keyword.strip()
    if with_it_rubric:
        vacancy_filter["rubrics"] = [{"id": "1", "subrubricIds": []}]
    assert browser.page is not None
    raw = browser.page.evaluate(
        _FETCH,
        {
            "query": _QUERY,
            "variables": {
                "filter": vacancy_filter,
                "pagination": {"page": page, "count": 20},
                "sort": "BY_BUSINESS_SCORE",
            },
        },
    )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FetchError("Robota.ua returned a non-JSON response") from exc
    if payload.get("errors") and with_it_rubric:
        return None
    if payload.get("errors"):
        message = payload["errors"][0].get("message", "GraphQL error")
        raise FetchError(message)
    return payload


def _amount(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    amount = int(value)
    return amount or None


def _salary_text(minimum: int | None, maximum: int | None) -> str:
    if minimum and maximum and minimum != maximum:
        return f"{minimum}–{maximum} грн"
    if minimum or maximum:
        return f"{minimum or maximum} грн"
    return ""


def _clean(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())
