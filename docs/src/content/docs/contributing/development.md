---
title: Development
description: Setting up, running the checks, changing the database, the code layout and releases.
sidebar:
  order: 1
---

Contributor conventions (style, tests, commit and PR rules) are in [AGENTS.md](https://github.com/AnthonyPluth/Waypoint/blob/main/AGENTS.md).

## Setup and checks

```bash
poetry install --no-root                               # dependencies and the tools CI runs (ruff, mypy, ...), into .venv
poetry run python run.py                               # run Waypoint at http://localhost:8765 (build the web app first)
poetry run python -m unittest discover tests           # the test suite (SQLite)
DATABASE_URL=postgresql://... poetry run python -m unittest discover tests   # the same tests against Postgres
poetry run coverage run -m unittest discover tests && poetry run coverage report   # how much they cover
poetry run unittest-parallel -t . -s tests -j 4        # the suite across 4 processes, as CI runs it on SQLite: about 3x faster (`make test-parallel`)
poetry run mypy                                        # type-check the Python (settings in pyproject.toml)
poetry add <package>                                   # add a dependency (updates pyproject.toml and poetry.lock)
```

To run the tests on Postgres as CI does, start a throwaway database. Its data directory is in memory and nothing is flushed to disk, which makes the tests fast and means a crash loses the database: use these settings only for a database that lives for one test run, never for a real one. Docker’s default 64 MB of shared memory isn’t enough for the schemas the tests make.

```bash
docker run -d --rm --name waypoint-test-pg --shm-size=1g --tmpfs /var/lib/postgresql/data -p 5432:5432 -e POSTGRES_USER=waypoint -e POSTGRES_PASSWORD=waypoint -e POSTGRES_DB=waypoint postgres:16 -c fsync=off -c synchronous_commit=off -c full_page_writes=off -c shared_buffers=512MB -c max_connections=300
DATABASE_URL=postgresql://waypoint:waypoint@127.0.0.1:5432/waypoint make test-pg
docker stop waypoint-test-pg
```

- `make test-pg` checks that `DATABASE_URL` is set, then runs the suite against that Postgres with one test process per CPU: at least 4, at most 16 (`tools/test_jobs.sh`; `PG_JOBS=8 make test-pg` sets it).
- `max_connections` needs 30 for each process plus 100, so 300 serves the cap of 16.
- The database must be UTF-8. A cluster you make yourself needs `initdb -E UTF8 --locale=C.UTF-8`; the `postgres` Docker image already is.
- A test that needs a database of its own (`own_database` in `tests/shared.py`) borrows one of a few schemas each test process keeps. They are built once from the schema and emptied when the test is done (`TRUNCATE`, with the airport and airline reference rows restored). A schema a test still holds a connection to is freed by ending that connection.
- Schemas are named `p_<process id>_<n>`. A later run drops the ones left by a process that no longer exists, so running the suite twice on the same database gives the same result.

`make test-timings` prints the slowest tests and classes and the time spent making and emptying databases (on Postgres when `DATABASE_URL` is set). The “Docker image” workflow prints the same in its run summary when started by hand with “timings” ticked. Neither is part of `make check`.

A new database, for the tests and for a first start, is built in one step (`db.create_fresh`): the tables from `waypoint/storage/schema.py`, the airport and airline rows, and the stamp for the newest migration, with no migration replayed. A database that already has tables and a version is upgraded by `upgrade head`. `tests/test_migrations.py` builds one database each way and compares them.

The migration history up to revision `0034` is one baseline, `0034_baseline.py`, written out in full with its airport and airline rows (`down_revision = None`). The earlier migrations and their tests are in the repository’s history. A backup made at an older revision is refused with a message saying so: restore it with the last release before the squash, then take a new backup.

### The checks

`make check` runs everything to run before you push, each tool once:

- ruff, mypy and import-linter, and Waypoint’s own Semgrep rules;
- the fleet checks (see [Merging](#merging)), the feature map and the API contract checks;
- the Python tests, on SQLite and in parallel as CI runs them;
- the web app’s type-check, ESLint, Vitest tests and build, and the docs site’s build.

`make setup` installs the backend’s and the web app’s dependencies on a fresh checkout. `make lint`, `make test` (serial, for a clearer failure), `make test-parallel` and `make frontend-check` each run one part.

Only CI runs the security scans, each on the pull requests it can affect (`.github/workflows/security.yml`): Semgrep, Trivy, zizmor, pip-audit, npm audit and CodeQL. The Postgres tests also run only in CI; run them yourself as above.

For the quick checks on every commit (ruff, trailing whitespace, YAML and TOML syntax, merge-conflict markers, large files), install [pre-commit](https://pre-commit.com) and run `pre-commit install` once.

## One paved path

Most things have one way to do them, and `make lint` (so `make check`, and CI) fails on a copy of the old way. Use the helper instead. Where the old way is right for a reason, say why on the line (`# nosemgrep: <rule id> -- why` in Python, `// eslint-disable-next-line no-restricted-syntax -- why` in the web app) rather than switching the rule off.

| Don’t | Use |
| --- | --- |
| `urllib.request.urlopen` or `build_opener` outside `waypoint/tls.py` | `tls.urlopen` |
| `bool(body…)`, `float(body…)` or `int(body[…])` in `waypoint/server/api/` | `waypoint/validate.py` |
| `sa.text(f"…")`, or SQL built with `+`, `%` or `.format` | SQLAlchemy expressions, or `sa.text(":name")` with bound parameters |
| `date.today()` in the sync and provider modules | the `today` the caller passes (`today or date.today()` as its default is fine) |
| `datetime.utcnow()` | the local time, or `datetime.now(timezone.utc)` for another system |
| `(e as Error).message` in the web app | `errMsg(e)` from `lib/act.ts` |
| `fetch(` outside `lib/api.ts` | `api()` |
| `.catch(() => {})` with nothing in the braces | `ignoreFailure` from `lib/act.ts` |
| a comment (`#`, `//`, `/* */`, `<!-- -->`), apart from a tool’s directive such as `# noqa` or `// eslint-disable-next-line` | a name that says it; the why goes in the commit message or the docs (`tools/no_comments.py`, ESLint’s `waypoint/no-comments`) |

The Python rules are in `.semgrep/waypoint.yml`, each with a failing and a passing example in `.semgrep/examples/`. `make semgrep` runs the examples, then the code, as CI’s Semgrep job does, through `pipx` at the version `.github/workflows/security.yml` pins. The web app’s rules are in `frontend/eslint.config.js`, with their examples in `frontend/src/lint-rules.test.ts`.

## The web app

The web app is Svelte 5 and TypeScript in `frontend/`, with Tailwind CSS, components in the shadcn-svelte style on Bits UI, and Lucide icons. Waypoint serves its build at `/`, so build it once before running Waypoint from a checkout. It needs Node 26: `.nvmrc` names it, for `nvm use` or `fnm use`, and CI reads the same file.

```bash
cd frontend && npm ci                 # its packages, into frontend/node_modules
npm run dev                           # http://localhost:5173/ (reloads as you edit; start Waypoint on 8765 too)
npm run check                         # type-check it (CI runs this)
npm run lint                          # ESLint over it and the service worker (CI runs this)
npm test                              # unit tests for its pure logic and components, with Vitest (CI runs these too)
npm run coverage                      # the same, measuring how much of the web app they run (the frontend badge)
npm run build                         # into waypoint/static/app/, which Waypoint serves at / (the Docker image does this)
```

## The documentation

This site is [Astro Starlight](https://starlight.astro.build) in `docs/`, published to GitHub Pages by `.github/workflows/docs.yml` on every push to `main` that changes it. Each page is a Markdown file in `docs/src/content/docs/`, in a folder per sidebar group (`start/`, `privacy/`, `reference/`, `contributing/`). Its front matter sets the title, the description and its place in the group (`sidebar.order`). Images go in `docs/src/assets/`.

```bash
make docs          # http://localhost:4321/Waypoint/, reloading as you edit
make docs-build    # builds it into docs/dist and fails on a broken link between pages
```

Link to another page by its address, base included: `[Configuration](/Waypoint/reference/configuration/)`, or `/Waypoint/start/docker/#errors-and-logs` for a heading. Link to files in the repository with their GitHub address.

## Verifying a change in the real app

Unit tests don’t show a layout or a picker working, so run a change to the web app in a browser too. `make verify` (or `python run.py verify [page…]`):

- makes a temporary database and fills it with the demo data, the made-up data `python run.py demo` adds and never anyone’s real data;
- starts Waypoint on a free port and drives it with Playwright;
- sets up offline access in the browser before it visits a page, with a virtual passkey on `localhost` (the one the `authenticator` flow step adds), so every page image shows the app with offline access working rather than the “Offline access isn’t available on this device” notice;
- visits each page (the pages the web app has at the time) at phone (440 px, an iPhone 17 Pro Max) and desktop (1280 px) widths, and writes two images of each to `docs/src/assets/screenshots/`, which is committed: the full page, `<page>-<width>.png` (often thousands of pixels tall), and the first screen, `<page>-<width>-hero.png` (the viewport only: 440×956 on a phone, 1280×800 on a desktop). The README and the docs pages embed the hero images;
- writes a flow’s captures (`flow-<name>-….png`) to `artifacts/verify/` instead, since they aren’t byte-stable between runs. A flow’s extra widths (laptop, wide, zoomed) check and write no image;
- writes `report.json` (console errors, failed requests) to `artifacts/verify/`, which is not committed;
- exits non-zero, and says which page, width and request, on a console error, an uncaught error in the page, a 5xx response, a failed scripted step or an accessibility problem.

A run of every page empties the images folder first, so a removed page leaves no stale image. A run of some pages (`PAGES=…`) rewrites only theirs.

It also audits every page and flow it visits for accessibility, and fails on:

- a contrast, label, name, zoom or other [axe-core](https://github.com/dequelabs/axe-core) WCAG 2.2 AA violation;
- a control that shows no focus ring when you Tab to it;
- at phone width, a button, link or field smaller than 44 × 44 px (inline links in a sentence and the map’s marks are exempt).

When every page is checked, it also loads each one with `prefers-reduced-motion: reduce` and fails if any animation is still running. Motion is small and purposeful (the sheet, a status chip changing, the countdown), and one rule at the end of `frontend/src/app.css` turns all of it off for someone who asked for less.

```bash
make verify                          # every page, and the scripted flows
make verify PAGES="settings"         # only these pages (and the flows that start on them)
make verify VERIFY_JOBS=2            # two servers and browsers at a time (the default is the CPU count, at most 4)
poetry run python run.py verify --jobs 1 --flow add-trip   # one flow only, on one server
```

A full run is concurrent:

- `make verify` seeds the demo data once, copies it for each of the `VERIFY_JOBS` (or `--jobs`) servers, and starts one Waypoint on its own port from each copy, under the same frozen clock, with a browser for each.
- Scripted flows change the data (they add and delete bookings and trips, merge, flip settings), so they never share a server. Every flow goes, with all its widths, to one server’s queue in the order of its file name. The queues are balanced by the flows’ length and are the same on every run.
- The pages and the reduced-motion checks change nothing, so the servers share them. They are visited first, before any flow touches a server, by whichever browser is free.
- The images a page writes don’t depend on the number of servers. The report (`artifacts/verify/report.json` and the console) lists the problems in the order of a serial run, each naming its page, width and flow.
- A server that dies or a browser that cannot start is itself a problem. The visits it leaves undone are listed as not run, and the other servers carry on.
- `VERIFY_JOBS=1` (or `--jobs 1`) runs everything on one server, one visit after another. `--flow NAME` (repeatable) runs only those flows and visits no page, for fixing one.
- A flow must not depend on the data another flow left behind: it can run beside any other flow’s changes, or alone.

It uses the Chromium already installed under `PLAYWRIGHT_BROWSERS_PATH` (`/opt/pw-browsers` by default); without one, run `npx playwright install chromium` in `frontend/` once.

A scripted flow is a small JSON file in `frontend/verify/flows/`: a list of steps such as opening Settings and filling in a field. A pull request that changes the UI adds or edits a flow for it. The format is in [`frontend/verify/flows/README.md`](https://github.com/AnthonyPluth/Waypoint/blob/main/frontend/verify/flows/README.md).

### Screenshots in a pull request

A pull request that changes the UI commits the images `make verify` changed, so its diff shows each page before and after. A pull request with no UI change has nothing to commit, and says so.

Running `make verify` twice on one tree gives identical files, so an image changes only when the UI or its data does:

- The clock is frozen. The server and the demo seed run under `libfaketime` on a fixed date (`FROZEN_NOW` in `waypoint/verify.py`), and the browser’s clock is set to the same date.
- Each image is taken from the top of the page with animations finished, after the page’s requests settle, with a fixed colour profile, one raster thread and no sub-pixel text.
- It needs Linux (the dev container and CI; macOS doesn’t support `LD_PRELOAD`) and fails with the install line when `libfaketime` is missing.

```bash
sudo apt-get install libfaketime    # Debian and Ubuntu
make verify
git add docs/src/assets/screenshots
```

The repository is public: only `make verify`’s made-up demo data is ever committed, so look at the images you add. Waypoint is dark only, so `make verify` runs in the dark colour scheme and its screenshots are the dark app. The README embeds the hero images from `docs/src/assets/screenshots/`, so a change to them shows in the README too.

## Changing the database

Edit `waypoint/storage/schema.py`, then generate a migration and check it over:

```bash
poetry run alembic revision --autogenerate -m "add a column"   # writes waypoint/storage/migrations/versions/…
poetry run alembic check                                       # the schema and migrations agree
```

A column that refers to another table’s row gets a foreign key, `schema.refers(table, column, "users.id", ondelete)` (a hypothetical `segments.trip_id` would be `schema.refers(segments, "trip_id", "trips.id", "CASCADE")`):

- `CASCADE` when the row belongs to what it refers to (a trip’s flights);
- `SET NULL` when it only points at it.

A backup restores with the keys checked when the restore commits, so rows may come in any order.

Give each migration the next four-digit number after main’s newest (`0035_…py`, `revision = '0035'`) and a test of its own in `tests/test_migrations.py`: a method named `test_0035_…` that downgrades to the revision before it, writes the data it changes, upgrades and checks the result. `make check` and CI fail when there is more than one Alembic head (two branches that each added the next number), a number is used twice, or a migration has no test (`tools/fleet_checks.py`).

Waypoint applies the migration on its next start. Queries, in the app and in the tests, are SQLAlchemy statements over the ORM models (`Connection.execute()` doesn’t take SQL text), compiled for whichever database is in use. [Queries with SQLAlchemy](/Waypoint/contributing/orm/) is the guide.

## Code layout

| Path | What |
|---|---|
| `run.py` | Starts the server; `backup`, `restore`, `demo` and `verify` commands |
| `waypoint/server/` | The web server: `handler.py` (who may reach what, security headers, request limits, reading bodies and sending answers, `serve()`), `routes.py` (the API’s route table: finding a request’s route and answering it), `api/` (the API, one module per area), `common.py` (shared handler helpers) and `contract.py` (the API contract’s types) |
| `waypoint/domain/` | What Waypoint works out from your data: the trips, the mail parsers (`mail/`) and `demo.py`, the sample data. It doesn’t import the server |
| `waypoint/providers/` | Each outside service Waypoint reads from or sends to. Providers don’t import each other; what two of them share sits in a module of its own |
| `waypoint/storage/` | The database, at the bottom: it imports nothing from the domain, the providers or the server, and only it imports the database drivers and Alembic |
| `waypoint/storage/db.py`, `schema.py`, `models.py`, `settings_keys.py`, `secretbox.py`, `backup.py` | Database connections (SQLite or Postgres), the schema and its ORM models, the settings’ names, secrets encrypted at rest, backups |
| `waypoint/storage/migrations/`, `alembic.ini` | Alembic migrations, applied on start-up (with foreign keys off on SQLite while they run: batch mode remakes tables). The first, `0034`, is the baseline that replaced the earlier chain. Repairs for data saved by older versions are migrations too, run once, not code run at every start. A migration that removes data saves a backup first |
| `waypoint/tls.py`, `validate.py` | The only module that opens outbound connections (every https request goes through it); checking numbers and other input |
| `waypoint/dates.py`, `monitoring.py`, `oidc.py` | Date helpers; the log (scrubbed); OpenID Connect sign-in |
| `waypoint/verify.py` | The `run.py verify` browser check |
| `frontend/` | The web app (Svelte): `src/pages/` one file per page, `src/lib/` the API client, formatting and components |
| `waypoint/static/` | Files Waypoint serves beside the app: the service worker (`sw.js`), manifest, fonts, icons, and `page.css` for the sign-in pages. The web app builds into `waypoint/static/app/` |
| `tests/` | Unit and end-to-end tests, including a mock OIDC provider |
| `pyproject.toml`, `poetry.lock` | Dependencies (Poetry) |
| `data/` | Your database (not in Git) |

### Import boundaries

`make lint` (so `make check`, and CI) runs [import-linter](https://import-linter.readthedocs.io) over `waypoint/`, with the contracts in `pyproject.toml`:

- Only the server imports `waypoint/server/`: the domain, the providers, storage and the shared modules don’t.
- Only `waypoint/tls.py` opens outbound connections (`ssl`, `socket`, `http`, `websocket`, `requests`). The few modules that need one of these for another reason are listed, each with why. urllib can’t be split this way, so Semgrep keeps `urlopen` in `tls.py`.
- A provider doesn’t import another provider. What two of them share goes in a module of its own or in the domain.
- `waypoint/storage/` imports nothing from the domain, the providers or the server, and only it imports the database drivers and Alembic. Everything else reaches the database through `db.session()` and `db.connect()`.

When a contract breaks, move the code to where its import is allowed rather than adding an exception. A new provider module joins its provider’s contract, or gets one of its own.

## API handlers

A handler in `waypoint/server/api/` is listed in `routes.py`’s `ROUTES`, takes `(conn, query, body, *ids)` and returns the JSON to answer, or a `common.Response` for anything else (a download, a stream: `common.download` writes a download’s headers).

- A route that takes a file instead of JSON is marked `@common.upload(limit)`, and one that opens its own database sessions (a restore) `@common.own_session`.
- A handler checks everything it’s sent before using it. Numbers, whole numbers, days and on/off switches go through `waypoint/validate.py` (a switch sent as `"false"` is off); ids, query-string numbers and text fields through `server/common.py`’s `row_id`, `query_int` and `text`.
- What it can’t use, it refuses with `ApiError`: a 4xx and a message saying what’s wrong.

Anything else a handler raises is a bug. `routes.dispatch`, which answers the web app’s calls (`/api/…`), turns it into a 500 with only a reference, and logs and reports it with `monitoring.report(values=False)`: the error’s type and where it was raised, never what it said, which can quote the request or name a row. A database busy with something else (SQLite’s lock, or a Postgres lock timeout, deadlock or serialization failure: `db.is_busy`) is a 503, to try again.

The [feature map](/Waypoint/contributing/feature-map/) lists each route with its handler, the web app files that call it, its tests and its docs page. It is generated by `tools/feature_map.py`: run `make feature-map` after changing routes, `api(` calls, tests or docs. `make check` and CI fail when it is out of date, or when a route has no test and isn’t on `tools/feature_map_allowlist.txt`, a list of the routes that had none, which only shrinks.

### The API contract

Some routes have a typed contract with the web app, so a field renamed on one side fails a check instead of drifting silently. `Endpoints` in `frontend/src/lib/api-types.ts` lists the covered ones.

- **The backend.** The reply and request body types are TypedDicts in `waypoint/server/contract.py`. A covered handler is annotated with them: its return type is its reply, and the annotation on its body (third) parameter is what it takes (for a hypothetical trips route, `body: TripSet` and `-> TripSaved`). mypy then holds the handler to them. A body is what the web app sends, so the handler still checks every value with `waypoint/validate.py`. Where a reply is built from database rows (plain dicts to mypy), `tests/test_api_contract.py` calls the handler on sample data and checks the real reply against the contract.
- **The generated files.** `make api-contract` (`tools/api_contract.py`) reads the route table and those annotations and writes `docs/openapi.json`, an OpenAPI description of the covered routes, and from it `frontend/src/lib/api-types.ts`. Commit both; `make check` and CI fail when they are out of date. Don’t edit them by hand.
- **The web app.** Call a covered route with `apiCall` from `lib/contract.ts` (`api()` underneath), naming the route as `Endpoints` does (`"METHOD /path"`), with the address to call: `apiCall<"GET …">(address)`. The address, the method, the body and the reply are type-checked against the contract, so `npm run check` fails on a call or a field that no longer matches.

To cover another route: add its types to `contract.py`, annotate its handler, run `make api-contract`, switch its callers to `apiCall`, and add a call to `tests/test_api_contract.py` (which fails until every covered route is checked there).

## CI runners

CI runs on GitHub’s runners unless the repository variable `RUNS_ON` is set (Settings → Secrets and variables → Actions → Variables). Set it to a JSON list of runner labels, such as `["self-hosted", "linux", "x64"]`, and the jobs run on your own runners instead; delete it to go back to GitHub’s. GitHub doesn’t fall back by itself: while `RUNS_ON` is set and no runner with those labels is online, jobs wait in the queue.

Some jobs always use GitHub’s runners, whatever `RUNS_ON` says:

- a pull request that isn’t from this repository (a fork’s, including one whose fork has since been deleted), so code from outside the household never runs on its machines;
- Dependabot’s pull requests and runs, which run new versions of third-party dependencies;
- Agent review and the merge gate, which read pull requests’ content with secrets in reach;
- OpenSSF Scorecard, which publishes its results only from GitHub’s runners.

A self-hosted runner needs:

- Linux on x64, bash and git;
- Docker, because the Postgres tests run Postgres as a service container and the image build uses Docker Buildx with QEMU for ARM.

The setup actions install Python and Node themselves. Add the runner to this repository (Settings → Actions → Runners), not to an organization, and keep “Require approval for all external contributors” on (Settings → Actions → General).

`tools/fleet_checks.py` holds every job to this: a job’s `runs-on` is the shared `RUNS_ON` expression, or `ubuntu-latest` with a `# hosted: <why>` comment.

## Releases

Every push to `main` runs the tests and, at the same time, builds the image for `linux/amd64` and `linux/arm64` with the next version baked in, and checks that it starts. Nothing is published until the tests pass; then GitHub Actions:

1. pushes the image (already built, so this is quick) as `ghcr.io/anthonypluth/waypoint` tagged `latest`, `2.131.5` (and `v2.131.5`), `2.131` and `2`;
2. tags the version and publishes a [GitHub Release](https://github.com/AnthonyPluth/Waypoint/releases) with notes;
3. deletes untagged leftovers.

Every released version stays available, so you can pin one (`image: ghcr.io/anthonypluth/waypoint:2`) and upgrade when you choose.

Versions follow `vMAJOR.MINOR.PATCH`, decided by what has been merged since the last release. Pull request titles start with a type, which ends up in each merge commit’s message:

- `feat: …` bumps the minor version;
- `fix: …`, or anything else, bumps the patch;
- a `!` before the colon (`feat!: …`, `fix!: …`) bumps the major version, for a change that breaks an existing setup.

`#minor` or `#major` at the end of a line, or a line starting with `BREAKING CHANGE:`, work too. A message that only mentions them mid-sentence doesn’t count. The running version is shown under **Settings → Account**, in its Advanced section.

## Merging

A pull request is ready when its **Merge gate** status passes: every check on its head commit green (`.github/scripts/merge-gate.sh`). Besides the tests and the security scans, that includes:

- **Fleet checks** (`tools/fleet_checks.py`, `make fleet-checks`):
  - one Alembic head, and a test for each new migration;
  - the workflows’ conventions: bash by default, actions pinned by SHA with their version in a comment, `gh api` lists paginated;
  - each commit an AI agent wrote names its model in a trailer, `Co-Authored-By: Claude <Model> <version> <noreply@anthropic.com>`;
  - a test that was on `main` and is gone, or a line that skips a test or runs only some, needs a `Removes-Test: <name> — <why>` or `Skips-Test: <name> — <why>` trailer on one of the branch’s commits;
  - a raster image the branch adds or changes has to be a page image `make verify` writes: `<page>-phone.png`, `<page>-desktop.png` or their `-hero` variants in `docs/src/assets/screenshots/`, for a page in `frontend/verify/verify.mjs` (the visual regression baselines). Logo-catalogue images and files in `waypoint/static/` or `docs/public/` are allowed too; a hand-made before and after image fails.
- **Coverage floors** (`tools/coverage_floor.py`, run by `make test-parallel` and CI): the Python tests must cover 85% of the backend and 90% of each module in `waypoint/domain/`, `waypoint/providers/` and `waypoint/server/api/`. The web app’s floors are the thresholds in `frontend/vite.config.ts`. Raise them as coverage grows.
- **Every route** (`tests/test_every_route.py`): each route in the table needs sign-in, refuses a change without the app’s header or from another site, has its reply typed in the API contract, and has a docs page. None of these needs a test of its own.
- **Privacy** (`tests/privacy.py`): run code that handles mail, names or loyalty numbers inside `no_leaks(self, "CANARY-…", database=path)`. It fails if a canary value turns up in the clear in the log, Python’s logging, a request sent to another service (through `tls.urlopen`), or any table.
- **Agent review** (`.github/workflows/agent-review.yml`) is disabled: its trigger is commented out and the merge gate no longer requires its status, because Codex reviews pull requests. Turned back on, it needs one of two repository secrets (**Settings → Secrets and variables → Actions**): `CLAUDE_CODE_OAUTH_TOKEN`, for a Claude Pro or Max subscription (run `claude setup-token` and paste the token it prints), or `ANTHROPIC_API_KEY`, an API key from the Claude Console, which is used when both are set. `AGENT_REVIEW_BUDGET_USD` sets the most one review may spend, as Claude Code estimates it (3 US dollars), and `AGENT_REVIEW_MAX_TURNS` the most round trips to the model it may take (60). A review that hits either fails as an error rather than passing, so raise the limit and re-run it.

[Dependabot](https://github.com/AnthonyPluth/Waypoint/blob/main/.github/dependabot.yml) opens weekly pull requests to keep the GitHub Actions and the Python base image up to date; each one runs the tests before it can be merged.
