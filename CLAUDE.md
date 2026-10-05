# Claude Code notes

Repo conventions, commands and layout are in [AGENTS.md](AGENTS.md); read it first, especially "Waypoint's promises".

## Model routing

Pick the cheapest model that can do the job well. An issue names its model (the "Agent task" template); when delegating to a subagent, set its `model` accordingly:

- **Haiku**: file and symbol searches, listing usages, summarizing a file, boilerplate, mechanical renames, docs typos.
- **Sonnet**: normal implementation, bug fixes with a clear cause, writing or updating tests, small refactors, UI work, a vendor email parser with its fixtures, PR review of routine changes.
- **Opus**: architecture and design decisions, hard or unclear debugging, migrations, and anything security- or privacy-sensitive: auth, OIDC, sessions, `secretbox`, backups, the Gmail OAuth flow and token storage, the mail scanner's path from message to stored fields, trip visibility, loyalty and Known Traveler number storage, and the optional AI fallback.

When unsure, start one tier lower and escalate if the first attempt misses. Don't spawn a subagent for a task that takes a couple of tool calls to do inline.
