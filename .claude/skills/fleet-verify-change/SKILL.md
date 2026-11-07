---
# vendored from fleet v3.0.0 (plugins/fleet/skills/verify-change/SKILL.md) by `fleet sync`; edit it in fleet, not here: `fleet drift` fails on any change
name: fleet-verify-change
description: Use before marking a pull request ready for review, in a repository whose pyproject.toml sets [tool.fleet.verification]. Lists the change's dimensions (each user-visible behaviour, failure path, migration, permission and invariant), verifies each with the verification guides for the changed paths where the repository has them and the app's own tools and verify skills, and writes the Verification block into the pull request's description - every dimension verified with evidence from this session, or not verified with the reason.
---

# Verify the change and record it

The pull request's description says, one dimension at a time, what was verified, how, and on what evidence, and names what couldn't be verified and why. "Testing" says what was run (`make check`, specific tests); the Verification block says, per behaviour the change touches, whether it was checked. Reviews read it, `fleet checks` parses it, and the monthly report counts the gaps that keep coming back, so the block is a record, not a claim.

## When this applies

Before the pull request is marked ready for review, in a repository whose `pyproject.toml` has a `[tool.fleet.verification]` table. While the table has `required = false`, a missing or malformed block is a warning on the pull request; with `required = true` it fails `fleet checks` on a ready pull request. Write the block either way.

## List the dimensions

Read the diff (`git diff origin/main...HEAD`) and the issue, and write down every dimension the change touches:

- each behaviour a user sees: a page, a flow, a command, an API response, a message;
- each failure path: every new error, rejection, early return or timeout, and what the user sees then;
- each migration, and the data it moves;
- each permission, token or grant, and when it ends;
- anything `AGENTS.md` or `.github/agent-review/invariants.md` calls an invariant that the change comes near.

A change with one dimension has one row. A refactor still has the behaviours it must not have changed.

## Read the area guides first

Where `[tool.fleet.verification]` also sets `guides` (a directory of verification guides, one per area of the app), read the guides for the changed paths before verifying anything:

1. `git diff -z --name-only --no-renames origin/main...HEAD | fleet verification areas --json --stdin0` (the paths NUL-separated on stdin, so one run sees the whole diff, however long, and a path with spaces, newlines, quotes or a leading `-` stays one path) names every area whose `## Paths` globs match a changed path (both names of a renamed file count), with each guide's steps and gaps, and lists the paths no guide covers.
2. For each dimension in a named area, verify it the way the guide's `## How to verify` says: those are the commands, flows, fakes and tests the area is checked with.
3. A dimension the guide lists under `## Not verifiable yet` is `not verified`, and its How gives the guide's reason and what would change it.
4. A dimension you verified some other way than its guide says (a step the guide lacks, or one that didn't apply) says why in its How column, so a reviewer sees that the guide was read and why it was set aside.

Paths no guide covers are verified as below, and the `fleet-verification-guide` skill can write a guide for them once the change is done; the `verification-guides` check lists them as a warning on the pull request. Without `guides`, skip this step.

## Verify each one

Use the area's guide where there is one, and otherwise the repository's own tools, in this order of preference:

1. The app's verify skill (`.claude/skills/verify-*/`), which says how to run the app and drive its flows, and `make verify` or the control smoke where the repository has one: for anything on screen or in a flow.
2. A test that fails before the change and passes after, run in this session: for logic, failure paths and migrations.
3. A manual step you ran in this session, with its command and output.

Never mark a dimension `verified` on reasoning, on a test you didn't run, or on a run from another session. If the session lacks what a dimension needs (a fake, a flow, a fixture, a credential, a device), the dimension is `not verified`, and its How says what is missing and what would make it verifiable.

## Write the block

In the description's "Verification" section (add the heading after "Testing" if the template lacks it), between the two marker lines, each alone on its line:

```md
## Verification

<!-- fleet-verification -->
| Dimension | Status | How | Evidence |
| --- | --- | --- | --- |
| Settings page shows the new toggle | verified | `make verify`, flow `settings-toggle` | `screenshots/flow-settings-toggle-desktop.png` |
| Toggle rejected without the permission | verified | `tests/test_settings.py` | `test_a_viewer_cannot_change_the_toggle` passed |
| Sync against a live account | not verified | no fake for the provider; a fake under `tests/fakes/` would make it testable | - |
<!-- /fleet-verification -->
```

The rules the parser holds:

- the header row is exactly `| Dimension | Status | How | Evidence |`, and there is at least one row;
- Status is exactly `verified` or `not verified`;
- a `verified` row has a non-empty How (the command, flow, test or manual step) and non-empty Evidence (a test name, a flow name, a screenshot path, a command's output summary); `-` and `—` count as empty;
- a `not verified` row's How says why it couldn't be verified and what would make it verifiable;
- the markers start at the first column, and every row (the header, the separator and each dimension) starts with `|` at the first column: a row without its leading pipe, or one after a `>`, list or heading marker or an HTML tag, is rejected as ambiguous; a pipe inside a cell is written `\|`; between the markers, every line with an unescaped `|` is read as a row, so a note there escapes its pipes or stays outside;
- one block per description; lines between the markers without a pipe are ignored;
- the only code fence the parser knows is a plain top-level one (backticks or tildes at the start of the line); an indented, listed or quoted fence, an indented or prefixed marker or row, a tab on a fence line or a multiline HTML comment is rejected as ambiguous. That rule reaches the whole description, not only the record: write every fence at the first column and outside lists, anywhere in the description, command output in "Testing" included; with `required = false` a rejection is only a warning.

Every gap goes in as `not verified` with its reason, never left out: a reviewer who sees the gap can judge it, and one who doesn't can't. Keep "Testing" for what was run. `fleet verification show --pr N` prints the block as the tools read it.

## Before marking ready

Run `fleet checks --pr-event <payload>` locally where you can, or read the "fleet checks" run on the pull request: a warning or error there names the line and the rule. Fix the description, which re-runs the check, rather than arguing with it in a comment.
