from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from jobs.search import Query, run_search
from storage.catalog import Catalog, now_stamp
from storage.filters import CatalogFilters
from storage.records import MergeStats
from web.frontend.report import write_outputs

log = logging.getLogger("jobsearch")

MINIMUM_INTERVAL_HOURS = 0.25
MAXIMUM_INTERVAL_HOURS = 24 * 7


class CatalogService:
    """Refreshes the full remote-IT reservation catalog on a fixed interval."""

    def __init__(self, catalog: Catalog, interval_hours: float = 6, pages: int = 100) -> None:
        self.catalog = catalog
        self.interval_hours = min(
            max(interval_hours, MINIMUM_INTERVAL_HOURS), MAXIMUM_INTERVAL_HOURS
        )
        self.pages = min(max(pages, 1), 100)
        if self.interval_hours != interval_hours:
            log.warning("refresh interval clamped to %g h", self.interval_hours)
        if self.pages != pages:
            log.warning("page ceiling clamped to %s", self.pages)
        self.running = False
        self.next_run = ""
        self.last_error = ""
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._refresh_thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="catalog-refresh", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Ask the current refresh to finish the site it is reading, then exit."""
        self._stop.set()
        current = threading.current_thread()
        for worker in (self._thread, self._refresh_thread):
            if worker is None or not worker.is_alive() or worker is current:
                continue
            log.info("waiting for %s to finish the current site", worker.name)
            worker.join()

    def request_refresh(self) -> bool:
        if self._stop.is_set() or self.running or self._lock.locked():
            return False
        self._refresh_thread = threading.Thread(
            target=self.refresh,
            kwargs={"interactive": True},
            name="catalog-refresh-now",
            daemon=True,
        )
        self._refresh_thread.start()
        return True

    def refresh(self, interactive: bool = False) -> MergeStats | None:
        if not self._lock.acquire(blocking=False):
            return None
        self.running = True
        self.last_error = ""
        started = now_stamp()
        log.info("catalog refresh started")
        try:
            jobs, statuses = run_search(
                Query(
                    keyword="",
                    pages=self.pages,
                    focus="engineering",
                    verify=True,
                    interactive=interactive,
                ),
                cancelled=self._stop.is_set,
            )
            for status in statuses:
                line = "%s: %s (fetched %s, kept %s)"
                if status.ok:
                    log.info(line, status.name, status.message, status.fetched, status.kept)
                else:
                    log.warning(line, status.name, status.message, status.fetched, status.kept)
            finished = now_stamp()
            stats = self.catalog.merge(jobs, statuses, started, finished)
            log.info(
                "catalog refresh saved: added %s, updated %s, deactivated %s",
                stats.added,
                stats.updated,
                stats.deactivated,
            )
            try:
                stored = self.catalog.list_jobs(CatalogFilters(mine="all"))
                write_outputs(
                    [item.job for item in stored],
                    statuses,
                    Query(keyword="", pages=self.pages, focus="engineering"),
                )
            except Exception as exc:
                log.exception("catalog was saved, but out/ could not be written")
                self.last_error = f"каталог збережено, файл звіту не записався: {exc}"[:240]
            if self._stop.is_set():
                log.info("catalog refresh stopped before every source finished")
            return stats
        except Exception as exc:
            log.exception("catalog refresh failed")
            self.last_error = str(exc)[:240]
            try:
                self.catalog.record_failure(started, now_stamp(), self.last_error)
            except Exception:
                log.exception("could not record the failed refresh")
            return None
        finally:
            self.running = False
            self.next_run = _format(datetime.now() + timedelta(hours=self.interval_hours))
            self._lock.release()

    def _loop(self) -> None:
        # The first run follows a start-up, so someone is likely at the machine.
        interactive = True
        while not self._stop.is_set():
            self.refresh(interactive=interactive)
            interactive = False
            if self._stop.wait(self.interval_hours * 3600):
                return


def _format(moment: datetime) -> str:
    return moment.replace(microsecond=0).isoformat(sep=" ")
