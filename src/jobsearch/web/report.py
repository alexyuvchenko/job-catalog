from __future__ import annotations

import csv
import json
from html import escape
from pathlib import Path

from jobsearch.constants import REMOTE_LABELS, RESERVATION_LABELS, SOURCE_NAMES
from jobsearch.db.catalog import CatalogFilters, StoredJob
from jobsearch.models import Job, SourceStatus
from jobsearch.paths import OUT_DIR
from jobsearch.search import Query

MANUAL_LINKS = (
    (
        "Djinni",
        "https://djinni.co/jobs/?employment=remote&editorial=reservation",
        "офіційний фільтр «Бронювання» і віддалена робота",
    ),
    (
        "DOU",
        "https://jobs.dou.ua/vacancies/?remote=&search=%D0%B1%D1%80%D0%BE%D0%BD%D1%8E%D0%B2%D0%B0%D0%BD%D0%BD%D1%8F",
        "віддалені вакансії за запитом «бронювання»",
    ),
    (
        "Work.ua",
        "https://www.work.ua/jobs-remote-industry-it/?deferment=1",
        "віддалені IT-вакансії з фільтром «Бронювання працівників»",
    ),
    (
        "Robota.ua",
        "https://robota.ua/zapros/ukraine/params;rubrics=1",
        "IT-вакансії; скрипт залишає віддалені з позначкою бронювання",
    ),
    (
        "Jooble",
        "https://ua.jooble.org/SearchResult?rgns=%D0%B2%D1%96%D0%B4%D0%B4%D0%B0%D0%BB%D0%B5%D0%BD%D0%BE&ukw=%D0%B1%D1%80%D0%BE%D0%BD%D1%8E%D0%B2%D0%B0%D0%BD%D0%BD%D1%8F%20%D0%BF%D1%80%D0%B0%D1%86%D1%96%D0%B2%D0%BD%D0%B8%D0%BA%D1%96%D0%B2",
        "віддалені вакансії; у списку лишаються ті, де в тексті є бронювання",
    ),
)


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
    html_path.write_text(render_page(jobs, statuses, query, include_form=False), encoding="utf-8")
    return html_path


def _css() -> str:
    return """
    :root {
      color-scheme: light;
      --ink: #1c1915;
      --muted: #5e584f;
      --line: #e4ddd2;
      --paper: #f6f3ee;
      --card: #fffcf8;
      --green: #0d6b52;
      --green-soft: #e5f4ef;
      --amber: #8a5a12;
      --amber-soft: #f8efdc;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font: 16px/1.45 "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    }
    main { max-width: 1100px; margin: 0 auto; padding: 28px 20px 64px; }
    h1 { font-size: 1.7rem; line-height: 1.2; margin: 0 0 8px; }
    .lede { color: var(--muted); margin: 0 0 20px; max-width: 68ch; }
    .panel, form:not(.bare) {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 16px;
      margin-bottom: 16px;
    }
    form.bare { background: none; border: 0; padding: 0; margin: 0; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
    label { display: flex; flex-direction: column; gap: 4px; font-size: 0.82rem; color: var(--muted); }
    input, select {
      font: inherit; color: var(--ink); background: white;
      border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px;
    }
    .options { display: flex; flex-direction: column; gap: 8px; margin-top: 12px; }
    label.checks {
      flex-direction: row;
      align-items: flex-start;
      gap: 8px;
      color: var(--ink);
      font-size: 0.95rem;
    }
    label.checks input { width: 1rem; height: 1rem; margin: 3px 0 0; }
    button, .button {
      background: var(--green); color: white; border: 0; border-radius: 8px;
      padding: 10px 16px; font: inherit; cursor: pointer; text-decoration: none;
    }
    button.secondary { background: transparent; color: var(--green); border: 1px solid var(--green); }
    button:disabled { opacity: 0.55; cursor: default; }
    .sources { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 12px; padding: 0; list-style: none; }
    .sources li {
      display: inline-flex; align-items: center; gap: 6px;
      background: var(--card); border: 1px solid var(--line); border-radius: 999px;
      padding: 4px 10px; font-size: 0.85rem; white-space: nowrap;
    }
    .sources .bad { border-color: #e7b4b4; background: #fdecec; }
    .sources .warn { border-color: #e7d3a8; background: var(--amber-soft); }
    .banner {
      background: var(--amber-soft); color: var(--amber);
      border-radius: 10px; padding: 10px 12px; margin: 0 0 12px;
    }
    .banner.problem { background: #fdecec; color: #8a2b24; }
    .toolbar { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin: 8px 0; }
    .count, .statusline { color: var(--muted); }
    .statusline { margin: 0 0 12px; }
    .actions { display: flex; gap: 8px; align-items: center; margin-top: 12px; }
    .table-wrap { border: 1px solid var(--line); border-radius: 12px; background: var(--card); }
    tbody tr[hidden] { display: none; }
    table { width: 100%; border-collapse: collapse; background: var(--card); }
    th, td { text-align: left; padding: 12px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
    th {
      position: sticky; top: 0; z-index: 1;
      font-size: 0.78rem; letter-spacing: 0.03em; text-transform: uppercase; color: var(--muted);
      background: var(--card);
    }
    tr:last-child td { border-bottom: 0; }
    tbody tr:hover { background: #f4f8f6; }
    td.when, td.pay { white-space: nowrap; }
    td.where { max-width: 16rem; }
    tr.closed { opacity: 0.55; }
    a { color: var(--green); }
    .title { font-weight: 600; }
    .meta { color: var(--muted); font-size: 0.88rem; margin-top: 3px; }
    .badge {
      display: inline-block; border-radius: 999px; padding: 1px 8px;
      background: var(--green-soft); color: var(--green); font-size: 0.78rem;
    }
    .badge.warn { background: var(--amber-soft); color: var(--amber); }
    .new { font-size: 0.75rem; font-weight: 700; color: var(--green); margin-left: 6px; }
    .empty { color: var(--muted); padding: 24px 10px; }
    .note { color: var(--muted); font-size: 0.9rem; max-width: 78ch; }
    .links { padding-left: 18px; }
    #filter { max-width: 280px; }

    /* Wide screens: use the room. */
    @media (min-width: 1500px) {
      main { max-width: 1320px; }
      td.where { max-width: 22rem; }
    }

    /* Tablets and small laptops: the same table, tighter, and it scrolls instead of clipping. */
    @media (max-width: 960px) {
      main { padding: 22px 16px 56px; }
      .table-wrap { overflow-x: auto; }
      th, td { padding: 10px 8px; }
      td.where { max-width: 12rem; }
      .grid { grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr)); }
    }

    /* Phones: each vacancy is a card. */
    @media (max-width: 640px) {
      main {
        padding: 16px max(12px, env(safe-area-inset-right)) 48px max(12px, env(safe-area-inset-left));
      }
      h1 { font-size: 1.35rem; }
      .lede { font-size: 0.95rem; margin-bottom: 14px; }
      .panel, form:not(.bare) { padding: 12px; border-radius: 10px; }
      .grid { grid-template-columns: 1fr; gap: 10px; }
      .actions { flex-wrap: wrap; }
      .actions button, .actions form { flex: 1 1 100%; }
      .actions form button { width: 100%; }
      form:not(.bare) > button { width: 100%; }
      .sources {
        flex-wrap: nowrap; overflow-x: auto; padding-bottom: 4px;
        margin-right: -12px; padding-right: 12px; scrollbar-width: none;
      }
      .sources::-webkit-scrollbar { display: none; }
      .sources li { flex: none; }
      .toolbar { flex-direction: column; align-items: stretch; gap: 8px; }
      #filter { max-width: none; width: 100%; }
      .table-wrap { border: 0; background: none; border-radius: 0; overflow: visible; }
      table, tbody { display: block; background: none; }
      thead { display: none; }
      tbody tr {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        grid-template-areas:
          "job job"
          "company status"
          "where where"
          "pay when";
        gap: 6px 12px;
        background: var(--card); border: 1px solid var(--line); border-radius: 12px;
        padding: 12px; margin-bottom: 10px;
      }
      tbody tr:hover { background: var(--card); }
      tbody tr:last-child td { border-bottom: 0; }
      td { display: block; padding: 0; border: 0; min-width: 0; overflow-wrap: anywhere; }
      td.job { grid-area: job; }
      td.company { grid-area: company; font-weight: 600; }
      td.status { grid-area: status; text-align: right; }
      td.where { grid-area: where; max-width: none; color: var(--muted); font-size: 0.92rem; }
      td.pay { grid-area: pay; white-space: normal; }
      td.pay.none { display: none; }
      td.when { grid-area: when; text-align: right; color: var(--muted); font-size: 0.85rem; }
      td.empty { grid-area: auto; grid-column: 1 / -1; padding: 16px 4px; }
      tbody tr:has(td.empty) { display: block; border: 0; background: none; padding: 0; }
      .title { font-size: 1.02rem; line-height: 1.3; }
    }

    /* Touch screens: bigger targets, whatever the width. */
    @media (pointer: coarse) {
      input:not([type="checkbox"]), select, button { min-height: 44px; }
      label.checks { padding: 4px 0; }
      label.checks input { width: 1.3rem; height: 1.3rem; margin-top: 1px; }
    }
    """


def render_page(
    jobs: list[Job],
    statuses: list[SourceStatus],
    query: Query,
    include_form: bool,
) -> str:
    rows = "\n".join(_row(job) for job in jobs)
    if not rows and not statuses:
        rows = '<tr><td colspan="6" class="empty">Задайте умови і натисніть «Шукати».</td></tr>'
    elif not rows:
        rows = '<tr><td colspan="6" class="empty">Нічого не знайдено за цими умовами.</td></tr>'
    new_count = sum(1 for job in jobs if job.is_new)
    new_note = f" · нових з минулого пошуку: {new_count}" if new_count else ""
    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Віддалені IT-вакансії з бронюванням</title>
  <style>{_css()}</style>
</head>
<body>
<main>
  <h1>Віддалені IT-вакансії з бронюванням</h1>
  <p class="lede">Пошук віддаленої роботи в IT в Україні на Djinni, DOU, Work.ua, Robota.ua і Jooble серед вакансій, де роботодавець заявляє бронювання від мобілізації.</p>
  {_form(query) if include_form else ""}
  {"" if not statuses else '<ul class="sources">' + "".join(_status(status) for status in statuses) + "</ul>"}
  <div class="toolbar">
    <div class="count">{len(jobs)} вакансій{new_note}</div>
    <input id="filter" type="search" placeholder="Фільтр у списку" aria-label="Фільтр у списку">
  </div>
  <table>
    <thead>
      <tr>
        <th>Дата</th>
        <th>Вакансія</th>
        <th>Компанія</th>
        <th>Формат</th>
        <th>Зарплата</th>
        <th>Бронювання</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
  <h2>Перевірити джерела вручну</h2>
  <ul class="links">
    {"".join(f'<li><a href="{escape(url)}">{escape(name)}</a> — {escape(note)}</li>' for name, url, note in MANUAL_LINKS)}
  </ul>
  <p class="note">Бронювання — це заява роботодавця, що посаду можна включити в бронювання військовозобов’язаних працівників. Це не автоматична відстрочка: потрібні актуальні військово-облікові документи, а рішення залежить від статусу компанії і чинного порядку. Умови варто підтвердити на співбесіді. Work.ua, Robota.ua і Jooble відкриваються через Chrome, бо інакше сайти не віддають сторінку. Вікно Chrome з’являється поза екраном на час пошуку. У Jooble немає окремого фільтра бронювання, тому залишаються лише картки, де це написано в тексті.</p>
</main>
<script>
  const filter = document.getElementById("filter");
  filter.addEventListener("input", () => {{
    const query = filter.value.trim().toLowerCase();
    document.querySelectorAll("tbody tr").forEach((row) => {{
      row.hidden = query && !row.innerText.toLowerCase().includes(query);
    }});
  }});
  const form = document.querySelector("form");
  if (form) {{
    form.addEventListener("submit", () => {{
      const button = form.querySelector("button");
      button.disabled = true;
      button.textContent = "Шукаю…";
    }});
  }}
</script>
</body>
</html>
"""


def _form(query: Query) -> str:
    def selected(value: str, current: str) -> str:
        return " selected" if value == current else ""

    english_options = ['<option value="">будь-яка</option>']
    for level in ("A2", "B1", "B2", "C1", "C2"):
        english_options.append(
            f'<option value="{level}"{selected(level, query.english)}>{level}+</option>'
        )
    full_checked = " checked" if query.full_remote_only else ""
    return f"""
  <form action="/search" method="get">
    <div class="grid">
      <label>Посада або технологія
        <input name="keyword" value="{escape(query.keyword)}" placeholder="python, devops, qa">
      </label>
      <label>Ролі
        <select name="focus">
          <option value="engineering"{selected("engineering", query.focus)}>інженерні та продуктові</option>
          <option value="all"{selected("all", query.focus)}>усі вакансії, включно з HR і маркетингом</option>
        </select>
      </label>
      <label>Мін. зарплата, USD
        <input name="min_salary" inputmode="numeric" value="{"" if query.min_salary is None else query.min_salary}">
      </label>
      <label>Англійська від
        <select name="english">{"".join(english_options)}</select>
      </label>
      <label>Досвід від, років
        <input name="min_years" inputmode="decimal" value="{"" if query.min_years is None else query.min_years}">
      </label>
      <label>Сторінок з кожного сайту
        <input name="pages" type="number" min="1" max="10" value="{query.pages}">
      </label>
    </div>
    <p class="checks"><label class="checks"><input type="checkbox" name="full_remote_only" value="1"{full_checked}>Лише повна віддаленка, без гібриду</label></p>
    <button type="submit">Шукати</button>
  </form>
"""


def _status(status: SourceStatus) -> str:
    if not status.ok:
        css = "bad"
        detail = "помилка"
    elif not status.complete:
        css = "warn"
        detail = str(status.kept)
    else:
        css = "ok"
        detail = str(status.kept)
    return (
        f'<li class="{css}" title="{escape(status.message)}">'
        f"<strong>{escape(status.name)}</strong> {detail}</li>"
    )


def render_catalog(
    stored: list[StoredJob],
    statuses: list[SourceStatus],
    filters: CatalogFilters,
    *,
    active_count: int,
    inactive_count: int,
    running: bool,
    last_finished: str,
    next_run: str,
    added: int,
    updated: int,
    deactivated: int,
    error: str,
    can_refresh: bool = True,
) -> str:
    rows = "\n".join(_row(item.job, closed=not item.active) for item in stored)
    if not rows:
        message = (
            "Каталог ще порожній. Перше оновлення вже йде."
            if running
            else "Нічого не знайдено за цими умовами."
        )
        rows = f'<tr><td colspan="6" class="empty">{message}</td></tr>'
    new_count = sum(1 for item in stored if item.job.is_new and item.active)
    new_note = f" · нових з останнього оновлення: {new_count}" if new_count else ""
    if last_finished:
        progress = f"Оновлено {escape(last_finished)}: додано {added}, змінено {updated}, знято {deactivated}."
        if next_run and not running:
            progress += f" Наступне оновлення о {escape(next_run)}."
    else:
        progress = "Оновлення ще не завершувалось."
    notices = []
    if running:
        notices.append(
            '<p class="banner">Зараз оновлюю каталог. Список на екрані лишається, а нові дані з’являться самі.</p>'
        )
    if error:
        notices.append(f'<p class="banner problem">{escape(error)}</p>')
    banner = "".join(notices)
    shown = len(stored)
    refreshing = "1" if running else "0"
    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Віддалені IT-вакансії з бронюванням</title>
  <style>{_css()}</style>
</head>
<body data-refreshing="{refreshing}">
<main>
  <h1>Віддалені IT-вакансії з бронюванням</h1>
  <p class="lede">Каталог віддалених IT-вакансій в Україні, де роботодавець заявляє бронювання від мобілізації. Список збирається з Djinni, DOU, Work.ua, Robota.ua і Jooble і оновлюється сам.</p>
  {banner}
  <p class="statusline">{progress} У каталозі {active_count} актуальних{f", знятих {inactive_count}" if inactive_count else ""}.</p>
  {_catalog_form(filters, running, can_refresh)}
  {"" if not statuses else '<ul class="sources">' + "".join(_status(status) for status in statuses) + "</ul>"}
  <div class="toolbar">
    <div class="count" id="shown">Показано {shown}{new_note}</div>
    <input id="filter" type="search" placeholder="Фільтр у списку" aria-label="Фільтр у списку">
  </div>
  <div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>Дата</th>
        <th>Вакансія</th>
        <th>Компанія</th>
        <th>Формат</th>
        <th>Зарплата</th>
        <th>Бронювання</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
  </div>
  <h2>Перевірити джерела вручну</h2>
  <ul class="links">
    {"".join(f'<li><a href="{escape(url)}">{escape(name)}</a> — {escape(note)}</li>' for name, url, note in MANUAL_LINKS)}
  </ul>
  <p class="note">Бронювання — це заява роботодавця, що посаду можна включити в бронювання військовозобов’язаних працівників. Це не автоматична відстрочка: потрібні актуальні військово-облікові документи, а рішення залежить від статусу компанії і чинного порядку. Умови варто підтвердити на співбесіді. Вакансія зникає з активного списку, коли її більше немає у джерелі під час чергового оновлення. Якщо сайт не відповів, попередні вакансії цього джерела залишаються. Work.ua, Robota.ua і Jooble відкриваються через Chrome поза екраном. У Jooble залишаються лише картки, де в тексті є бронювання.</p>
</main>
<script>
  const filter = document.getElementById("filter");
  const shown = document.getElementById("shown");
  const shownLabel = shown ? shown.textContent : "";
  const applyFilter = () => {{
    const query = filter.value.trim().toLowerCase();
    let visible = 0;
    document.querySelectorAll("tbody tr").forEach((row) => {{
      if (row.querySelector(".empty")) return;
      const hide = query && !row.innerText.toLowerCase().includes(query);
      row.hidden = hide;
      if (!hide) visible += 1;
    }});
    if (!shown) return;
    shown.textContent = query ? "Показано " + visible : shownLabel;
  }};
  filter.addEventListener("input", applyFilter);
  if (document.body.dataset.refreshing === "1") {{
    const timer = setInterval(async () => {{
      try {{
        const response = await fetch("/api/status");
        if (!response.ok) return;
        const data = await response.json();
        if (data.running === false) location.reload();
      }} catch (error) {{
        /* keep polling; one failed status check should not freeze the page */
      }}
    }}, 4000);
  }}
</script>
</body>
</html>
"""


def _catalog_form(filters: CatalogFilters, running: bool, can_refresh: bool = True) -> str:
    def selected(value: str, current: str) -> str:
        return " selected" if value == current else ""

    english_options = ['<option value="">будь-яка</option>']
    for level in ("A2", "B1", "B2", "C1", "C2"):
        english_options.append(
            f'<option value="{level}"{selected(level, filters.english)}>{level}+</option>'
        )
    source_options = ['<option value="">усі джерела</option>']
    for name in SOURCE_NAMES:
        source_options.append(
            f'<option value="{escape(name)}"{selected(name, filters.source)}>{escape(name)}</option>'
        )
    full_checked = " checked" if filters.full_remote_only else ""
    closed_checked = " checked" if filters.include_inactive else ""
    if not can_refresh:
        button = "Оновлення — лише на комп’ютері"
    else:
        button = "Оновлення вже йде…" if running else "Оновити зараз"
    disabled = " disabled" if running or not can_refresh else ""
    return f"""
  <div class="panel">
  <form id="filters" class="bare" action="/" method="get">
    <div class="grid">
      <label>Посада або технологія
        <input name="q" value="{escape(filters.text)}" placeholder="python, devops, qa">
      </label>
      <label>Джерело
        <select name="source">{"".join(source_options)}</select>
      </label>
      <label>Мін. зарплата, USD
        <input name="min_salary" inputmode="numeric" value="{"" if filters.min_salary is None else filters.min_salary}">
      </label>
      <label>Англійська від
        <select name="english">{"".join(english_options)}</select>
      </label>
      <label>Досвід від, років
        <input name="min_years" inputmode="decimal" value="{"" if filters.min_years is None else filters.min_years}">
      </label>
    </div>
    <div class="options">
      <label class="checks"><input type="checkbox" name="full_remote_only" value="1"{full_checked}>Лише повна віддаленка, без гібриду</label>
      <label class="checks"><input type="checkbox" name="include_inactive" value="1"{closed_checked}>Показати вакансії, яких уже немає в джерелах</label>
    </div>
  </form>
  <div class="actions">
    <button type="submit" form="filters">Застосувати</button>
    <form class="bare" action="/refresh" method="post">
      <button class="secondary" type="submit"{disabled}>{button}</button>
    </form>
  </div>
  </div>
"""


def _row(job: Job, closed: bool = False) -> str:
    salary = job.salary_text or "—"
    remote = REMOTE_LABELS.get(job.remote, job.remote)
    if closed:
        reservation = "знято"
    elif job.reservation == "confirmed":
        reservation = "підтверджено"
    elif job.reservation == "unverified":
        reservation = "без бейджа"
    else:
        reservation = RESERVATION_LABELS.get(job.reservation, job.reservation)
    badge_class = "badge warn" if closed or job.reservation != "confirmed" else "badge"
    new = '<span class="new">нова</span>' if job.is_new and not closed else ""
    hint = f' title="{escape(job.evidence)}"' if job.evidence and not closed else ""
    location = f" · {escape(job.location)}" if job.location else ""
    category = f" · {escape(job.category)}" if job.category else ""
    english = f" · English {escape(job.english)}" if job.english and job.english != "none" else ""
    years = ""
    if job.years is not None:
        years_text = str(int(job.years)) if job.years == int(job.years) else str(job.years)
        years = f" · {years_text} р. досвіду"
    css = ' class="closed"' if closed else ""
    company = escape(job.company) if job.company else "—"
    pay_class = "pay" if job.salary_text else "pay none"
    return f"""<tr{css}>
      <td class="when">{escape(job.published or "—")}</td>
      <td class="job"><a class="title" href="{escape(job.url)}">{escape(job.title)}</a>{new}
        <div class="meta">{escape(job.source)}{category}{english}{years}</div></td>
      <td class="company">{company}</td>
      <td class="where">{escape(remote)}{location}</td>
      <td class="{pay_class}">{escape(salary)}</td>
      <td class="status"><span class="{badge_class}"{hint}>{escape(reservation)}</span></td>
    </tr>"""


def _write_csv(path: Path, jobs: list[Job]) -> None:
    fields = [
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
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for job in jobs:
            writer.writerow(job.as_dict())
