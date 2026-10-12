from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple

from core.classify import detect_language
from core.models import CompanyReview, Job, ReviewSource, SourceStatus
from core.paths import CATALOG_PATH
from storage.filters import MAX_RATING, CatalogFilters, apply_sort, is_visible
from storage.group import company_key, group_same_positions, position_key_parts
from storage.records import JobMarks, MergeStats, StoredJob
from storage.sqlite import connect
from web.auth import (
    DUMMY_HASH,
    AccountError,
    User,
    check_password,
    check_username,
    expires_soon,
    fresh_token,
    hash_password,
    session_expiry,
    token_hash,
    verify_password,
)

# A job counts as changed only when one of these differs. Dates and snippets are left out:
# relative dates such as "2 weeks ago" shift every day without the vacancy changing.
# A found company is read again after a week. A miss or a failed read is tried the next day.
REVIEW_FOUND_TTL = timedelta(days=7)
REVIEW_OTHER_TTL = timedelta(days=1)

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


class CompanyTarget(NamedTuple):
    """One active company that still needs a DOU review lookup."""

    key: str
    name: str
    dou_url: str


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

    def list_jobs(self, filters: CatalogFilters, user_id: int | None = None) -> list[StoredJob]:
        """Vacancies for one account. Without ``user_id`` the shared report has no personal marks."""
        cutoff = self._new_cutoff()
        found: list[StoredJob] = []
        # A missing account must not match the legacy user_id 0 rows.
        owner = user_id if user_id is not None else -1
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT jobs.*,
                       COALESCE(s.favorite, 0) AS favorite,
                       COALESCE(s.hidden, 0) AS hidden,
                       COALESCE(s.rating, 0) AS rating,
                       COALESCE(s.viewed_at, '') AS viewed_at
                FROM jobs LEFT JOIN job_states s ON s.url = jobs.url AND s.user_id = ?
                ORDER BY jobs.published DESC, jobs.salary_max DESC, jobs.title
                """,
                (owner,),
            ).fetchall()
            reviews = _reviews_by_key(connection)
        for row in rows:
            stored = _stored(row, cutoff)
            if is_visible(stored, filters):
                found.append(stored)
        apply_sort(found, filters)
        grouped = group_same_positions(found)
        for item in grouped:
            item.review = reviews.get(company_key(item.job.company))
        return grouped

    def companies_due(self) -> list[CompanyTarget]:
        """Active companies whose reviews are missing or old enough to read again."""
        with self._session() as connection:
            jobs = connection.execute(
                "SELECT company, company_url FROM jobs WHERE active = 1"
            ).fetchall()
            saved = {
                row["company_key"]: (row["status"], row["checked_at"])
                for row in connection.execute(
                    "SELECT company_key, status, checked_at FROM company_reviews"
                )
            }
        targets: dict[str, CompanyTarget] = {}
        for row in jobs:
            key = company_key(row["company"])
            if not key:
                continue
            dou_url = _dou_company_url(row["company_url"])
            current = targets.get(key)
            if current is None:
                targets[key] = CompanyTarget(key, " ".join(row["company"].split()), dou_url)
            elif dou_url and not current.dou_url:
                targets[key] = CompanyTarget(current.key, current.name, dou_url)
        now = datetime.now()
        due = []
        for target in targets.values():
            known = saved.get(target.key)
            if known is None:
                due.append(target)
                continue
            status, checked_at = known
            checked = _parse_stamp(checked_at)
            ttl = REVIEW_FOUND_TTL if status == "found" else REVIEW_OTHER_TTL
            if checked is None or now - checked >= ttl:
                due.append(target)
        due.sort(key=lambda item: item.key)
        return due

    def saved_company_review(self, key: str) -> CompanyReview | None:
        """The review already stored for this company, including one kept after a failed read."""
        with self._session() as connection:
            row = connection.execute(
                "SELECT * FROM company_reviews WHERE company_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return _review_from_row(row)

    def save_company_review(
        self,
        key: str,
        name: str,
        review: CompanyReview | None,
        status: str,
    ) -> None:
        """Store a company lookup. A failed read keeps a score that was already saved."""
        if status not in {"found", "partial", "missing", "error"}:
            raise ValueError(f"unknown review status {status}")
        stamp = now_stamp()
        with self._session() as connection:
            if status == "error":
                connection.execute(
                    """
                    INSERT INTO company_reviews (
                        company_key, name, rating, review_count, voter_count,
                        reviews_url, poll_url, profile_url, sources_json, status, checked_at
                    ) VALUES (?, ?, NULL, 0, 0, '', '', '', '[]', 'error', ?)
                    ON CONFLICT(company_key) DO UPDATE SET checked_at = excluded.checked_at
                    """,
                    (key, name, stamp),
                )
                return
            if status in {"found", "partial"} and review is None:
                status = "missing"
            rating = None if review is None else review.rating
            review_count = 0 if review is None else review.review_count
            voter_count = 0 if review is None else review.voter_count
            reviews_url = "" if review is None else review.reviews_url
            poll_url = "" if review is None else review.poll_url
            profile_url = "" if review is None else review.profile_url
            sources_json = "[]" if review is None else _dump_sources(review.sources)
            connection.execute(
                """
                INSERT INTO company_reviews (
                    company_key, name, rating, review_count, voter_count,
                    reviews_url, poll_url, profile_url, sources_json, status, checked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(company_key) DO UPDATE SET
                    name = excluded.name,
                    rating = excluded.rating,
                    review_count = excluded.review_count,
                    voter_count = excluded.voter_count,
                    reviews_url = excluded.reviews_url,
                    poll_url = excluded.poll_url,
                    profile_url = excluded.profile_url,
                    sources_json = excluded.sources_json,
                    status = excluded.status,
                    checked_at = excluded.checked_at
                """,
                (
                    key,
                    name,
                    rating,
                    review_count,
                    voter_count,
                    reviews_url,
                    poll_url,
                    profile_url,
                    sources_json,
                    status,
                    stamp,
                ),
            )

    def set_marks(
        self,
        url: str,
        user_id: int,
        *,
        favorite: bool | None = None,
        hidden: bool | None = None,
        rating: int | None = None,
        viewed: bool | None = None,
    ) -> JobMarks | None:
        """Change what this account noted about one vacancy. Returns None for an unknown vacancy."""
        if rating is not None and not 0 <= rating <= MAX_RATING:
            raise ValueError(f"rating must be from 0 to {MAX_RATING}")
        with self._session() as connection:
            # Two quick clicks arrive as two requests. Taking the write lock before reading
            # keeps the second from overwriting the first with stale values.
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            job_row = connection.execute(
                "SELECT title, company FROM jobs WHERE url = ?", (url,)
            ).fetchone()
            if job_row is None:
                return None
            row = connection.execute(
                """
                SELECT favorite, hidden, rating, viewed_at FROM job_states
                WHERE user_id = ? AND url = ?
                """,
                (user_id, url),
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
            stamp = now_stamp()
            payload = (
                int(marks.favorite),
                int(marks.hidden),
                marks.rating,
                marks.viewed_at,
                stamp,
            )
            for sibling in _sibling_urls(connection, url, job_row["title"], job_row["company"]):
                connection.execute(
                    """
                    INSERT INTO job_states (user_id, url, favorite, hidden, rating, viewed_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, url) DO UPDATE SET
                        favorite = excluded.favorite,
                        hidden = excluded.hidden,
                        rating = excluded.rating,
                        viewed_at = excluded.viewed_at,
                        updated_at = excluded.updated_at
                    """,
                    (user_id, sibling, *payload),
                )
        return marks

    def create_user(self, username: str, password: str) -> User:
        """Create an account. The first one keeps marks saved before accounts existed."""
        name = check_username(username)
        password_hash = hash_password(check_password(password))
        with self._session() as connection:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            first = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO users (username, username_key, password_hash, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (name, name.casefold(), password_hash, now_stamp()),
                )
            except sqlite3.IntegrityError:
                raise AccountError("username_taken") from None
            user_id = int(cursor.lastrowid)
            if first:
                connection.execute(
                    "UPDATE job_states SET user_id = ? WHERE user_id = 0",
                    (user_id,),
                )
        return User(user_id, name)

    def authenticate(self, username: str, password: str) -> User | None:
        name = username.strip()
        if not name or len(name) > 64 or not isinstance(password, str) or len(password) > 200:
            verify_password("password-check", DUMMY_HASH)
            return None
        with self._session() as connection:
            row = connection.execute(
                "SELECT id, username, password_hash FROM users WHERE username_key = ?",
                (name.casefold(),),
            ).fetchone()
        stored = row["password_hash"] if row is not None else DUMMY_HASH
        if row is None or not verify_password(password, stored):
            return None
        return User(int(row["id"]), row["username"])

    def open_session(self, user_id: int) -> str:
        token = fresh_token()
        now = now_stamp()
        with self._session() as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            connection.execute(
                """
                INSERT INTO sessions (token_hash, user_id, expires_at)
                VALUES (?, ?, ?)
                """,
                (token_hash(token), user_id, session_expiry()),
            )
        return token

    def user_for_session(self, token: str) -> User | None:
        if not token or len(token) > 200:
            return None
        digest = token_hash(token)
        now = now_stamp()
        with self._session() as connection:
            row = connection.execute(
                """
                SELECT users.id AS id, users.username AS username, sessions.expires_at AS expires_at
                FROM sessions JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ?
                """,
                (digest,),
            ).fetchone()
            if row is None:
                return None
            if row["expires_at"] <= now:
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (digest,))
                return None
            if expires_soon(row["expires_at"]):
                connection.execute(
                    "UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
                    (session_expiry(), digest),
                )
            return User(int(row["id"]), row["username"])

    def close_session(self, token: str) -> None:
        if not token:
            return
        with self._session() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (token_hash(token),),
            )

    def save_filters(self, user_id: int, raw: str) -> None:
        if len(raw) > 4000:
            raise ValueError("filters too large")
        with self._session() as connection:
            _touch_prefs(connection, user_id)
            connection.execute(
                "UPDATE user_prefs SET filters = ? WHERE user_id = ?",
                (raw, user_id),
            )

    def saved_filters(self, user_id: int) -> str:
        with self._session() as connection:
            row = connection.execute(
                "SELECT filters FROM user_prefs WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return "" if row is None else row["filters"]

    def save_language(self, user_id: int, language: str) -> None:
        if language not in ("uk", "en"):
            return
        with self._session() as connection:
            _touch_prefs(connection, user_id)
            connection.execute(
                "UPDATE user_prefs SET ui_language = ? WHERE user_id = ?",
                (language, user_id),
            )

    def saved_language(self, user_id: int) -> str:
        with self._session() as connection:
            row = connection.execute(
                "SELECT ui_language FROM user_prefs WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None or row["ui_language"] not in ("uk", "en"):
            return ""
        return row["ui_language"]

    def counts(self) -> tuple[int, int]:
        with self._session() as connection:
            active = connection.execute("SELECT COUNT(*) FROM jobs WHERE active = 1").fetchone()[0]
            inactive = connection.execute("SELECT COUNT(*) FROM jobs WHERE active = 0").fetchone()[
                0
            ]
        return active, inactive

    def user_count(self) -> int:
        with self._session() as connection:
            return connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]

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
                user_id INTEGER NOT NULL DEFAULT 0,
                url TEXT NOT NULL REFERENCES jobs(url) ON DELETE CASCADE,
                favorite INTEGER NOT NULL DEFAULT 0,
                hidden INTEGER NOT NULL DEFAULT 0,
                rating INTEGER NOT NULL DEFAULT 0 CHECK (rating BETWEEN 0 AND 5),
                viewed_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, url)
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                username_key TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS user_prefs (
                user_id INTEGER PRIMARY KEY,
                filters TEXT NOT NULL DEFAULT '',
                ui_language TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS company_reviews (
                company_key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                rating INTEGER,
                review_count INTEGER NOT NULL DEFAULT 0,
                voter_count INTEGER NOT NULL DEFAULT 0,
                reviews_url TEXT NOT NULL DEFAULT '',
                poll_url TEXT NOT NULL DEFAULT '',
                profile_url TEXT NOT NULL DEFAULT '',
                sources_json TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                checked_at TEXT NOT NULL
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
        review_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(company_reviews)")
        }
        if "sources_json" not in review_columns:
            connection.execute(
                "ALTER TABLE company_reviews ADD COLUMN sources_json TEXT NOT NULL DEFAULT ''"
            )
        _migrate_marks(connection)
        connection.commit()


def _touch_prefs(connection: sqlite3.Connection, user_id: int) -> None:
    connection.execute(
        """
        INSERT INTO user_prefs (user_id, filters, ui_language) VALUES (?, '', '')
        ON CONFLICT(user_id) DO NOTHING
        """,
        (user_id,),
    )


def _migrate_marks(connection: sqlite3.Connection) -> None:
    """Marks saved before accounts existed sit on user 0 until the first account is created."""
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(job_states)")}
    if "user_id" in columns:
        return
    connection.commit()
    connection.execute("PRAGMA foreign_keys=OFF")
    connection.executescript(
        """
        CREATE TABLE job_states_v2 (
            user_id INTEGER NOT NULL DEFAULT 0,
            url TEXT NOT NULL REFERENCES jobs(url) ON DELETE CASCADE,
            favorite INTEGER NOT NULL DEFAULT 0,
            hidden INTEGER NOT NULL DEFAULT 0,
            rating INTEGER NOT NULL DEFAULT 0 CHECK (rating BETWEEN 0 AND 5),
            viewed_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, url)
        );
        INSERT INTO job_states_v2 (user_id, url, favorite, hidden, rating, viewed_at, updated_at)
        SELECT 0, url, favorite, hidden, rating, viewed_at, updated_at FROM job_states;
        DROP TABLE job_states;
        ALTER TABLE job_states_v2 RENAME TO job_states;
        """
    )
    connection.execute("PRAGMA foreign_keys=ON")


def _reviews_by_key(connection: sqlite3.Connection) -> dict[str, CompanyReview]:
    """Saved scores worth showing. A company with neither a score nor reviews is left out."""
    found: dict[str, CompanyReview] = {}
    rows = connection.execute("SELECT * FROM company_reviews WHERE status IN ('found', 'partial')")
    for row in rows:
        review = _review_from_row(row)
        if review is not None:
            found[row["company_key"]] = review
    return found


def _review_from_row(row: sqlite3.Row) -> CompanyReview | None:
    sources = _sources_from_row(row)
    if not sources:
        return None
    rating = None if row["rating"] is None else int(row["rating"])
    return CompanyReview(
        rating=rating,
        review_count=int(row["review_count"]),
        voter_count=int(row["voter_count"]),
        reviews_url=row["reviews_url"],
        poll_url=row["poll_url"],
        profile_url=row["profile_url"],
        sources=sources,
    )


def _sources_from_row(row: sqlite3.Row) -> tuple[ReviewSource, ...]:
    raw = row["sources_json"] if "sources_json" in row.keys() else ""
    if not raw:
        return _legacy_sources(row)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return _legacy_sources(row)
    if not isinstance(payload, list):
        return _legacy_sources(row)
    sources = []
    for item in payload:
        source = _source_from_json(item)
        if source is not None:
            sources.append(source)
    return tuple(sources)


def _legacy_sources(row: sqlite3.Row) -> tuple[ReviewSource, ...]:
    """A score saved before Indeed was added is a DOU survey score."""
    rating = None if row["rating"] is None else int(row["rating"])
    review_count = int(row["review_count"])
    reviews_url = row["reviews_url"] or ""
    poll_url = row["poll_url"] or ""
    if rating is None and not review_count and not reviews_url and not poll_url:
        return ()
    score = f"{rating}/100" if rating is not None else ""
    return (
        ReviewSource(
            source="DOU",
            rating=rating,
            score=score,
            review_count=review_count,
            voter_count=int(row["voter_count"]),
            reviews_url=reviews_url,
            poll_url=poll_url,
        ),
    )


def _source_from_json(item) -> ReviewSource | None:
    if not isinstance(item, dict) or item.get("source") not in {"DOU", "Indeed"}:
        return None
    rating = item.get("rating")
    if rating is not None and (isinstance(rating, bool) or not isinstance(rating, int)):
        return None
    if rating is not None and not 0 <= rating <= 100:
        return None
    return ReviewSource(
        source=str(item["source"]),
        rating=rating,
        score=str(item.get("score") or ""),
        review_count=_json_count(item.get("review_count")),
        voter_count=_json_count(item.get("voter_count")),
        reviews_url=str(item.get("reviews_url") or ""),
        poll_url=str(item.get("poll_url") or ""),
    )


def _json_count(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _dump_sources(sources: tuple[ReviewSource, ...]) -> str:
    payload = [
        {
            "source": source.source,
            "rating": source.rating,
            "score": source.score,
            "review_count": source.review_count,
            "voter_count": source.voter_count,
            "reviews_url": source.reviews_url,
            "poll_url": source.poll_url,
        }
        for source in sources
    ]
    return json.dumps(payload, ensure_ascii=False)


def _dou_company_url(url: str) -> str:
    if "https://jobs.dou.ua/companies/" in (url or ""):
        return url
    return ""


def _parse_stamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _sibling_urls(connection: sqlite3.Connection, url: str, title: str, company: str) -> list[str]:
    key = position_key_parts(title, company)
    if key is None:
        return [url]
    found = []
    for row in connection.execute("SELECT url, title, company FROM jobs"):
        if position_key_parts(row["title"], row["company"]) == key:
            found.append(row["url"])
    return found or [url]


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


def now_stamp() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")
