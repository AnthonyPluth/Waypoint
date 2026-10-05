# Claude Code notes

Repo conventions, commands and layout are in [AGENTS.md](AGENTS.md); read it first, especially "Waypoint's promises".

## Model routing

Use Sonnet wherever it can do the job, and Haiku where it's enough. An issue names its model (the "Agent task" template); when delegating to a subagent, set its `model` accordingly:

- **Haiku**: file and symbol searches, listing usages, summarizing a file, boilerplate, mechanical renames and edits, docs typos.
- **Sonnet**: the default for everything else: features, migrations, bug fixes, tests, refactors, UI, vendor email parsers, and the security- and privacy-sensitive work too (auth, sessions, `secretbox`, the Gmail flow, the mail scanner, trip visibility, loyalty numbers, the AI fallback). The checks hold that work to AGENTS.md's promises (Semgrep's promise rules, `tests/test_every_route.py`, `tests/privacy.py`'s `no_leaks`, the coverage floors, strict mypy for `domain/` and `providers/`), and the independent agent review reads every pull request.
- **Opus**: only when Sonnet's attempt has missed (a check or the review keeps failing on the same thing), for a design decision the issue leaves open, or for debugging whose cause stays unclear.

Don't spawn a subagent for a task that takes a couple of tool calls to do inline.
