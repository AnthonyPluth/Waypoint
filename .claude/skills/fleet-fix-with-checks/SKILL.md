---
# vendored from fleet v1.0.0 (plugins/fleet/skills/fix-with-checks/SKILL.md) by `fleet sync`; edit it in fleet, not here: `fleet drift` fails on any change
name: fleet-fix-with-checks
description: Use when fixing a review finding or a CI failure whose kind is listed under "Mistakes that keep coming back" in AGENTS.md, or when the same mistake shows up a second time. The fix then includes the check that would have caught it - a lint rule, a Semgrep rule with examples, a type or a test - and the AGENTS.md item's parenthesis names that check.
---

# Fix it with a check

A mistake that repeats gets a check. Fixing the one place a reviewer pointed at leaves the next pull request free to make the same mistake; a check stops it for every pull request after this one.

## When this applies

- A review finding ("Agent review" or "Second review") or a CI failure has a `kind` that is an item under `AGENTS.md`'s "Mistakes that keep coming back".
- The same mistake has come up before: in another pull request's review, in the monthly "Repeated review findings" issue, or earlier in this one.

A one-off mistake of a kind no item lists is fixed on its own; this skill doesn't apply.

## Choose the check

Pick the cheapest check that would have failed on the mistake as it was written, and passes on the fix:

1. **A lint rule** (ruff, ESLint) when an existing rule or option catches it: turn it on, or narrow its configuration to the paths that need it.
2. **A Semgrep rule** in `.semgrep/` when the mistake is a code pattern no linter knows (a call that must go through one helper, a value that must never reach a log). Every rule comes with a failing and a passing example under `.semgrep/examples/`: a line marked `# ruleid: <rule-id>` above the code it must flag, and one marked `# ok: <rule-id>` above code it must leave alone (`//` in TypeScript). The examples are checked with the rules on every run, so a rule that stops matching fails.
3. **A type** when the mistake is mixing up values: strict mypy, a `NewType` for an id or a unit, a `Literal` for a closed set of strings, a TypeScript type for the frontend.
4. **A test** when only behaviour shows it: a failure path, a round trip, an access that must end. Write it so it fails before your fix (run it against the old code once) and passes after.

A check `fleet checks` runs, or an app check in the app's `extra-checks`, is right when the mistake is about the repository's layout rather than its code (a file in the wrong place, a generated file left stale).

## Update the item

The item's parenthesis says how it is checked. After adding the check, edit the item under "Mistakes that keep coming back":

- `(human-judged: …)` becomes `(checked: <the rule id, or the test file>)` when the check covers the whole item, or `(partly checked: <what checks which part>; <what stays human-judged and why>)` when it covers part of it.
- An item already `checked` or `partly checked` gets the new check added to its list.
- An item inside fleet's markers (`fleet:begin` / `fleet:end`) is fleet's text: change it in fleet, not in the app. The app's own items, after the block, are the app's to edit.

If no check can express the mistake, say why in the pull request; the item stays human-judged and its parenthesis says why.

## Never silence a rule

Don't fix a failing check by turning it off, adding an ignore or `noqa`, loosening its pattern, raising a threshold, skipping or weakening a test, or deleting an example. If a check is wrong, fix the check, show in the pull request why it was wrong, and keep its examples or tests passing. A suppression the owner has already agreed to says so on the line, with the reason.

## In the pull request

Say which finding or failure led to the check, name the check, and show it failing before the fix and passing after (the command and its output).
