import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from tests.support import sign_in

from jobsearch.auth import (
    AccountError,
    check_password,
    check_username,
    hash_password,
    safe_next,
    verify_password,
)
from jobsearch.db.catalog import Catalog, CatalogFilters
from jobsearch.models import Job, SourceStatus
from jobsearch.service import CatalogService
from jobsearch.web.server import create_app

DJINNI = SourceStatus("Djinni", True, "ok", fetched=1, kept=1)


class AccountTests(unittest.TestCase):
    def test_password_and_return_path(self):
        stored = hash_password("password-1")
        self.assertTrue(verify_password("password-1", stored))
        self.assertFalse(verify_password("password-2", stored))
        self.assertFalse(verify_password("password-1", "scrypt$1$1$1$00$00"))
        self.assertEqual(check_username("  Олена  "), "Олена")
        with self.assertRaises(AccountError):
            check_username(" ")
        with self.assertRaises(AccountError):
            check_password("short")
        self.assertEqual(safe_next("/?q=python"), "/?q=python")
        self.assertEqual(safe_next("https://evil.example"), "/")
        self.assertEqual(safe_next("//evil.example"), "/")
        self.assertEqual(safe_next("/login"), "/")

    def test_marks_and_filters_belong_to_the_account(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = Catalog(Path(folder) / "catalog.sqlite")
            catalog.merge([_job()], [DJINNI], "2026-10-10 10:00:00", "2026-10-10 10:01:00")
            ada = catalog.create_user("Ada", "password-1")
            with self.assertRaises(AccountError):
                catalog.create_user("ada", "password-2")
            ben = catalog.create_user("ben", "password-2")
            catalog.set_marks(_job().url, ada.id, favorite=True, rating=5, hidden=False)
            ada_seen = catalog.list_jobs(CatalogFilters(mine="favorites"), ada.id)
            ben_seen = catalog.list_jobs(CatalogFilters(mine="favorites"), ben.id)
            self.assertEqual([item.job.url for item in ada_seen], [_job().url])
            self.assertEqual(ben_seen, [])
            self.assertEqual(catalog.list_jobs(CatalogFilters(), ben.id)[0].marks.rating, 0)

            service = CatalogService(catalog, interval_hours=24, pages=1)
            app = create_app(catalog, service, start_scheduler=False)
            ada_client = TestClient(app, base_url="http://127.0.0.1")
            ben_client = TestClient(app, base_url="http://127.0.0.1")
            sign_in(ada_client, catalog, "Ada", "password-1")
            sign_in(ben_client, catalog, "ben", "password-2")

            saved = ada_client.get("/", params={"q": "python", "min_rating": "4", "per_page": "25"})
            self.assertEqual(saved.status_code, 200)
            self.assertIn('name="q"', saved.text)
            self.assertIn('value="python"', saved.text)
            again = ada_client.get("/")
            self.assertIn('value="python"', again.text)
            self.assertIn('<option value="25" selected>', again.text)
            self.assertIn("Ada", again.text)

            other = ben_client.get("/")
            self.assertNotIn('value="python"', other.text)
            self.assertIn(">ben<", other.text)

            # A one-off API query must not replace the saved view.
            ada_client.get("/api/jobs", params={"q": "go"})
            self.assertIn('value="python"', ada_client.get("/").text)
            cleared = ada_client.get("/", params={"reset": "1"})
            self.assertNotIn('value="python"', cleared.text)

    def test_old_marks_move_to_the_first_account(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "catalog.sqlite"
            _write_old_catalog(path)
            catalog = Catalog(path)
            first = catalog.create_user("ada", "password-1")
            second = catalog.create_user("ben", "password-2")
            ada = catalog.list_jobs(CatalogFilters(mine="favorites"), first.id)
            ben = catalog.list_jobs(CatalogFilters(mine="favorites"), second.id)
            self.assertEqual([item.marks.rating for item in ada], [4])
            self.assertEqual(ben, [])

    def test_the_catalog_requires_a_session(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = Catalog(Path(folder) / "catalog.sqlite")
            catalog.merge([_job()], [DJINNI], "2026-10-10 10:00:00", "2026-10-10 10:01:00")
            client = TestClient(
                create_app(catalog, CatalogService(catalog), start_scheduler=False),
                base_url="http://127.0.0.1",
            )
            page = client.get("/", follow_redirects=False)
            self.assertEqual(page.status_code, 303)
            self.assertTrue(page.headers["location"].startswith("/login"))
            self.assertEqual(client.get("/api/jobs").status_code, 401)
            self.assertEqual(client.get("/fragments/rows").status_code, 401)
            self.assertEqual(client.get("/health").status_code, 200)

            bad = client.post(
                "/login", data={"username": "ada", "password": "password-1"}, follow_redirects=False
            )
            self.assertEqual(bad.status_code, 200)
            self.assertIn("Невірне ім’я або пароль", bad.text)
            self.assertNotIn("session=", bad.headers.get("set-cookie", ""))

            mismatch = client.post(
                "/register",
                data={"username": "ada", "password": "password-1", "password2": "password-2"},
            )
            self.assertIn("Паролі не збігаються", mismatch.text)

            stolen = client.post(
                "/login",
                data={"username": "ada", "password": "password-1", "next": "https://evil.example"},
                follow_redirects=False,
            )
            # The account does not exist yet, so this stays on the form.
            self.assertEqual(stolen.status_code, 200)

            created = client.post(
                "/register",
                data={"username": "ada", "password": "password-1", "password2": "password-1"},
                follow_redirects=False,
            )
            self.assertEqual(created.status_code, 303)
            self.assertEqual(created.headers["location"], "/")
            away = client.post(
                "/login",
                data={"username": "ada", "password": "password-1", "next": "https://evil.example"},
                follow_redirects=False,
            )
            self.assertEqual(away.headers["location"], "/")
            foreign = client.post(
                "/logout",
                headers={"Origin": "https://evil.example"},
                follow_redirects=False,
            )
            self.assertEqual(foreign.status_code, 403)
            client.post("/logout", follow_redirects=False)
            self.assertEqual(client.get("/api/jobs").status_code, 401)

            english = client.get("/login", params={"lang": "en"})
            self.assertIn("Sign in", english.text)
            self.assertIn("not an automatic deferment", english.text)


def _write_old_catalog(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE jobs (
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
            last_seen TEXT NOT NULL
        );
        CREATE TABLE job_states (
            url TEXT PRIMARY KEY REFERENCES jobs(url) ON DELETE CASCADE,
            favorite INTEGER NOT NULL DEFAULT 0,
            hidden INTEGER NOT NULL DEFAULT 0,
            rating INTEGER NOT NULL DEFAULT 0,
            viewed_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );
        """
    )
    job = _job()
    connection.execute(
        """
        INSERT INTO jobs (
            url, source, job_id, title, company, company_url, location, remote,
            salary_min, salary_max, currency, salary_text, category, english, years,
            published, reservation, evidence, snippet, active, first_seen, last_seen
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (
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
            "2026-10-10 10:00:00",
            "2026-10-10 10:01:00",
        ),
    )
    connection.execute(
        """
        INSERT INTO job_states (url, favorite, hidden, rating, viewed_at, updated_at)
        VALUES (?, 1, 0, 4, '', '2026-10-10 10:00:00')
        """,
        (job.url,),
    )
    connection.commit()
    connection.close()


def _job() -> Job:
    return Job(
        source="Djinni",
        job_id="1",
        title="Python Developer",
        company="Example",
        company_url="",
        url="https://example.com/1",
        location="Україна",
        remote="full",
        salary_min=None,
        salary_max=None,
        currency=None,
        salary_text="",
        category="Python",
        english="B2",
        years=3,
        published="2026-10-09",
        reservation="confirmed",
        evidence="",
        snippet="",
    )


if __name__ == "__main__":
    unittest.main()
