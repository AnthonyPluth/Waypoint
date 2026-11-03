---
# vendored from fleet v1.1.0 (plugins/fleet/skills/verification-guide/SKILL.md) by `fleet sync`; edit it in fleet, not here: `fleet drift` fails on any change
name: fleet-verification-guide
description: Use in a repository whose pyproject.toml sets guides under [tool.fleet.verification], to write or update the verification guide for an area the user names, or for the changed paths that the verification-guides check lists as covered by no guide. A guide says which paths an area covers, how to verify a change there (each command, flow, fake or test run once in this session) and what can't be verified yet, why, and what would change that.
---

# Write a verification guide

A verification guide gives every session the same method for one area of the app: which paths it covers, how to verify a change there, and what can't be verified yet. The `fleet-verify-change` skill reads the guides for a change's paths before it verifies anything, and `fleet checks` holds them to the files they name, so a guide is a tested recipe, not notes.

## When this applies

In a repository whose `pyproject.toml` sets `guides` under `[tool.fleet.verification]` (the guides directory, relative to the repository root). Write or update a guide:

- for an area the user names ("the settings pages", "the import job");
- for the paths the `verification-guides` check listed as covered by no guide (`no verification guide covers N changed path(s): ...`): extend the guide whose area they belong to, or write a new one;
- for a guide the check called stale (a glob that matches no tracked file): fix the glob, or the guide, after a move or a removal.

The guide doesn't replace the app's feature map or its verify skill, and this skill doesn't edit either: read them, link to them, and leave them as they are.

## Inspect the area

Before writing a line, find out what the area is and how it can be checked:

1. The code: its routes, pages, CLI commands, jobs and the modules behind them (`git ls-files` and the source).
2. The app's verify tooling: its verify skill (`.claude/skills/verify-*/`), `make verify` or the flows its driver runs, the control or smoke commands, the fakes under its tests, and the tests that cover the area.
3. The feature map, where the app has one: which features live in the area and how each is checked today.

## The format

`<guides>/<area>.md`, the file name being the area's name (lowercase letters, digits and `-`):

```md
# Settings

The settings pages and the API behind them.

## Paths

- `src/app/settings/**`
- `src/web/pages/settings/**`
- `tests/test_settings.py`

## How to verify

- `make verify`, flow `settings-toggle`: the page at phone and desktop widths, screenshots under `screenshots/`.
- `tests/test_settings.py`: the API's validation and permission checks.

## Not verifiable yet

- The email sent on a change: there is no fake mail server, so the message can't be read in a test; a fake under `tests/fakes/` would make it verifiable.
```

The rules `fleet verification guides` and the check hold:

- line 1 is `# <Area>`; a line or two of prose may follow before the first section;
- then `## Paths`, `## How to verify` and `## Not verifiable yet`, in that order, each once, and no other headings;
- every line in a section is a list item (`- ...`) or an indented continuation of one; no code fences, so a command goes inline in backticks;
- `## Paths` lists globs relative to the repository root, optionally in backticks: `*` and `?` stay within one directory, `**` is a whole segment matching any number of directories (`src/**`, `**/test_*.py`), a directory is written `<dir>/**`, and there are no spaces, brackets, braces, leading `/`, `./` or `!`;
- every glob matches at least one tracked file (`git ls-files`); one that matches nothing is a stale guide and fails `fleet checks`;
- `## How to verify` lists steps, each naming a real command, flow, fake or test;
- `## Not verifiable yet` lists each gap, why it can't be verified and what would change that, or is the single item `Nothing`.

## Every step is run once

Run every command and flow you put under "How to verify" once in this session, and read its output: a step that doesn't run, or doesn't check what it says, stays out. When a step needs something the session lacks (a fake, a fixture, a credential, a device), it isn't a step: it goes under "Not verifiable yet" with that reason and what would provide it. Every gap gets a reason; a gap without one is a guess.

## Before you finish

- `fleet verification guides` lists the area with its globs, and `fleet verification areas <a path in the area>` names it.
- `fleet checks` passes the `verification-guides` check: the guide parses and every glob matches a tracked file.
- The pull request says which steps you ran and what they printed.
