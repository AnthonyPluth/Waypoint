# Gotchas

What usually goes wrong when driving Waypoint with `tools/control`, and what to do about it.

## The clock is frozen

- The server and the seed run under libfaketime at `FROZEN_NOW` in `waypoint/verify.py` (2026-06-15, noon, UTC), and the browser's clock is fixed at the same moment with its time zone set to UTC. "Today" on every page is that day, whatever the real date is. The demo trips are dated relative to it, so what is "next up" or "in 2 days" never moves.
- Without libfaketime nothing starts. `doctor` says so and prints the install line (`sudo apt-get install libfaketime`). It works on Linux only, because macOS has no `LD_PRELOAD`.
- A bug that only happens as time passes (a countdown, a job that runs at an hour) can't be reproduced here: write a test with fake time.

## The browser starts the way a flow's does, not a page's

- `make verify` sets up offline access in the browser (a virtual passkey, then Settings → Offline on `localhost`) before it visits each page, so the images show the app with offline access working. A new session hasn't: Upcoming then says "Offline access isn't available on this device". Run `tools/control offline`, then `goto` the page, and the screenshot is byte for byte the page's image in `docs/src/assets/screenshots/` (when the Chromium is the same build).
- Passkeys need a host name, not an IP address, so `offline` moves the session to `http://localhost:<port>` (the same server). `goto` stays on the host the page is on; a flow with `"host": "localhost"` opens there.
- `flow` runs in a new browser, as make verify's flows do, so it has none of the session's offline access, and `reset` gives a new browser too. Right after a flow the session is the flow's browser as it ended (fake data and an offline switch included): look around, then `reset`.

## Flows

- Each make verify page and flow runs on its own server and fresh copy of the demo data, so a flow starts from the seed. `tools/control flow <name>` runs on your session's data: if you changed something, run `reset` first. A flow that changes data (adds a trip, dismisses a review item) doesn't pass twice on the same data.
- Flows that fake a reply (`fake_labels`, `fake_first_run`, `fake_archive` and the rest) change only what the page's later requests see, and only until the browser is replaced. There is no mailbox, AI or flight-status service behind the demo server: it can't reach the internet, so anything that needs one fails or is faked.
- A flow with `viewports` only runs there (`more-menu` is phone only, `open-settings` desktop only). Run it at the other width and it fails at its first step; the `notes` in the answer say so.
- After every screenshot the flow checks again the `expect_text` steps since its last action. A screenshot that scrolls or closes something fails the flow with `check_lost`.
- A flow's images go to `artifacts/control/flows/`, at every width (make verify writes them at phone and desktop only), named as make verify names them.

## What a session doesn't check

- make verify also runs an accessibility audit on every page and flow (axe, 44 px tap targets at phone width, a visible focus ring on every tab stop) and a reduced-motion pass, and fails on them. A session doesn't: a clean `console` and `network` here is not a pass. Run `make verify PAGES="trips"` (or `poetry run python run.py verify --flow <name>`) before you push a UI change.
- `oauth-approve`, the page for approving an assistant's connection, needs the assistants make verify registers first. It can't be opened by `goto`.

## Sizes and the theme

- Phone is 440×956 (an iPhone 17 Pro Max) and desktop is 1280×800, the only two widths make verify shoots. `laptop` (1024×768), `wide` (1440×900) and `zoomed` (853×533, a 1280 px window at 150% zoom) are there for the flows that list them. There is no other tablet width: look at 768 to 1023 px in a browser by hand.
- The app is dark only: make verify, and so this session, shows the dark theme. There is no light theme to check.
- `screenshot` is the whole page; `screenshot --viewport` is the first screen (make verify's `-hero` images). Both scroll to the top first.

## Settling and flakes

- `screenshot`, `goto` and `wait-settle` wait as make verify does before an image: the network idle (up to 3 seconds), fonts loaded, no animation running (up to 3 seconds), then a short settle. If it never settles the answer says what was still going, in `notes` or `stillLoading`; that is a bug in the page, and it will show as a note in make verify's report too.
- The pointer stays where the last click left it, as in make verify, so a hovered row shows its buttons in the image.
- Raster flakes are rare: an edge or a rounded corner that comes out one level apart between runs. Take the shot again before you believe a one-pixel difference.

## One session per checkout

- A control session never takes make verify's ports or data, so it can run beside one, but it adds load. `start` refuses a machine that is busy (more than 1.5 runnable processes per CPU) unless you pass `--anyway`, and `doctor` names a make verify that is running.
- There's one session per checkout. A second `start` says one is running. `stop` it, or keep using it.
- A session stops by itself after 30 idle minutes (`--idle-minutes`). If a command then reports `stale_session` or `no_session`, run `start` again.

## Targets

- Use the names `snapshot --text` shows: `click button "Save"` is `click button Save`. Text matching ignores case and matches substrings; add `--exact` for an exact match.
- More than one visible match is an error that lists them. Pick one with `--nth`, or name it more exactly.
- Text that starts with `-` goes after `--`: `type textbox Amount -- -5`.
- The flows use Playwright selectors (`a[href^='#trip/'] >> visible=true`); a target that starts like a selector (`#id`, `.class`, `[attr]`, `tag[attr]`, `css=`, `text=`) is used as one.
