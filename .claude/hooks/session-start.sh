#!/bin/bash
# Claude Code on the web: get a fresh session's container ready to run what CI runs (make check), before the session
# starts. The backend needs Python 3.14 (Poetry), which the container doesn't come with; the web app needs its npm
# packages. Safe to run again: each step is quick when there's nothing to do.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0   # on your own machine, docs/src/content/docs/contributing/development.md says how to set up
fi
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"

# Python 3.14 for Poetry's environment (uv fetches a build if the container has none).
if ! command -v uv >/dev/null 2>&1; then
  python3 -m pip install --quiet --user "uv==0.12.21"
  export PATH="$HOME/.local/bin:$PATH"
fi
py=$(command -v python3.14 || uv python find 3.14 2>/dev/null || true)
if [ -z "$py" ]; then
  uv python install 3.14
  py=$(uv python find 3.14)
fi
if ! command -v poetry >/dev/null 2>&1; then
  python3 -m pip install --quiet --user "poetry==2.5.1"
  export PATH="$HOME/.local/bin:$PATH"
fi
poetry env use --quiet "$py" >/dev/null
# Poetry's virtualenv can pick another Python than the one asked for (it has made a 3.11 environment named py3.14):
# if so, make the environment with 3.14's own venv where Poetry expects it.
venv=$(poetry env info --path)
if ! "$venv/bin/python" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 14))' 2>/dev/null; then
  rm -rf "$venv"
  "$py" -m venv "$venv"
fi
# Waypoint's dependencies and the tools CI runs (ruff, mypy, coverage, ...: pyproject.toml's dev group).
poetry install --no-root --no-interaction

# The web app's packages (npm install, not ci: the container's cache keeps them between sessions).
(cd frontend && npm install --no-audit --no-fund)
