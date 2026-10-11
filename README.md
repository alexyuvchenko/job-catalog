# Remote IT jobs with бронювання

Search public IT listings in Ukraine for remote roles whose employers say they can reserve an employee from mobilization (бронювання).

Бронювання is the employer’s statement that the role can be included in reservation of conscripted employees. It is not an automatic deferment. You still need current military-registration documents, and the outcome depends on the company’s status and the rules in force. Confirm the terms in the interview.

The search reads five boards:

- **Djinni** — the official “Бронювання” filter plus remote work. Every result from this filter is treated as confirmed.
- **DOU** — remote listings that mention бронювання. A result is kept only when the vacancy page has DOU’s бронювання badge, so a booking-system product mention is not treated as a reservation offer.
- **Work.ua** — remote IT jobs with the “Бронювання працівників” filter (`deferment=1`).
- **Robota.ua** — remote vacancies whose listing is marked as employee reservation, limited to the IT rubric.
- **Jooble** — paused for now. Existing Jooble rows stay until fetching is turned back on.

Djinni and DOU are read with plain HTTP requests. Work.ua and Robota.ua refuse those, so they open in Google Chrome off-screen. Chrome needs to be installed. Requests go one at a time, with a short pause.

### “Verify you are human”

If a page asks for that check, Chrome moves on screen and the search waits up to five minutes for you to finish it. Then the window goes back off-screen and reading continues. This happens only when someone is likely at the machine: a one-off search, the first refresh after `--serve` starts, and «Оновити зараз». Later scheduled refreshes skip that site instead, so no window opens while you are away, and its previous vacancies stay. Ctrl+C ends the wait.

## Setup

Python 3.15 and [uv](https://docs.astral.sh/uv/) are required.

```bash
uv sync
```

That creates `.venv` from `uv.lock`, installs this package, and installs Ruff for development.

## Search once

```bash
uv run job-search --keyword python --pages 2
uv run job-search --keyword "qa" --full-remote-only --min-salary 2000 --english B1
uv run job-search --focus all --pages 4
uv run job-search --keyword python --json
uv run job-search --keyword python --pages 2 --open
```

| Flag | Meaning |
| --- | --- |
| `--keyword` | Role or technology. Empty shows every matching IT role. |
| `--pages` | Listing pages to read from each site, from 1 to 10. The default is 2. |
| `--focus engineering` | Developers, QA, DevOps, data, security, product, project, design, analysts. This is the default. |
| `--focus all` | Also keep HR, marketing, and sales roles at these companies. |
| `--full-remote-only` | Hide hybrid roles that also name a city. |
| `--min-salary 2500` | Hide USD ranges whose top is below this number. Roles without a salary, and roles listed in UAH or EUR, stay. |
| `--english B2` | Hide roles that state a lower level. Unknown English stays. DOU usually does not state a level on the card. |
| `--min-years` | Hide roles whose stated experience is below this many years. Unknown experience stays. |
| `--since-days 14` | Only vacancies dated within this window. |
| `--no-verify` | Skip opening DOU vacancy pages. Those rows stay marked as unverified. |
| `--refresh` | Ignore the saved DOU badge cache and check the pages again. Without it, a missing badge is rechecked after a day and a found one after a week. |
| `--json` | Print JSON instead of a text list. |
| `--open` | Open the HTML report when the search finishes. |

Results are written to `out/jobs.html`, `out/jobs.json`, and `out/jobs.csv`. `data/cache.sqlite` remembers vacancies already seen and whether a DOU page had the badge. The next run marks new links. A one-off search does not change the catalog below.

## Catalog

The local service keeps the remote engineering list and refreshes it on its own. A refresh uses no keyword and keeps reading until each site runs out of pages, up to 100 pages per site. It then merges the results:

- a new vacancy is added
- a vacancy that is still listed is updated
- a vacancy that disappeared from a site that responded in full is marked inactive
- if a site fails, or only some of its pages load, the vacancies it already had stay, and the ones it returned are still added or updated

```bash
uv run job-search --serve
uv run job-search --serve --interval 3 --port 8765
```

Open http://127.0.0.1:8765 . The page is a FastAPI app that listens on this computer only unless you pass `--host`. The first refresh starts immediately, and Chrome opens off-screen for Work.ua and Robota.ua. Later refreshes run every 6 hours. Leave the process running. Logs go to the terminal.

| Flag | Meaning |
| --- | --- |
| `--port` | Address port. The default is 8765. |
| `--host` | Address to listen on. The default is `127.0.0.1`, which only this computer can reach. `0.0.0.0` lets other devices on the network open the page. See [Open it on a phone](#open-it-on-a-phone). |
| `--public-host NAME` | DNS name a reverse proxy or tunnel will send. Repeat for each name. See [Publish on the internet](#publish-on-the-internet). |
| `--no-register` | Do not let visitors create accounts. |
| `--interval` | Hours between refreshes. The default is 6. Values are kept between 15 minutes and 7 days. |
| `--catalog-pages` | Safety ceiling for pages per site. The default is 100. Each site still stops when its own listings run out. |

The page adapts to the screen. On a phone each vacancy is a card, on a tablet it is a compact table, and on a wide monitor the table uses the extra width. The page filters the saved catalog. It does not start a crawl until you press «Оновити зараз» or the interval comes due. That button only works from the catalog page itself. While a refresh runs, the list stays put and reloads once the new data is saved.

The chips above the list show how each site did in the last saved refresh:

| Chip | Meaning |
| --- | --- |
| Green, with a count | The site was read to the end. |
| Amber, with a count | Only part of the site was read. Its older vacancies were kept. |
| Red, «помилка» | The site could not be read. Its older vacancies were kept. Hover for the reason. |

In the reservation column, «підтверджено» (“confirmed”) means the site or its badge states the reservation. «без бейджа» (“no badge”) means the DOU vacancy page could not be checked. «знято» (“closed”) means the vacancy is no longer listed at its source.

### Language

The page is in Ukrainian and English. The UK/EN switch in the corner is remembered in a cookie. Without a choice, the browser's language decides: English for `en`, Ukrainian otherwise. You can also open `/?lang=en`. The saved HTML report is Ukrainian. Tooltips that come from a site (the reservation evidence) and error messages from a failed refresh stay in the language they were written in.

### What changed in the last refresh

Each refresh is compared with the one before it, so you can see what moved. A coloured edge on the row and a tag next to the title show it:

| Mark | Meaning |
| --- | --- |
| green, «нова» / “new” | The vacancy first appeared in the last refresh. |
| amber, «змінено» / “changed” | Title, company, place, format, salary, English level, experience, category, or reservation changed. Hover the tag to see which. A vacancy that was closed and came back also counts. |
| red, «знято» / “closed” | The vacancy disappeared from its source in the last refresh. It shows only with «Показати вакансії, яких уже немає» ticked, or when you filter by closed. |
| grey background | You already opened it. |
| blue «EN» | The description is written in English. |

Dates and text snippets are not compared, because relative dates such as “2 weeks ago” change every day. The numbers in the status line above the list (“added 10, changed 1, closed 3”) link to the matching filter. The first refresh has nothing to compare with, so nothing is marked until the second one finishes.

### Your own marks

Every row has buttons that save at once, without leaving the page:

- ♥ favorite
- ✕ «не для мене» (“not for me”): hides the vacancy. A toast offers Undo. A vacancy is either a favorite or not for you, so one clears the other.
- ✓ viewed. Opening the title also marks it viewed. Press ✓ again to unmark.
- ★ rating from 1 to 5. Press the same star again to clear it.

Marks are stored in `data/catalog.sqlite` by account and link, and they survive refreshes. If a vacancy disappears and returns, its marks are still there. Sign in from the catalog page. The first visit can create the account. Anyone who can open the address can create an account and read the shared list. Marks, ratings, and filters belong to the account that set them, so another account does not see yours. See [Open it on a phone](#open-it-on-a-phone).

### Filters and pages

Besides the text, source, salary, English, experience, and remote filters, you can narrow by:

| Filter | Options |
| --- | --- |
| My marks | all except «не для мене» (default), everything, favorites, not viewed, viewed, rated, only «не для мене» |
| My rating from | 1★ and up, up to 5★ |
| Changes in the last refresh | added, changed, closed |
| Description language | English, Ukrainian |

Filters apply when you change a select or press «Застосувати». The account remembers the filters, sort, and page size, and the next visit opens with them. «Скинути» clears that saved view. On a phone the filters and the legend start folded, with the number of active filters in the title. The list shows 25, 50 (default), 100, or 200 rows per page. Use the page links, or press «Показати ще» to add the next rows under the current ones without reloading.

The date, job, and company headings sort the list. Date starts with the newest vacancy, and a job or company name starts at the beginning of the alphabet; click the same heading again to reverse it. A vacancy with no date stays at the end. On a phone those headings are buttons above the cards. Sorting stays in place when you filter or turn the page. «Скинути» clears it.

### Open it on a phone

Start the service so it listens on the network, and keep the computer awake and on the same Wi-Fi as the phone:

```bash
uv run job-search --serve --host 0.0.0.0
```

The log prints the address to use, for example `http://192.168.1.20:8765`. You can also find it with `ipconfig getifaddr en0` on macOS. Open that address on the phone. macOS may ask once to allow incoming connections.

- Sign in with the same account on the phone to see the same marks, ratings, and filters. A different account has its own.
- Anyone who can reach the port can create an account and read the shared catalog, so use this only on a network you trust.
- Only an IP address works in the browser. Names other than `localhost` are rejected.
- «Оновити зараз» is disabled for other devices, because a refresh opens Chrome on the computer running the service. Use it on that computer.
- Guest Wi-Fi often blocks devices from reaching each other. If the phone cannot connect, try the main network.
- For access away from home without opening your network, run a private tunnel such as [Tailscale](https://tailscale.com/) on both devices. Its `100.x.x.x` addresses are accepted.

### Publish on the internet

The process should still listen on this computer. Put HTTPS in front of it (a reverse proxy or a tunnel). Do not forward port 8765 on the router: Cactus often has no public IPv4, and a raw port has no TLS.

Anyone who can open the public address can create an account and read the shared catalog. Pass `--no-register` if you want only accounts created on this computer.

```bash
uv run job-search --serve --public-host catalog.example.com
```

Point the proxy or tunnel at `http://127.0.0.1:8765` and use that DNS name. A temporary Cloudflare tunnel is:

```bash
cloudflared tunnel --url http://127.0.0.1:8765
```

Then restart with the hostname it prints, for example `--public-host random-words.trycloudflare.com`. Open `https://…` in the browser, not `http://`. Only the names you listed are accepted. `/docs` is off. «Оновити зараз» still only works on this computer.

Ctrl+C finishes the site already in progress, closes Chrome, and saves the sites read in that run. Sites that were not reached keep their previous vacancies. The catalog changes only when a refresh is saved, so stopping in the middle does not wipe the list.

The catalog, marks, filters, and refresh require a signed-in session. Pages redirect to `/login`. `/api/jobs`, `/api/jobs/state`, and `/fragments/rows` answer 401. `/health` stays open. A call to `/api/jobs` with no filter query uses the account’s saved filters.

| Request | What it returns |
| --- | --- |
| `GET /login`, `POST /login` | Sign in. The session cookie is `HttpOnly` and lasts 30 days. |
| `GET /register`, `POST /register` | Create an account and sign in. |
| `POST /logout` | End this browser’s session. |
| `GET /` | The catalog page. Without a session, this redirects to `/login`. With a session and no filter query, it opens the account’s saved filters. `/?reset=1` clears them. |
| `GET /health` | Whether a refresh is running, stored counts, the last finish time, and the last error. `GET /api/status` is the same. It answers 503 when the database cannot be read. |
| `GET /?page=2&per_page=100` | A page of the list. `per_page` is 25, 50, 100, or 200. Other values fall back to the default. |
| `GET /api/jobs` | The filtered list as JSON, not paged. It adds `active`, `change`, `changes`, `language`, `favorite`, `hidden`, `rating`, and `viewed` to each vacancy. Query parameters match the page: `q`, `source`, `min_salary`, `english`, `min_years`, `full_remote_only`, `include_inactive`, `mine` (`all`, `favorites`, `unviewed`, `viewed`, `rated`, `hidden`), `min_rating`, `change` (`added`, `changed`, `closed`), `language` (`en`, `uk`), `sort` (`date`, `job`, `company`), `dir` (`asc`, `desc`). |
| `POST /api/jobs/state` | Saves your marks. JSON body: `url` and any of `favorite`, `hidden`, `rating` (0 to 5), `viewed`. Omitted fields stay as they are. Answers with the stored marks, or 404 for an unknown vacancy. Only accepted from the page's own origin. |
| `GET /fragments/rows` | The next rows as JSON for «Показати ще». Takes the same query as the page. |
| `GET /docs` | Interactive API docs. |
| `POST /refresh` | Starts a refresh when one is not already running, then returns to `/`. |

The database is `data/catalog.sqlite`. `data/` and `out/` are local state. After each saved refresh the service rewrites `out/jobs.html`, `out/jobs.json`, and `out/jobs.csv` from the active list. If those files cannot be written, the catalog itself is still kept and the page says so.

## Layout

The code is in `src/` (an application, not a library), with tests in `tests/`.

- `core` — models, classification (remote, salary, English, language), constants, paths, logging
- `sources` — one module per job board
- `network` — page fetch and off-screen Chrome
- `storage` — the SQLite catalog (`catalog.py`), its filters and sorting (`filters.py`), returned records (`records.py`), and shared SQLite settings (`sqlite.py`)
- `jobs` — the refresh loop (`refresh.py`) and the one-off search (`search.py`)
- `web` — the FastAPI app (`app.py`), host check and response headers (`security.py`), page language (`language.py`), and the routes in `auth/` and `catalog/`
- `web/frontend` — pages, rows, components, the Ukrainian and English text (`i18n.py`), the saved report (`report.py`), and `assets/` (CSS and JavaScript)
- `cli.py` — the command

`uv run job-search` is the command. `uv run python -m cli` does the same thing.

`data/` and `out/` are created next to `pyproject.toml`, so run the app from a checkout of this repository.

## Development

```bash
uv run ruff check
uv run ruff format
uv run pytest
```
