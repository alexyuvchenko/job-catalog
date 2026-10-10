from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from jobsearch.classify import accept_remote, detect_language, english_meets, salary_meets
from jobsearch.db.sqlite import connect
from jobsearch.models import Job, SourceStatus
from jobsearch.paths import CATALOG_PATH

# A job counts as changed only when one of these differs. Dates and snippets are left out:
# relative dates such as "2 weeks ago" shift every day without the vacancy changing.
TRACKED_FIELDS = (
    "title",
    "company",
    "location",
    "remote",
    "salary_min",
    "salary_max",
    "currency",
    "salary_text",
    "reservation",
    "english",
    "years",
    "category",
)

MINE_CHOICES = ("", "all", "favorites", "unviewed", "viewed", "rated", "hidden")
CHANGE_CHOICES = ("", "added", "changed", "closed")
LANGUAGE_CHOICES = ("", "en", "uk")
MAX_RATING = 5


@dataclass
class CatalogFilters:
    text: str = ""
    source: str = ""
    full_remote_only: bool = False
    min_salary: int | None = None
    english: str = ""
    min_years: float | None = None
    include_inactive: bool = False
    # Personal marks. "" hides jobs marked "not for me"; "all" shows everything.
    mine: str = ""
    min_rating: int | None = None
    # What the latest refresh did: added, changed, or closed vacancies.
    change: str = ""
    # Language of the description: "en" or "uk".
    language: str = ""


@dataclass
class MergeStats:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    deactivated: int = 0


@dataclass
class JobMarks:
    favorite: bool = False
    hidden: bool = False
    rating: int = 0
    viewed_at: str = ""

    @property
    def viewed(self) -> bool:
        return bool(self.viewed_at)


@dataclass
class StoredJob:
    job: Job
    active: bool
    first_seen: str
    last_seen: str
    marks: JobMarks = field(default_factory=JobMarks)
    changed_at: str = ""
    changes: tuple[str, ...] = ()
    closed_at: str = ""
    # What the latest refresh did to this vacancy.
    changed_now: bool = False
    closed_now: bool = False
    language: str = ""

    @property
    def change(self) -> str:
        """The latest refresh's effect on this vacancy: closed, added, changed, or ''."""
        if self.closed_now:
            return "closed"
        if self.job.is_new:
            return "added"
        if self.changed_now:
            return "changed"
        return ""


class Catalog:
    def __init__(self, path: Path = CATALOG_PATH) -> None:
        self.path = path
        self._schema_ready = False

    def merge(
        self,
        jobs: list[Job],
        statuses: list[SourceStatus],
        started_at: str,
        finished_at: str,
    ) -> MergeStats:
        stats = MergeStats()
        with self._session() as connection:
            for status in statuses:
                if not status.ok:
                    continue
                incoming = [job for job in jobs if job.source == status.name]
                if not incoming:
                    continue
                seen: set[str] = set()
                for job in incoming:
                    if job.url in seen:
                        continue
                    seen.add(job.url)
                    outcome = self._upsert(connection, job, finished_at)
                    if outcome == "added":
                        stats.added += 1
                    elif outcome == "changed":
                        stats.updated += 1
                    else:
                        stats.unchanged += 1
                placeholders = ",".join("?" for _ in seen)
                if status.complete:
                    cursor = connection.execute(
                        f"""
                        UPDATE jobs
                        SET active = 0, closed_at = ?
                        WHERE source = ? AND active = 1 AND url NOT IN ({placeholders})
                        """,
                        (finished_at, status.name, *seen),
                    )
                    stats.deactivated += cursor.rowcount
            cursor = connection.execute(
                """
                INSERT INTO refreshes (started_at, finished_at, ok, added, updated, deactivated, error)
                VALUES (?, ?, 1, ?, ?, ?, '')
                """,
                (started_at, finished_at, stats.added, stats.updated, stats.deactivated),
            )
            refresh_id = cursor.lastrowid
            connection.executemany(
                """
                INSERT INTO source_runs (refresh_id, name, ok, message, fetched, kept, complete)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        refresh_id,
                        status.name,
                        int(status.ok),
                        status.message,
                        status.fetched,
                        status.kept,
                        int(status.complete),
                    )
                    for status in statuses
                ],
            )
        return stats

    def record_failure(self, started_at: str, finished_at: str, error: str) -> None:
        with self._session() as connection:
            connection.execute(
                """
                INSERT INTO refreshes (started_at, finished_at, ok, error)
                VALUES (?, ?, 0, ?)
                """,
                (started_at, finished_at, error[:500]),
            )

    def list_jobs(self, filters: CatalogFilters) -> list[StoredJob]:
        cutoff = self._new_cutoff()
        found: list[StoredJob] = []
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT jobs.*,
                       COALESCE(s.favorite, 0) AS favorite,
                       COALESCE(s.hidden, 0) AS hidden,
                       COALESCE(s.rating, 0) AS rating,
                       COALESCE(s.viewed_at, '') AS viewed_at
                FROM jobs LEFT JOIN job_states s ON s.url = jobs.url
                ORDER BY jobs.published DESC, jobs.salary_max DESC, jobs.title
                """
            ).fetchall()
        for row in rows:
            stored = _stored(row, cutoff)
            if _visible(stored, filters):
                found.append(stored)
        return found

    def set_marks(
        self,
        url: str,
        *,
        favorite: bool | None = None,
        hidden: bool | None = None,
        rating: int | None = None,
        viewed: bool | None = None,
    ) -> JobMarks | None:
        """Change what you noted about one vacancy. Returns None for an unknown vacancy."""
        if rating is not None and not 0 <= rating <= MAX_RATING:
            raise ValueError(f"rating must be from 0 to {MAX_RATING}")
        with self._session() as connection:
            # Two quick clicks arrive as two requests. Taking the write lock before reading
            # keeps the second from overwriting the first with stale values.
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM jobs WHERE url = ?", (url,)).fetchone() is None:
                return None
            row = connection.execute(
                "SELECT favorite, hidden, rating, viewed_at FROM job_states WHERE url = ?",
                (url,),
            ).fetchone()
            marks = (
                JobMarks()
                if row is None
                else JobMarks(bool(row[0]), bool(row[1]), int(row[2]), row[3])
            )
            if favorite is not None:
                marks.favorite = favorite
                if favorite:
                    marks.hidden = False
            if hidden is not None:
                marks.hidden = hidden
                if hidden:
                    marks.favorite = False
            if rating is not None:
                marks.rating = rating
            if viewed is not None:
                marks.viewed_at = (marks.viewed_at or now_stamp()) if viewed else ""
            connection.execute(
                """
                INSERT INTO job_states (url, favorite, hidden, rating, viewed_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    favorite = excluded.favorite,
                    hidden = excluded.hidden,
                    rating = excluded.rating,
                    viewed_at = excluded.viewed_at,
                    updated_at = excluded.updated_at
                """,
                (
                    url,
                    int(marks.favorite),
                    int(marks.hidden),
                    marks.rating,
                    marks.viewed_at,
                    now_stamp(),
                ),
            )
        return marks

    def counts(self) -> tuple[int, int]:
        with self._session() as connection:
            active = connection.execute("SELECT COUNT(*) FROM jobs WHERE active = 1").fetchone()[0]
            inactive = connection.execute("SELECT COUNT(*) FROM jobs WHERE active = 0").fetchone()[
                0
            ]
        return active, inactive

    def latest_statuses(self) -> tuple[list[SourceStatus], str, int, int, int]:
        with self._session() as connection:
            refresh = connection.execute(
                """
                SELECT id, finished_at, added, updated, deactivated
                FROM refreshes
                WHERE ok = 1 AND finished_at IS NOT NULL
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            if refresh is None:
                return [], "", 0, 0, 0
            runs = connection.execute(
                """
                SELECT name, ok, message, fetched, kept, complete
                FROM source_runs WHERE refresh_id = ? ORDER BY rowid
                """,
                (refresh["id"],),
            ).fetchall()
            finished_at = refresh["finished_at"]
            added = refresh["added"]
            updated = refresh["updated"]
            deactivated = refresh["deactivated"]
            run_rows = [
                (
                    run["name"],
                    bool(run["ok"]),
                    run["message"],
                    run["fetched"],
                    run["kept"],
                    bool(run["complete"]),
                )
                for run in runs
            ]
        statuses = [
            SourceStatus(
                name=name, ok=ok, message=message, fetched=fetched, kept=kept, complete=complete
            )
            for name, ok, message, fetched, kept, complete in run_rows
        ]
        return statuses, finished_at, added, updated, deactivated

    def _new_cutoff(self) -> str:
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT started_at FROM refreshes
                WHERE ok = 1 AND finished_at IS NOT NULL
                ORDER BY id DESC
                LIMIT 2
                """
            ).fetchall()
            if len(rows) < 2:
                return ""
            return rows[0]["started_at"]

    def _upsert(self, connection: sqlite3.Connection, job: Job, seen_at: str) -> str:
        """Store one vacancy. Returns "added", "changed", or "same"."""
        existing = connection.execute(
            f"SELECT active, {', '.join(TRACKED_FIELDS)} FROM jobs WHERE url = ?", (job.url,)
        ).fetchone()
        if existing is None:
            connection.execute(
                """
                INSERT INTO jobs (
                    url, source, job_id, title, company, company_url, location, remote,
                    salary_min, salary_max, currency, salary_text, category, english, years,
                    published, reservation, evidence, snippet, active, first_seen, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                _values(job) + (seen_at, seen_at),
            )
            return "added"
        changes = [name for name in TRACKED_FIELDS if existing[name] != getattr(job, name)]
        if not existing["active"]:
            changes.append("active")
        connection.execute(
            """
            UPDATE jobs SET
                source = ?, job_id = ?, title = ?, company = ?, company_url = ?, location = ?,
                remote = ?, salary_min = ?, salary_max = ?, currency = ?, salary_text = ?,
                category = ?, english = ?, years = ?, published = ?, reservation = ?,
                evidence = ?, snippet = ?, active = 1, closed_at = '', last_seen = ?
            WHERE url = ?
            """,
            (
                job.source,
                job.job_id,
                job.title,
                job.company,
                job.company_url,
                job.location,
                job.remote,
                job.salary_min,
                job.salary_max,
                job.currency,
                job.salary_text,
                job.category,
                job.english,
                job.years,
                job.published,
                job.reservation,
                job.evidence,
                job.snippet,
                seen_at,
                job.url,
            ),
        )
        if not changes:
            return "same"
        connection.execute(
            "UPDATE jobs SET changed_at = ?, changes = ? WHERE url = ?",
            (seen_at, ",".join(changes), job.url),
        )
        return "changed"

    @contextmanager
    def _session(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = connect(self.path)
        if self._schema_ready:
            return connection
        try:
            self._prepare(connection)
        except Exception:
            connection.close()
            raise
        self._schema_ready = True
        return connection

    def _prepare(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                url TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                job_id TEXT NOT NULL,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                company_url TEXT NOT NULL,
                location TEXT NOT NULL,
                remote TEXT NOT NULL,
                salary_min INTEGER,
                salary_max INTEGER,
                currency TEXT,
                salary_text TEXT NOT NULL,
                category TEXT NOT NULL,
                english TEXT NOT NULL,
                years REAL,
                published TEXT NOT NULL,
                reservation TEXT NOT NULL,
                evidence TEXT NOT NULL,
                snippet TEXT NOT NULL,
                active INTEGER NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                changed_at TEXT NOT NULL DEFAULT '',
                changes TEXT NOT NULL DEFAULT '',
                closed_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS refreshes (
                id INTEGER PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                ok INTEGER NOT NULL DEFAULT 0,
                added INTEGER NOT NULL DEFAULT 0,
                updated INTEGER NOT NULL DEFAULT 0,
                deactivated INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS source_runs (
                refresh_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                ok INTEGER NOT NULL,
                message TEXT NOT NULL,
                fetched INTEGER NOT NULL,
                kept INTEGER NOT NULL,
                complete INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS job_states (
                url TEXT PRIMARY KEY REFERENCES jobs(url) ON DELETE CASCADE,
                favorite INTEGER NOT NULL DEFAULT 0,
                hidden INTEGER NOT NULL DEFAULT 0,
                rating INTEGER NOT NULL DEFAULT 0 CHECK (rating BETWEEN 0 AND 5),
                viewed_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS jobs_source_active ON jobs(source, active);
            CREATE INDEX IF NOT EXISTS jobs_published ON jobs(published);
            """
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(source_runs)")}
        if "complete" not in columns:
            connection.execute(
                "ALTER TABLE source_runs ADD COLUMN complete INTEGER NOT NULL DEFAULT 1"
            )
            connection.execute(
                "UPDATE source_runs SET complete = 0 WHERE message LIKE '%не знімаються%'"
            )
        job_columns = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)")}
        for name in ("changed_at", "changes", "closed_at"):
            if name not in job_columns:
                connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        connection.commit()


def _values(job: Job) -> tuple:
    return (
        job.url,
        job.source,
        job.job_id,
        job.title,
        job.company,
        job.company_url,
        job.location,
        job.remote,
        job.salary_min,
        job.salary_max,
        job.currency,
        job.salary_text,
        job.category,
        job.english,
        job.years,
        job.published,
        job.reservation,
        job.evidence,
        job.snippet,
    )


def _stored(row: sqlite3.Row, cutoff: str) -> StoredJob:
    first_seen = row["first_seen"]
    changed_at = row["changed_at"]
    closed_at = row["closed_at"]
    active = bool(row["active"])
    job = Job(
        source=row["source"],
        job_id=row["job_id"],
        title=row["title"],
        company=row["company"],
        company_url=row["company_url"],
        url=row["url"],
        location=row["location"],
        remote=row["remote"],
        salary_min=row["salary_min"],
        salary_max=row["salary_max"],
        currency=row["currency"],
        salary_text=row["salary_text"],
        category=row["category"],
        english=row["english"],
        years=row["years"],
        published=row["published"],
        reservation=row["reservation"],
        evidence=row["evidence"],
        snippet=row["snippet"],
        is_new=bool(cutoff) and first_seen >= cutoff,
    )
    return StoredJob(
        job=job,
        active=active,
        first_seen=first_seen,
        last_seen=row["last_seen"],
        marks=JobMarks(
            favorite=bool(row["favorite"]),
            hidden=bool(row["hidden"]),
            rating=int(row["rating"]),
            viewed_at=row["viewed_at"],
        ),
        changed_at=changed_at,
        changes=tuple(name for name in row["changes"].split(",") if name),
        closed_at=closed_at,
        changed_now=bool(cutoff) and bool(changed_at) and changed_at >= cutoff,
        closed_now=bool(cutoff) and not active and bool(closed_at) and closed_at >= cutoff,
        language=detect_language(row["snippet"]),
    )


def _visible(stored: StoredJob, filters: CatalogFilters) -> bool:
    if not stored.active and not filters.include_inactive and filters.change != "closed":
        return False
    if not _mine_matches(stored.marks, filters.mine):
        return False
    if filters.min_rating is not None and stored.marks.rating < filters.min_rating:
        return False
    if filters.change and stored.change != filters.change:
        return False
    if filters.language and stored.language != filters.language:
        return False
    job = stored.job
    if filters.source and job.source != filters.source:
        return False
    if filters.text:
        blob = " ".join((job.title, job.company, job.location, job.snippet, job.category)).lower()
        if filters.text.lower() not in blob:
            return False
    if not accept_remote(job.remote, filters.full_remote_only):
        return False
    if not salary_meets(job, filters.min_salary):
        return False
    if not english_meets(job.english, filters.english):
        return False
    if filters.min_years is not None and job.years is not None and job.years < filters.min_years:
        return False
    return True


def _mine_matches(marks: JobMarks, choice: str) -> bool:
    if choice == "all":
        return True
    if choice == "hidden":
        return marks.hidden
    if marks.hidden:
        return False
    if choice == "favorites":
        return marks.favorite
    if choice == "unviewed":
        return not marks.viewed
    if choice == "viewed":
        return marks.viewed
    if choice == "rated":
        return marks.rating > 0
    return True


def now_stamp() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")
