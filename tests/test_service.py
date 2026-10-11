import threading
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from tests.support import sign_in

from cli import main
from core.models import Job, SourceStatus
from jobs.refresh import MINIMUM_INTERVAL_HOURS, CatalogService
from jobs.search import DISABLED, STOPPED, Query, run_search
from storage.catalog import Catalog
from web.app import create_app
from web.security import host_allowed


class TestService:
    def test_interval_has_a_floor_and_start_is_single_flight(self, tmp_path):
        service = CatalogService(Catalog(tmp_path / "catalog.sqlite"), interval_hours=0.01, pages=1)
        assert service.interval_hours == MINIMUM_INTERVAL_HOURS
        service._loop = lambda: service._stop.wait(2)
        service.start()
        first = service._thread
        service.start()
        assert first is service._thread
        service.stop()
        assert not (first.is_alive())

    def test_stop_finishes_the_refresh_that_is_already_running(self, tmp_path):
        service = CatalogService(Catalog(tmp_path / "catalog.sqlite"), interval_hours=6, pages=1)
        entered = threading.Event()

        def search(query, client=None, cancelled=None):
            entered.set()
            while not cancelled():
                entered.wait(0.01)
            return [], []

        with patch("jobs.refresh.run_search", search):
            assert service.request_refresh()
            assert entered.wait(1)
            service.stop()
        assert not (service._refresh_thread.is_alive())
        assert not (service.running)

    def test_report_write_failure_keeps_the_saved_catalog(self, tmp_path):
        catalog = Catalog(tmp_path / "catalog.sqlite")
        service = CatalogService(catalog, interval_hours=6, pages=1)
        status = SourceStatus("Djinni", True, "ok", fetched=1, kept=1)
        with (
            patch("jobs.refresh.run_search", return_value=([_job()], [status])),
            patch("jobs.refresh.write_outputs", side_effect=OSError("disk full")),
        ):
            stats = service.refresh()
        assert stats.added == 1
        assert catalog.counts() == (1, 0)
        assert "файл звіту не записався" in service.last_error

    def test_stopped_search_does_not_read_later_sources_or_keep_unverified_dou(self, tmp_path):
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

        with (
            patch("jobs.search.CACHE_PATH", tmp_path / "cache.sqlite"),
            patch("jobs.search.HTTP_SOURCES", (("Djinni", djinni), ("DOU", dou))),
            patch("jobs.search.Browser", browser),
        ):
            jobs, statuses = run_search(
                Query(pages=1, verify=True), cancelled=lambda: len(calls) >= 2
            )
        assert calls == ["Djinni", "DOU"]
        assert [job.source for job in jobs] == ["Djinni"]
        by_name = {status.name: status for status in statuses}
        assert by_name["Djinni"].ok
        assert not (by_name["DOU"].complete)
        assert "не знімаються" in by_name["DOU"].message
        assert by_name["Work.ua"].message == STOPPED
        assert by_name["Jooble"].message == DISABLED
        assert not (by_name["Jooble"].ok)

    def test_health_security_and_refresh_origin(self, tmp_path):
        catalog = Catalog(tmp_path / "catalog.sqlite")
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
        assert health.status_code == 200
        assert health.json()["active"] == 1
        assert health.json()["running"]
        assert client.get("/api/status").json()["active"] == 1
        assert health.headers["x-content-type-options"] == "nosniff"
        policy = client.get("/").headers["content-security-policy"]
        assert "frame-ancestors 'none'" in policy
        # The page polls /api/status, and default-src 'none' would block that.
        assert "connect-src 'self'" in policy

        foreign = client.post(
            "/refresh",
            headers={"Origin": "https://evil.example"},
            follow_redirects=False,
        )
        assert foreign.status_code == 403
        same = client.post(
            "/refresh",
            headers={"Origin": "http://127.0.0.1"},
            follow_redirects=False,
        )
        assert same.status_code == 303

        broken = client.get("/boom")
        assert broken.status_code == 500
        assert "Каталог тимчасово недоступний" in broken.text
        assert "secret" not in broken.text
        assert "catalog.sqlite" not in broken.text
        assert client.get("/missing").status_code == 404
        assert TestClient(app, base_url="http://evil.example").get("/health").status_code == 400

    def test_port_must_be_real(self):
        with pytest.raises(SystemExit):
            main(["--port", "70000"])

    def test_host_must_be_an_address(self):
        with pytest.raises(SystemExit):
            main(["--host", "example.com"])
        with patch("cli.serve") as serve:
            main(["--serve", "--host", "0.0.0.0", "--port", "9000"])
        assert serve.call_args.kwargs["host"] == "0.0.0.0"
        with patch("cli.serve") as serve:
            main(["--serve"])
        assert serve.call_args.kwargs["host"] == "127.0.0.1"

    def test_host_rules(self):
        assert host_allowed("127.0.0.1:8765", False)
        assert host_allowed("localhost", False)
        assert host_allowed("[::1]:8765", False)
        assert not (host_allowed("192.168.1.20:8765", False))
        for address in ("192.168.1.20:8765", "10.0.0.5", "172.16.4.2", "100.101.102.103:8765"):
            assert host_allowed(address, True), address
        for name in ("8.8.8.8", "evil.example", "192.168.1.20.evil.example", ""):
            assert not host_allowed(name, True), name

    def test_a_phone_on_the_network_can_read_but_not_refresh(self, tmp_path):
        catalog = Catalog(tmp_path / "catalog.sqlite")
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
        assert phone.get("/").status_code == 200
        assert "лише на комп’ютері" in phone.get("/").text
        assert len(phone.get("/api/jobs").json()) == 1
        refused = phone.post("/refresh", headers=origin, follow_redirects=False)
        assert refused.status_code == 403

        # The same machine may refresh, whether it uses localhost or its network address.
        for base, peer in (
            ("http://127.0.0.1:8765", "127.0.0.1"),
            ("http://192.168.1.20:8765", "192.168.1.20"),
        ):
            machine = TestClient(network, base_url=base, client=(peer, 50001))
            sign_in(machine, catalog)
            assert "лише на комп’ютері" not in machine.get("/").text
            allowed = machine.post("/refresh", headers={"Origin": base}, follow_redirects=False)
            assert allowed.status_code == 303, base

        # Without --host the service still answers only to localhost.
        assert (
            TestClient(local_only, base_url="http://192.168.1.20:8765").get("/").status_code == 400
        )
        assert TestClient(network, base_url="http://8.8.8.8").get("/health").status_code == 400


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
