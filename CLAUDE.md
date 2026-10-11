# CLAUDE.md

Personal tool that collects remote IT vacancies in Ukraine where the employer states it can reserve an employee from mobilization (бронювання). It is a legitimate job search tool. See `README.md` for user-facing docs.

## Commands

```bash
uv sync                                          # install
uv run job-catalog --serve                       # catalog service on 127.0.0.1:8765
uv run job-catalog --keyword python              # one-off search, writes out/
uv run ruff check --fix . && uv run ruff format .
uv run pytest                                 # all tests
uv run pytest tests/test_marks.py                # one module
```

Run ruff and the tests after every substantive change. Live fetches, Chrome, and `uv sync` need network access, so they do not work in a restricted sandbox.

## Layout (`src/`, flat: import as `core`, `web`, and so on)

- `sources/` — one module per board: Djinni, DOU, Work.ua, Robota.ua, Jooble. Fetchers return `Listing(jobs, message, complete)`.
- `network/` — `client.py` (urllib, cookies per domain) and `browser.py` (headed off-screen Chrome via Playwright, used by Work.ua, Robota.ua, Jooble).
- `core/` — `models.py`, `classify.py` (remote, salary, English, description language), `constants.py`, `paths.py`, `log.py`. No imports from other project packages.
- `storage/` — `catalog.py`: SQLite catalog (merge, change detection, marks in `job_states`, accounts). `filters.py`: `CatalogFilters`, sorting, visibility. `records.py`: `StoredJob`, `JobMarks`, `MergeStats`. `sqlite.py`: shared connection settings (WAL).
- `jobs/` — `refresh.py` (refresh loop, `CatalogService`) and `search.py` (one-off search).
- `web/` — `app.py` builds the FastAPI app and mounts routers. `security.py`: allowed hosts and response headers. `language.py`: page language and cookie. `auth/`: accounts and sign-in routes. `catalog/`: list, marks, and refresh routes.
- `web/frontend/` — `pages.py`, `catalog_rows.py`, `components.py`, `account_page.py`, `report.py` (saved report), `i18n.py` (Ukrainian and English text), and `assets/styles.py`, `assets/script.py`.
- `cli.py` — entry point (`job-catalog` script, or `python -m cli`).

`data/` (catalog and cache DBs) and `out/` are local state next to `pyproject.toml`. Do not commit them.

## Rules to keep

- **Reservation wording.** бронювання is an employer statement, not an automatic deferment. UI and README must say current military-registration documents are required and the terms are confirmed in the interview.
- **Sources.** The Djinni reservation + remote filter is the confirmed source. DOU is kept only with the official badge (`search=бронювання` and `from=badge`). Work.ua uses remote + `deferment=1`. Robota.ua uses remote + `isReservation`. None of them is limited to an IT industry/rubric; after the official reservation mark, only engineering/IT titles are kept. Default focus is engineering and product IT.
- **No Cloudflare-bypass toolkit.** Chrome is used only because some sites refuse plain requests. When a site asks "verify you are human", wait for the person in an attended run, and fail fast in scheduled runs.
- **Catalog merge.** Merge by URL. A failed or incomplete source never deactivates its old rows, and neither does a source that returned no jobs. "New", "changed" and "closed" mean what the latest successful refresh did, so they need at least two successful refreshes. Tracked fields are in `TRACKED_FIELDS`. Dates and snippets are deliberately not compared.
- **Marks.** `set_marks` takes the write lock first (`BEGIN IMMEDIATE`) so quick clicks cannot overwrite each other. Marking "not for me" clears favorite, and the reverse.
- **Web security.** Default bind is `127.0.0.1`. With `--host`, `AllowedHosts` accepts only private IPs, never other names (DNS rebinding). POSTs must be same-origin. `/refresh` works only from the local machine. CSP is sent on HTML pages only.
- **Text.** UI copy is Ukrainian and English: add every string to `web/frontend/i18n.py` with both languages and the same `{placeholders}`. CLI help and README are English.

## Style

- Python 3.15, `ruff` line length 100, rules E/F/I/UP/B. E501 is ignored, because the formatter wraps code and HTML, CSS, SQL and regex stay on one line.
- Tests use `pytest` and temporary directories. Network calls and Chrome are mocked.
- In `web/frontend/assets/script.py` the JavaScript is a plain string, not an f-string, so braces need no doubling. A regex backslash is written `\\` there.

## Verifying UI changes

Change the web UI only with a browser check. Seed a scratch catalog, run it on a spare port (for example 8799), and check desktop and a phone width, in both languages, plus the actions you changed. Then stop the server, clear any device emulation, and leave no Chrome or Playwright processes running.

## Working agreements

- Do not commit, force-push, or change git config unless asked.
- The service may be running on 8765 with old code. After changes, tell the user to restart it. A restart starts a full crawl.
