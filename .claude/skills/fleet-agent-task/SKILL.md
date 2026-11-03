---
# vendored from fleet v1.1.0 (plugins/fleet/skills/agent-task/SKILL.md) by `fleet sync`; edit it in fleet, not here: `fleet drift` fails on any change
name: fleet-agent-task
description: Use when writing or drafting a GitHub issue that an AI coding agent will carry out - an issue finished in one session and one pull request, with the sections Context, Scope, Out of scope, Acceptance criteria, Tests, Depends on and Model, and the model chosen by the rules here.
---

# Writing an agent task

An agent task is an issue one agent finishes in one session and one pull request. It decides everything a user would notice, so the agent never has to choose; anything it leaves open, the agent asks about instead of guessing.

## Size

One session, one pull request. If the work needs two pull requests that land one after the other, or two areas that could be worked on at once, write two issues and say which depends on which.

## Sections

Write them in this order, each as a bold heading line (`**Context**`):

- **Context**: why the work is needed and what exists today, with the real file names, commands and statuses (`src/app/settings.py`, `make verify`, "Merge gate"). Never a made-up or approximate path: check it exists.
- **Scope**: what to build, as a list. Name the files to add or change and the behaviour each must have; settle every decision a user would notice.
- **Out of scope**: what the agent must not do, including the neighbouring work another issue does (name that issue).
- **Acceptance criteria**: checkboxes (`- [ ]`), each one something the pull request can show: a command's output, a test that fails before the change, an image. "Works well" isn't a criterion.
- **Tests**: the test files to add or extend and the checks to run.
- **Depends on**: the issues that must merge first, or "Nothing".
- **Model**: the model to run the session on, and why in a few words.

## The model

- **Opus** by default.
- **Fable** (`claude-fable-5-1`) for security work, the review workflows, CI secrets, anything that handles untrusted pull request content, and security scanning.
- **Sonnet** only for mechanical copying: renames, typo fixes, moving text without changing it.

## Drafts that refer to each other

While a set of issues is still a draft, refer to one that doesn't exist yet by its key in double curly braces, `{{FLEET-SYNC}}`; replace each with the issue's number once it's created. A key is short, upper case and stable (`PROJECT-PIECE`).

## No personal data

In a public repository, an issue holds nothing personal: no person's name, address, account, email address, host or domain of anyone's own, token, key or anything copied from a real instance of an app. Examples use made-up values. In a private repository, still keep it to what the work needs.

## A UI issue

An issue that changes anything a person sees adds this criterion: the UI matches the signed-off design (name the issue that signed it off), any change to layout, flow or visual style needs the owner's sign-off before merge, and the pull request shows `make verify` images at phone and desktop width. The design-signoff skill says what counts.
