from __future__ import annotations

import argparse
import ipaddress
import json
import subprocess
import sys
from pathlib import Path

from core.constants import ENGLISH_LEVELS, REMOTE_LABELS
from core.models import Job
from jobs.search import Query, run_search
from web.app import serve
from web.frontend.report import write_outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Search remote IT jobs in Ukraine that offer employee reservation (бронювання)."
    )
    parser.add_argument(
        "--serve", action="store_true", help="run the local catalog and refresh it on a schedule"
    )
    parser.add_argument("--port", type=_port, default=8765)
    parser.add_argument(
        "--host",
        type=_host,
        default="127.0.0.1",
        help="address to listen on; 0.0.0.0 lets other devices on the network read the list",
    )
    parser.add_argument("--interval", type=float, default=6, help="hours between catalog refreshes")
    parser.add_argument(
        "--catalog-pages",
        type=int,
        default=100,
        help="safety ceiling; each site is read until its listings run out",
    )
    parser.add_argument("--keyword", default="", help="role or technology, for example: python")
    parser.add_argument(
        "--pages", type=int, default=2, help="listing pages to read from each site (1-10)"
    )
    parser.add_argument("--focus", choices=("engineering", "all"), default="engineering")
    parser.add_argument("--full-remote-only", action="store_true", help="hide hybrid roles")
    parser.add_argument("--min-salary", type=int, default=None, help="minimum USD salary")
    parser.add_argument("--english", choices=ENGLISH_LEVELS, default="")
    parser.add_argument("--min-years", type=float, default=None)
    parser.add_argument("--since-days", type=int, default=None)
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="do not open DOU vacancy pages to confirm the badge",
    )
    parser.add_argument("--refresh", action="store_true", help="ignore the saved DOU badge cache")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a text list")
    parser.add_argument(
        "--open", action="store_true", help="open the HTML report when the search finishes"
    )
    args = parser.parse_args(argv)

    if args.serve:
        interval = args.interval if args.interval > 0 else 6
        serve(args.port, interval_hours=interval, pages=args.catalog_pages, host=args.host)
        return 0

    pages = min(max(args.pages, 1), 10)
    query = Query(
        keyword=args.keyword.strip(),
        pages=pages,
        focus=args.focus,
        full_remote_only=args.full_remote_only,
        min_salary=args.min_salary,
        english=args.english,
        min_years=args.min_years,
        since_days=args.since_days,
        verify=not args.no_verify,
        refresh=args.refresh,
    )
    print("Reading public listings on Djinni, DOU, Work.ua, and Robota.ua…", file=sys.stderr)
    jobs, statuses = run_search(query)
    for status in statuses:
        print(f"{status.name}: {status.message} (shown {status.kept})", file=sys.stderr)
    path = write_outputs(jobs, statuses, query)
    if args.json:
        json.dump([job.as_dict() for job in jobs], sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        _print_jobs(jobs)
    sys.stdout.flush()
    print(f"Saved {path}", file=sys.stderr)
    if args.open:
        _open(path)
    return 0


def _host(value: str) -> str:
    try:
        if value != "localhost":
            ipaddress.ip_address(value)
    except ValueError:
        raise argparse.ArgumentTypeError("host must be localhost or an IP address") from None
    return value


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be from 1 to 65535")
    return port


def _print_jobs(jobs: list[Job]) -> None:
    if not jobs:
        print("No matching jobs.")
        return
    new_count = sum(1 for job in jobs if job.is_new)
    suffix = f", {new_count} new since the last search" if new_count else ""
    print(f"{len(jobs)} jobs{suffix}\n")
    for job in jobs:
        mark = " new" if job.is_new else ""
        remote = REMOTE_LABELS.get(job.remote, job.remote)
        salary = job.salary_text or "salary not listed"
        print(f"{job.published or '----------'}  {job.source}{mark}")
        print(f"  {job.title} — {job.company}")
        print(f"  {salary} · {remote} · {job.location or 'location not listed'}")
        print(f"  {job.url}")
        print(flush=True)


def _open(path: Path) -> None:
    command = ["open", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
    subprocess.run(command, check=False)


if __name__ == "__main__":
    raise SystemExit(main())
