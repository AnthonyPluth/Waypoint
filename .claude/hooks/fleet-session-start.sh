#!/bin/bash
# vendored from fleet v2.2.0 (plugins/fleet/hooks/session-start.sh) by `fleet sync`; edit it in fleet, not here: `fleet drift` fails on any change
# Claude Code on the web: get a fresh session's container ready to run what CI runs (make check), before the session
# starts. The union of Waypoint's and Runway's hooks (docs/drift.md), configured by the app's .claude/hooks/fleet.conf:
#   PYTHON_VERSION  the Python Poetry's environment runs on (uv fetches a build if the container has none); empty skips
#                   Python and Poetry
#   FRONTEND_DIRS   the web app directories whose npm packages to install, space-separated
#   APT_PACKAGES    Debian packages the checks need (libfaketime for make verify), space-separated
#   NODE_CHECK      what must be in a complete node_modules, space-separated: a package name (it must import) or a
#                   file under node_modules (esrap/types/public.d.ts: it must exist); missing, the directory is
#                   reinstalled from its lockfile
# .claude/hooks/session-start.local.sh, when present, is sourced last, for the app's own steps. Safe to run again: each
# step is quick when there's nothing to do.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0   # on your own machine, the app's contributing docs say how to set up
fi
cd "${CLAUDE_PROJECT_DIR:-$PWD}"

PYTHON_VERSION=""
FRONTEND_DIRS=""
APT_PACKAGES=""
NODE_CHECK=""
if [ -f .claude/hooks/fleet.conf ]; then
  # shellcheck source=/dev/null
  . .claude/hooks/fleet.conf
fi

UV_VERSION="0.12.21"
POETRY_VERSION="2.5.1"

if [ -n "$PYTHON_VERSION" ]; then
  # pip --user installs uv and Poetry here; on the PATH first, a second session finds them without reinstalling.
  export PATH="$HOME/.local/bin:$PATH"
  if ! command -v uv >/dev/null 2>&1; then
    python3 -m pip install --quiet --user "uv==$UV_VERSION"
  fi
  py=$(command -v "python$PYTHON_VERSION" || uv python find "$PYTHON_VERSION" 2>/dev/null || true)
  if [ -z "$py" ]; then
    uv python install "$PYTHON_VERSION"
    py=$(uv python find "$PYTHON_VERSION")
  fi
  if ! command -v poetry >/dev/null 2>&1; then
    python3 -m pip install --quiet --user "poetry==$POETRY_VERSION"
  fi
  poetry env use --quiet "$py" >/dev/null
  # Poetry's virtualenv can pick another Python than the one asked for (it has made a 3.11 environment named py3.14):
  # if so, make the environment with the asked-for Python's own venv where Poetry expects it.
  venv=$(poetry env info --path)
  have=$("$venv/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)
  if [ "$have" != "$(echo "$PYTHON_VERSION" | cut -d. -f1,2)" ]; then
    rm -rf "$venv"
    "$py" -m venv "$venv"
  fi
  # The app's dependencies and the tools CI runs (ruff, mypy, coverage, ...: pyproject.toml's dev group).
  poetry install --no-root --no-interaction
fi

# make verify freezes the clock with libfaketime, and apps may need other packages: install what isn't there yet.
missing=""
for package in $APT_PACKAGES; do
  if ! dpkg -s "$package" >/dev/null 2>&1; then
    missing="$missing $package"
  fi
done
if [ -n "$missing" ]; then
  # shellcheck disable=SC2086
  if ! apt-get install -y --no-install-recommends $missing >/dev/null 2>&1; then
    # shellcheck disable=SC2086
    sudo apt-get install -y --no-install-recommends $missing >/dev/null 2>&1 \
      || echo "session-start:$missing isn't installed; the checks that need it will fail" >&2
  fi
fi

# A node_modules restored from the container's cache can be cut short or stale, and `npm install` takes it as done: lint
# and type errors then only show up in CI. NODE_CHECK names what such a cut leaves out.
node_modules_ok() {
  local dir=$1 entry slashes
  for entry in $NODE_CHECK; do
    slashes=${entry//[^\/]/}
    if { [[ $entry == @* ]] && [ ${#slashes} -ge 2 ]; } || { [[ $entry != @* ]] && [ ${#slashes} -ge 1 ]; }; then
      test -f "$dir/node_modules/$entry" || return 1
    else
      (cd "$dir" && node --input-type=module -e 'await import(process.argv[1])' "$entry") >/dev/null 2>&1 || return 1
    fi
  done
}

for dir in $FRONTEND_DIRS; do
  # npm install, not ci: the container's cache keeps the packages between sessions; --no-save: npm would otherwise
  # rewrite the committed lockfile.
  (cd "$dir" && npm install --no-save --no-audit --no-fund)
  if ! node_modules_ok "$dir"; then
    echo "$dir/node_modules is incomplete; reinstalling from the lock file" >&2
    (cd "$dir" && rm -rf node_modules && npm ci --no-audit --no-fund)
    node_modules_ok "$dir" || echo "$dir/node_modules is still incomplete: lint or type checks will fail" >&2
  fi
done

if [ -f .claude/hooks/session-start.local.sh ]; then
  # shellcheck source=/dev/null
  . .claude/hooks/session-start.local.sh
fi
