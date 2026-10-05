#!/usr/bin/env bash
# Runs the independent reviewer for .github/workflows/agent-review.yml, in the current directory (review/: main's
# prompt.md, schema.json and AGENTS.md, the change, and the pull request's tree in pr/), writing its answer to
# output.json. Run from main's copy, never a pull request's.
#
# Authentication: ANTHROPIC_API_KEY (an API key) if it is set, else CLAUDE_CODE_OAUTH_TOKEN (a Claude Pro or Max
# subscription's token, from `claude setup-token`). Only the one used is passed on.
#
# Isolation, the same either way: a fresh session (nothing saved, nothing resumed) whose only tools are Read, Grep and
# Glob, confined to this directory (--restricted); no settings files (user, project or local), so a pull request's
# .claude/settings.json grants nothing and runs no hook; no CLAUDE.md, skills, plugins, hooks, slash commands or MCP
# servers (--safe-mode, --strict-mcp-config with none, CLAUDE_CODE_DISABLE_CLAUDE_MDS, disableAllHooks). Not --bare,
# which skips the same things but reads only ANTHROPIC_API_KEY (never the subscription's token) and also drops Grep and
# Glob; the flags above do its job for both kinds of secret.
#
# Needs: CLAUDE (the claude executable), MODEL, BUDGET (US dollars, the most it may spend), and one of the two secrets.
set -euo pipefail

: "${CLAUDE:?}" "${MODEL:?}" "${BUDGET:?}"

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  unset CLAUDE_CODE_OAUTH_TOKEN
  echo "Authenticating with the API key."
elif [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
  unset ANTHROPIC_API_KEY
  echo "Authenticating with the Claude subscription's token."
else
  echo "::error::Neither an ANTHROPIC_API_KEY nor a CLAUDE_CODE_OAUTH_TOKEN secret."
  exit 1
fi

export CLAUDE_CODE_DISABLE_CLAUDE_MDS=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

status=0
"$CLAUDE" --print "$(cat prompt.md)" \
  --tools Read,Grep,Glob --allowedTools Read,Grep,Glob --permission-mode dontAsk --restricted --safe-mode \
  --setting-sources "" --settings '{"disableAllHooks":true}' --strict-mcp-config --mcp-config '{"mcpServers":{}}' \
  --disable-slash-commands --no-session-persistence --model "$MODEL" --max-budget-usd "$BUDGET" \
  --json-schema "$(cat schema.json)" --output-format json > output.json || status=$?
echo "Claude Code exited with $status"
