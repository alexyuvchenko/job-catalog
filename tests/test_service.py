import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from tests.support import sign_in

from jobsearch.cli import main
from jobsearch.db.catalog import Catalog
from jobsearch.models import Job, SourceStatus
from jobsearch.search import STOPPED, Query, run_search
from jobsearch.service import MINIMUM_INTERVAL_HOURS, CatalogService
from jobsearch.web.server import create_app, host_allowed


class ServiceTests(unittest.TestCase):
    def test_interval_has_a_floor_and_start_is_single_flight(self):
        with tempfile.TemporaryDirectory() as folder:
            service = CatalogService(
                Catalog(Path(folder) / "catalog.sqlite"), interval_hours=0.01, pages=1
            )
            self.assertEqual(service.interval_hours, MINIMUM_INTERVAL_HOURS)
            service._loop = lambda: service._stop.wait(2)
            service.start()
            first = service._thread
            service.start()
            self.assertIs(first, service._thread)
            service.stop()
            self.assertFalse(first.is_alive())

    def test_stop_finishes_the_refresh_that_is_already_running(self):
        with tempfile.TemporaryDirectory() as folder:
            service = CatalogService(
                Catalog(Path(folder) / "catalog.sqlite"), interval_hours=6, pages=1
            )
            entered = threading.Event()

            def search(query, client=None, cancelled=None):
                entered.set()
                while not cancelled():
                    entered.wait(0.01)
                return [], []

            with patch("jobsearch.service.run_search", search):
                self.assertTrue(service.request_refresh())
                self.assertTrue(entered.wait(1))
                service.stop()
            self.assertFalse(service._refresh_thread.is_alive())
            self.assertFalse(service.running)

    def test_report_write_failure_keeps_the_saved_catalog(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = Catalog(Path(folder) / "catalog.sqlite")
            service = CatalogService(catalog, interval_hours=6, pages=1)
            status = SourceStatus("Djinni", True, "ok", fetched=1, kept=1)
            with (
                patch("jobsearch.service.run_search", return_value=([_job()], [status])),
                patch("jobsearch.service.write_outputs", side_effect=OSError("disk full")),
            ):
                stats = service.refresh()
            self.assertEqual(stats.added, 1)
            self.assertEqual(catalog.counts(), (1, 0))
            self.assertIn("файл звіту не записався", service.last_error)

    def test_stopped_search_does_not_read_later_sources_or_keep_unverified_dou(self):
        calls = []

        def djinni(client, keyword, pages):
            calls.append("Djinni")
            return [_job()], "прочитано 1"

        def dou(client, keyword, pages):
            calls.append("DOU")
            return [
                _job(source="DOU", url="https://jobs.dou.ua/vacancies/1", job_id="d1")
            ], "прочитано 1"

        def browser():
            raise AssertionError("Chrome should stay closed")

        with tempfile.TemporaryDirectory() as folder:
            with (
                patch("jobsearch.search.CACHE_PATH", Path(folder) / "cache.sqlite"),
                patch("jobsearch.search.HTTP_SOURCES", (("Djinni", djinni), ("DOU", dou))),
                patch("jobsearch.search.Browser", browser),
            ):
                jobs, statuses = run_search(
                    Query(pages=1, verify=True), cancelled=lambda: len(calls) >= 2
                )
        self.assertEqual(calls, ["Djinni", "DOU"])
        self.assertEqual([job.source for job in jobs], ["Djinni"])
        by_name = {status.name: status for status in statuses}
        self.assertTrue(by_name["Djinni"].ok)
        self.assertFalse(by_name["DOU"].complete)
        self.assertIn("не знімаються", by_name["DOU"].message)
        self.assertEqual(by_name["Work.ua"].message, STOPPED)
        self.assertFalse(by_name["Jooble"].ok)

    def test_health_security_and_refresh_origin(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = Catalog(Path(folder) / "catalog.sqlite")
            catalog.merge(
                [_job()],
                [SourceStatus("Djinni", True, "ok", fetched=1, kept=1)],
                "2026-10-10 10:00:00",
                "2026-10-10 10:01:00",
            )
            service = CatalogService(catalog, interval_hours=24, pages=1)
            service.running = True
            app = create_app(catalog, service, start_scheduler=False)

            @app.get("/boom")
            def boom() -> None:
                raise RuntimeError("secret /tmp/catalog.sqlite")

            client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)
            sign_in(client, catalog)
            health = client.get("/health")
            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.json()["active"], 1)
            self.assertTrue(health.json()["running"])
            self.assertEqual(client.get("/api/status").json()["active"], 1)
            self.assertEqual(health.headers["x-content-type-options"], "nosniff")
            policy = client.get("/").headers["content-security-policy"]
            self.assertIn("frame-ancestors 'none'", policy)
            # The page polls /api/status, and default-src 'none' would block that.
            self.assertIn("connect-src 'self'", policy)

            foreign = client.post(
                "/refresh",
                headers={"Origin": "https://evil.example"},
                follow_redirects=False,
            )
            self.assertEqual(foreign.status_code, 403)
            same = client.post(
                "/refresh",
                headers={"Origin": "http://127.0.0.1"},
                follow_redirects=False,
            )
            self.assertEqual(same.status_code, 303)

            broken = client.get("/boom")
            self.assertEqual(broken.status_code, 500)
            self.assertIn("Каталог тимчасово недоступний", broken.text)
            self.assertNotIn("secret", broken.text)
            self.assertNotIn("catalog.sqlite", broken.text)
            self.assertEqual(client.get("/missing").status_code, 404)
            self.assertEqual(
                TestClient(app, base_url="http://evil.example").get("/health").status_code, 400
            )

    def test_port_must_be_real(self):
        with self.assertRaises(SystemExit):
            main(["--port", "70000"])

    def test_host_must_be_an_address(self):
        with self.assertRaises(SystemExit):
            main(["--host", "example.com"])
        with patch("jobsearch.cli.serve") as serve:
            main(["--serve", "--host", "0.0.0.0", "--port", "9000"])
        self.assertEqual(serve.call_args.kwargs["host"], "0.0.0.0")
        with patch("jobsearch.cli.serve") as serve:
            main(["--serve"])
        self.assertEqual(serve.call_args.kwargs["host"], "127.0.0.1")

    def test_host_rules(self):
        self.assertTrue(host_allowed("127.0.0.1:8765", False))
        self.assertTrue(host_allowed("localhost", False))
        self.assertTrue(host_allowed("[::1]:8765", False))
        self.assertFalse(host_allowed("192.168.1.20:8765", False))
        for address in ("192.168.1.20:8765", "10.0.0.5", "172.16.4.2", "100.101.102.103:8765"):
            self.assertTrue(host_allowed(address, True), address)
        for name in ("8.8.8.8", "evil.example", "192.168.1.20.evil.example", ""):
            self.assertFalse(host_allowed(name, True), name)

    def test_a_phone_on_the_network_can_read_but_not_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = Catalog(Path(folder) / "catalog.sqlite")
            catalog.merge(
                [_job()],
                [SourceStatus("Djinni", True, "ok", fetched=1, kept=1)],
                "2026-10-10 10:00:00",
                "2026-10-10 10:01:00",
            )
            service = CatalogService(catalog, interval_hours=24, pages=1)
            service.running = True  # a refresh must not really start
            network = create_app(catalog, service, start_scheduler=False, allow_lan=True)
            local_only = create_app(catalog, service, start_scheduler=False)
            origin = {"Origin": "http://192.168.1.20:8765"}

            phone = TestClient(
                network, base_url="http://192.168.1.20:8765", client=("192.168.1.50", 50000)
            )
            sign_in(phone, catalog)
            self.assertEqual(phone.get("/").status_code, 200)
            self.assertIn("лише на комп’ютері", phone.get("/").text)
            self.assertEqual(len(phone.get("/api/jobs").json()), 1)
            refused = phone.post("/refresh", headers=origin, follow_redirects=False)
            self.assertEqual(refused.status_code, 403)

            # The same machine may refresh, whether it uses localhost or its network address.
            for base, peer in (
                ("http://127.0.0.1:8765", "127.0.0.1"),
                ("http://192.168.1.20:8765", "192.168.1.20"),
            ):
                machine = TestClient(network, base_url=base, client=(peer, 50001))
                sign_in(machine, catalog)
                self.assertNotIn("лише на комп’ютері", machine.get("/").text)
                allowed = machine.post("/refresh", headers={"Origin": base}, follow_redirects=False)
                self.assertEqual(allowed.status_code, 303, base)

            # Without --host the service still answers only to localhost.
            self.assertEqual(
                TestClient(local_only, base_url="http://192.168.1.20:8765").get("/").status_code,
                400,
            )
            self.assertEqual(
                TestClient(network, base_url="http://8.8.8.8").get("/health").status_code, 400
            )


def _job(**overrides) -> Job:
    data = dict(
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
    data.update(overrides)
    return Job(**data)


if __name__ == "__main__":
    unittest.main()
