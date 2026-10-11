from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from core.classify import accept_remote, english_meets, is_it_role, salary_meets
from core.models import Job, Listing, SourceStatus
from core.paths import CACHE_PATH
from network.browser import Browser, BrowserError
from network.client import Client, FetchError
from sources.djinni import fetch_jobs as fetch_djinni
from sources.dou import fetch_jobs as fetch_dou
from sources.dou import verify_reservation
from sources.jooble import fetch_jobs as fetch_jooble
from sources.robota import fetch_jobs as fetch_robota
from sources.workua import fetch_jobs as fetch_workua
from storage.sqlite import session


@dataclass
class Query:
    keyword: str = ""
    pages: int = 2
    focus: str = "engineering"
    full_remote_only: bool = False
    min_salary: int | None = None
    english: str = ""
    min_years: float | None = None
    since_days: int | None = None
    verify: bool = True
    refresh: bool = False
    # Someone is at the machine and can finish a "verify you are human" check in Chrome.
    interactive: bool = True


HTTP_SOURCES = (("Djinni", fetch_djinni), ("DOU", fetch_dou))
BROWSER_SOURCES = (("Work.ua", fetch_workua), ("Robota.ua", fetch_robota), ("Jooble", fetch_jooble))
STOPPED = "оновлення зупинено, попередні вакансії лишаються"


def run_search(
    query: Query,
    client: Client | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[list[Job], list[SourceStatus]]:
    client = client or Client()
    collected: list[Job] = []
    statuses: list[SourceStatus] = []

    def stopped() -> bool:
        return cancelled is not None and cancelled()

    if not _walk(
        HTTP_SOURCES,
        lambda fetcher: fetcher(client, query.keyword, query.pages),
        collected,
        statuses,
        stopped,
    ):
        _skip(statuses, [name for name, _fetcher in BROWSER_SOURCES])
    else:
        _collect_browser_sources(query, collected, statuses, stopped)

    filtered = [job for job in collected if _matches(job, query)]
    if query.verify and not stopped():
        filtered, dropped = verify_reservation(client, filtered, CACHE_PATH, query.refresh)
        for status in statuses:
            if status.name == "DOU" and status.ok:
                status.message += f"; без бейджа відсіяно {dropped}"
    elif query.verify and any(job.source == "DOU" for job in filtered):
        # Badge checks are not finished, so leave the previous DOU rows untouched.
        filtered = [job for job in filtered if job.source != "DOU"]
        for status in statuses:
            if status.name == "DOU" and status.ok:
                status.complete = False
                status.message += (
                    "; перевірку бейджа зупинено, тож попередні вакансії DOU не знімаються"
                )
    else:
        for job in filtered:
            if job.source == "DOU":
                job.reservation = "unverified"

    filtered = _mark_new(filtered)
    filtered.sort(
        key=lambda job: (job.published or "0000-00-00", job.salary_max or 0), reverse=True
    )
    for status in statuses:
        status.kept = sum(1 for job in filtered if job.source == status.name)
    return filtered, statuses


def _walk(
    sources: tuple[tuple[str, Callable], ...],
    invoke: Callable,
    collected: list[Job],
    statuses: list[SourceStatus],
    stopped: Callable[[], bool],
) -> bool:
    for index, (name, fetcher) in enumerate(sources):
        if stopped():
            _skip(statuses, [item[0] for item in sources[index:]])
            return False
        _take(name, lambda fetcher=fetcher: invoke(fetcher), collected, statuses)
    return True


def _take(
    name: str,
    call: Callable[[], Listing | tuple],
    collected: list[Job],
    statuses: list[SourceStatus],
) -> None:
    try:
        listing = _as_listing(call())
    except FetchError as exc:
        statuses.append(SourceStatus(name=name, ok=False, message=str(exc), complete=False))
        return
    except Exception as exc:  # one broken source must not discard the others
        statuses.append(
            SourceStatus(name=name, ok=False, message=f"Unexpected error: {exc}", complete=False)
        )
        return
    statuses.append(
        SourceStatus(
            name=name,
            ok=True,
            message=listing.message,
            fetched=len(listing.jobs),
            complete=listing.complete,
        )
    )
    collected.extend(listing.jobs)


def _as_listing(result: Listing | tuple) -> Listing:
    if isinstance(result, Listing):
        return result
    jobs, message = result
    return Listing(list(jobs), str(message), complete="не знімаються" not in str(message))


def _collect_browser_sources(
    query: Query,
    collected: list[Job],
    statuses: list[SourceStatus],
    stopped: Callable[[], bool],
) -> None:
    if stopped():
        _skip(statuses, [name for name, _fetcher in BROWSER_SOURCES])
        return
    try:
        with Browser(interactive=query.interactive) as browser:
            browser.cancelled = stopped
            _walk(
                BROWSER_SOURCES,
                lambda fetcher: fetcher(browser, query.keyword, query.pages),
                collected,
                statuses,
                stopped,
            )
    except BrowserError as exc:
        for name, _fetcher in BROWSER_SOURCES:
            statuses.append(SourceStatus(name=name, ok=False, message=str(exc), complete=False))


def _skip(statuses: list[SourceStatus], names: list[str]) -> None:
    for name in names:
        statuses.append(SourceStatus(name=name, ok=False, message=STOPPED, complete=False))


def _matches(job: Job, query: Query) -> bool:
    if not is_it_role(job.title, job.category, query.focus):
        return False
    if not accept_remote(job.remote, query.full_remote_only):
        return False
    if not salary_meets(job, query.min_salary):
        return False
    if not english_meets(job.english, query.english):
        return False
    if query.min_years is not None and job.years is not None and job.years < query.min_years:
        return False
    if query.since_days is not None and job.published:
        try:
            published = date.fromisoformat(job.published)
        except ValueError:
            published = None
        if published and published < date.today() - timedelta(days=query.since_days):
            return False
    return True


def _mark_new(jobs: list[Job]) -> list[Job]:
    now = datetime.now().isoformat(timespec="seconds")
    with session(CACHE_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS seen (
                url TEXT PRIMARY KEY,
                first_seen TEXT NOT NULL
            )
            """
        )
        known = {row[0] for row in connection.execute("SELECT url FROM seen")}
        for job in jobs:
            job.is_new = bool(known) and job.url not in known
            connection.execute(
                "INSERT OR IGNORE INTO seen (url, first_seen) VALUES (?, ?)",
                (job.url, now),
            )
    return jobs
