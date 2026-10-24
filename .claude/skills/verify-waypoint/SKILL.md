---
name: verify-waypoint
description: Run, drive, screenshot or verify Waypoint's web app in a real browser on demo data, with tools/control (a session you start once, then one command at a time). Use it to check a UI change works, reproduce or investigate a UI bug, look at a page at phone and desktop widths, run one of make verify's flows step by step, or get screenshot evidence for a pull request, instead of writing a throwaway Playwright script.
---

# Verify Waypoint in the real app

`tools/control` drives the real app on made-up demo data: a demo server under make verify's frozen clock and a Chromium on it, kept alive between commands. Every command prints JSON (`--text` for a readable form); a failure is `{"ok": false, "error": {code, message, hint}}`, and the hint says what to do next.

Use it while you work, to see what you changed. `make verify` is still the batch check (every page and flow at both widths, the accessibility audit) and the only source of the images in `docs/src/assets/screenshots/`.

## The loop

1. **Launch.** `tools/control doctor --text`, then `tools/control start`. It refuses a busy machine (`--anyway` overrides) and leaves a running make verify alone. Rebuild first (`cd frontend && npm run build`) after a change under `frontend/src`, or you see the old app; a session started before the build keeps serving the old files until `reset`.
2. **Drive.** `goto <route>`, `snapshot --text` (the roles and names to target), `click link Trips`, `type textbox Search london`, `press Escape`, `viewport desktop`, `flow <name>`.
3. **Prove.** `screenshot` at `viewport phone` and at `viewport desktop`, then open each image and look at it. Read `console` and `network`: make verify fails a page on a console error or a 5xx, so treat them as failures too.
4. **Clean up.** `tools/control stop`. After a crash: `tools/control cleanup`.

## Evidence to attach

- The commands you ran and what they returned (paste the JSON or `--text`).
- What you saw in the screenshots at phone (440×956) and desktop (1280×800).
- For a pull request that changes the UI, the images are the ones `make verify` writes to `docs/src/assets/screenshots/` (AGENTS.md, "Git and PRs"), never anything from `artifacts/control/`.

## Safety

- Demo data only, on the session's own loopback server, with none of your real settings (no `DATABASE_URL`, sign-in or secret key reaches it) and no way out to the internet. It refuses other URLs and never touches a real instance.
- The repository is public: put no real data (names, confirmation codes, loyalty numbers) in commands, flows, screenshots or PR text.
- What it reports is scrubbed: requests as paths with ids as `:id` and never a query string, calendar feed addresses as `/feed/…`, console text without amounts, email addresses or long tokens.
- Everything it writes is under `artifacts/control/`, ignored by git. Never commit it, and never copy an image into `docs/src/assets/screenshots/` by hand.
- `eval` is read-only unless you pass `--write`. `reset`, `stop` and `cleanup` take `--dry-run`.

## References

- [references/cli.md](references/cli.md): every command and option. It is generated from the CLI's help (`make verify-skill`); `tools/control <command> --help` prints the same text.
- [references/gotchas.md](references/gotchas.md): what usually breaks, and why.
- [references/journeys.md](references/journeys.md): recipes you can copy (reproduce a bug, check a layout at both widths, set up offline access, compare before and after, run a flow).
