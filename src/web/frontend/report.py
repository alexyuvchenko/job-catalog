"""Files written by a one-off search: JSON, CSV, and a static HTML page."""

from __future__ import annotations

import csv
import json
from html import escape
from pathlib import Path

from core.models import Job, SourceStatus
from core.paths import OUT_DIR
from jobs.search import Query
from storage.group import group_same_positions
from storage.records import StoredJob
from web.frontend.assets.styles import CSS
from web.frontend.catalog_rows import render_rows
from web.frontend.components import manual_links, source_chips
from web.frontend.i18n import translator

_REPORT_JS = """
(() => {
  const filter = document.getElementById("filter");
  filter.addEventListener("input", () => {
    const query = filter.value.trim().toLowerCase();
    document.querySelectorAll("tbody tr").forEach((row) => {
      row.hidden = query && !row.innerText.toLowerCase().includes(query);
    });
  });
})();
"""

_CSV_FIELDS = [
    "published",
    "source",
    "title",
    "company",
    "location",
    "remote",
    "salary_text",
    "currency",
    "salary_min",
    "salary_max",
    "category",
    "english",
    "years",
    "reservation",
    "url",
    "evidence",
]


def write_outputs(jobs: list[Job], statuses: list[SourceStatus], query: Query) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "query": {
            "keyword": query.keyword,
            "pages": query.pages,
            "focus": query.focus,
            "full_remote_only": query.full_remote_only,
            "min_salary": query.min_salary,
            "english": query.english,
            "min_years": query.min_years,
            "since_days": query.since_days,
        },
        "sources": [status.__dict__ for status in statuses],
        "jobs": [job.as_dict() for job in jobs],
    }
    (OUT_DIR / "jobs.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_csv(OUT_DIR / "jobs.csv", jobs)
    html_path = OUT_DIR / "jobs.html"
    html_path.write_text(render_page(jobs, statuses), encoding="utf-8")
    return html_path


def render_page(jobs: list[Job], statuses: list[SourceStatus], language: str = "uk") -> str:
    t = translator(language)
    items = group_same_positions(
        [StoredJob(job=job, active=True, first_seen="", last_seen="") for job in jobs]
    )
    rows = render_rows(items, t, actions=False)
    if not rows:
        rows = f'<tr><td colspan="6" class="empty">{escape(t("report_empty"))}</td></tr>'
    new_count = sum(1 for item in items if item.job.is_new)
    new_note = t("report_new", n=new_count) if new_count else ""
    return f"""<!DOCTYPE html>
<html lang="{language}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(t("title"))}</title>
  <style>{CSS}</style>
</head>
<body>
<main>
  <h1>{escape(t("title"))}</h1>
  <p class="lede">{escape(t("lede_report"))}</p>
  {source_chips(statuses, t)}
  <div class="toolbar">
    <div class="count">{escape(t("report_count", n=len(items)))}{escape(new_note)}</div>
    <input id="filter" type="search" placeholder="{escape(t("filter_list"))}" aria-label="{escape(t("filter_list"))}">
  </div>
  <div class="table-wrap">
  <table class="static">
    <caption>{escape(t("table_caption"))}</caption>
    <thead>
      <tr>
        <th>{escape(t("th_date"))}</th>
        <th>{escape(t("th_job"))}</th>
        <th>{escape(t("th_company"))}</th>
        <th>{escape(t("th_format"))}</th>
        <th>{escape(t("th_salary"))}</th>
        <th>{escape(t("th_reservation"))}</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
  </div>
  {manual_links(t)}
  <p class="note">{escape(t("note_report"))}</p>
</main>
<script>{_REPORT_JS}</script>
</body>
</html>
"""


def _write_csv(path: Path, jobs: list[Job]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for job in jobs:
            writer.writerow(job.as_dict())
