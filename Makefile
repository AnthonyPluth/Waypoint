# The checks to run before you push: `make check` runs ruff, mypy, import-linter, Waypoint's own Semgrep rules, the fleet
# checks, the feature map's and the API contract's checks, the Python tests (in parallel, as CI does), the web app's
# type-check, ESLint, Vitest tests and build, and the docs site's build, each once. The other targets run one part of it. The security scans (Semgrep's registry packs, Trivy, zizmor, pip-audit, npm audit, CodeQL)
# run only in CI, on the pull requests they can affect.
# Python commands go through Poetry, as in docs/src/content/docs/contributing/development.md.

PYTHON ?= poetry run python
NPM ?= npm
# The tools come from the Poetry environment (pyproject.toml's dev group, which `poetry install` adds), at the
# versions CI runs. mypy has to run there anyway, to see Waypoint's dependencies.
RUFF ?= poetry run ruff
MYPY ?= poetry run mypy
LINT_IMPORTS ?= poetry run lint-imports
UNITTEST_PARALLEL ?= poetry run unittest-parallel -t . -s tests -j 4
# Waypoint's own Semgrep rules (.semgrep/waypoint.yml), at the version .github/workflows/security.yml pins (change both
# together). Semgrep isn't in the Poetry environment: it pins dependencies of its own and doesn't run on Python 3.14,
# so it goes through pipx, on pipx's own Python.
SEMGREP ?= pipx run semgrep==1.146.0

.PHONY: check lint python-lint frontend-lint semgrep test test-parallel test-pg fix \
	frontend-check frontend-typecheck frontend-test frontend-build docs docs-build verify feature-map feature-map-check \
	fleet-checks api-contract api-contract-check pr-screenshots

# frontend-lint is a prerequisite of both lint and frontend-check, and make runs it once.
check: lint feature-map-check api-contract-check fleet-checks test-parallel frontend-check docs-build

# Ruff, mypy and import-linter's boundaries (the contracts in pyproject.toml) for Python, ESLint over the web app and
# waypoint/static (the same lint CI runs), and Waypoint's own Semgrep rules.
lint: python-lint frontend-lint semgrep

python-lint:
	$(RUFF) check .
	$(MYPY)
	$(LINT_IMPORTS)

# Waypoint's own rules for the paved paths (.semgrep/waypoint.yml): first that each rule flags its failing examples and only
# those (.semgrep/examples/), then the code. The ESLint rules' examples are frontend/src/lint-rules.test.ts.
semgrep:
	$(PYTHON) .semgrep/check_examples.py $(SEMGREP)
	$(SEMGREP) scan --metrics=off --disable-version-check --error --config .semgrep/waypoint.yml waypoint run.py frontend/src frontend/index.html frontend/package.json pyproject.toml

test:
	$(PYTHON) -m unittest discover tests

# The tests across 4 processes, the command CI runs (about 3x faster than `make test`), measuring coverage, and the
# floor it must meet (tools/coverage_floor.py): new code comes with the tests that run it.
test-parallel:
	$(UNITTEST_PARALLEL) --coverage --coverage-rcfile pyproject.toml
	poetry run coverage json -q -o coverage.json
	$(PYTHON) tools/coverage_floor.py coverage.json

# The same, against the Postgres at $$DATABASE_URL (an empty database is fine; see docs/src/content/docs/contributing/development.md).
test-pg:
	@test -n "$$DATABASE_URL" || { echo "Set DATABASE_URL, e.g. postgresql://waypoint:waypoint@127.0.0.1:5432/waypoint" >&2; exit 1; }
	$(UNITTEST_PARALLEL)

# Applies ruff's safe fixes (unused imports and the like); review the diff before committing.
fix:
	$(RUFF) check --fix .

# Reinstalled whenever package-lock.json is newer, so a pull that adds a dependency picks it up.
frontend/node_modules: frontend/package-lock.json
	cd frontend && $(NPM) ci --no-audit --no-fund
	touch frontend/node_modules

# The web app's type-check, ESLint, Vitest tests (with the coverage floor in frontend/vite.config.ts) and build, as CI
# runs them.
frontend-check: frontend-typecheck frontend-lint frontend-test frontend-build

frontend-typecheck: frontend/node_modules
	cd frontend && $(NPM) run check

frontend-lint: frontend/node_modules
	cd frontend && $(NPM) run lint

frontend-test: frontend/node_modules
	cd frontend && $(NPM) run coverage

frontend-build: frontend/node_modules
	cd frontend && $(NPM) run build

docs/node_modules: docs/package-lock.json
	cd docs && $(NPM) ci --no-audit --no-fund
	touch docs/node_modules

# The documentation site (Astro Starlight), with live reload at http://localhost:4321/Waypoint/.
docs: docs/node_modules
	cd docs && $(NPM) run dev

# Builds the site into docs/dist and checks every link between its pages, as docs.yml does.
docs-build: docs/node_modules
	cd docs && $(NPM) run build

# Runs the real app on made-up demo data and drives it with Playwright: each page at phone, tablet and desktop widths, plus
# the scripted flows in frontend/verify/flows. Screenshots (full page, and `-top`: the viewport only), console errors and
# failed requests go to artifacts/verify/; it
# fails on a console error or a 5xx. `make verify PAGES="upcoming settings"` visits only those pages.
verify: frontend/node_modules frontend-build
	$(PYTHON) run.py verify $(PAGES)

# The feature map (docs/feature-map.json and its docs page): each route's handler, web app callers, tests and docs.
# feature-map-check fails when it is out of date or a route has no test (tools/feature_map_allowlist.txt only shrinks).
feature-map:
	$(PYTHON) tools/feature_map.py

feature-map-check:
	$(PYTHON) tools/feature_map.py --check

# The API contract (docs/openapi.json and frontend/src/lib/api-types.ts), generated from the routes and the types their
# handlers are annotated with (waypoint/server/contract.py). api-contract-check fails when either is out of date.
api-contract:
	$(PYTHON) tools/api_contract.py

api-contract-check:
	$(PYTHON) tools/api_contract.py --check

# Pushes make verify's `*-top.png` screenshots to the pr-screenshots branch (pr-$(PR)/) and prints the markdown for the
# PR's comment (tools/pr_screenshots.py). `make pr-screenshots PR=12 FILES="artifacts/verify/upcoming-phone-top.png …"` picks
# files; trailers for the commit go in $PR_SCREENSHOTS_TRAILERS. Demo data only: the repository is public.
pr-screenshots:
	@test -n "$(PR)" || { echo "usage: make pr-screenshots PR=<pull request number> [FILES=\"…\"]" >&2; exit 2; }
	@$(PYTHON) tools/pr_screenshots.py $(PR) $(FILES)

# Checks that replaced instructions (tools/fleet_checks.py): one Alembic head, a test for each new migration, the
# workflows' conventions, and the Co-Authored-By trailer on your commits since main, as CI checks a pull request's.
fleet-checks:
	$(PYTHON) tools/fleet_checks.py --commits origin/main..HEAD
