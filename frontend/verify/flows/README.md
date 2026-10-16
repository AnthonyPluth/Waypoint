# Scripted flows

Each `*.json` file here is a flow that `make verify` runs after visiting the pages, at phone, tablet and desktop widths (or the `viewports` it lists). A pull request adds steps by adding or editing a file.

```json
{
  "name": "open-settings",
  "page": "upcoming",
  "viewports": ["phone", "desktop"],
  "steps": [
    { "click": "a[href='#settings'] >> visible=true" },
    { "expect_text": { "selector": "h1", "text": "Settings" } },
    { "screenshot": "settings-open" }
  ]
}
```

- `page` is the route the flow starts on (default `upcoming`); `viewports` defaults to phone, tablet and desktop; `laptop` (1024 px), `wide` (1440 px) and `zoomed` (853 px, a 1280 px window at 150% zoom) are there for a flow that lists them. The app is dark only, so every flow runs in the dark colour scheme.
- A step has one action, and an optional `timeout` in milliseconds (default 10000). Selectors are [Playwright selectors](https://playwright.dev/docs/other-locators) (CSS, `text=…`, `role=…`).
  - `{"goto": "#route"}` opens a route of the app (or a full URL).
  - `{"select": {"selector": "label:has-text('What is it') select", "index": 1}}` chooses an option of a `<select>` by its position.
  - `{"click_if_present": selector}` clicks it when it shows up within a second (`timeout` changes that) and does nothing when it doesn't, for a step that only one width needs (a menu that exists on a phone).
  - `{"hover": selector}` moves the pointer over it (a hover state shows in the next screenshot); `{"click": selector}`, `{"fill": {"selector": …, "text": …}}`, `{"press": {"selector": …, "key": "Enter"}}`.
  - `{"upload": {"selector": "input[type=file]", "file": "tests/fixtures/flight_import/flighty.csv"}}` chooses a file of the repository (made-up data) in a file input; `{"scroll_to": selector}` scrolls it to the top of the screen, so the `-top` screenshot shows it.
  - `{"download": {"selector": "button:has-text('Save as image')", "name": "saved-image"}}` clicks it, waits for the file the browser downloads and saves it as `flow-<flow name>-<name>-<viewport>.png` (and `...-top.png`), so a PR can show what was saved.
  - `{"authenticator": "add"}` gives the page a virtual device check (a platform passkey with PRF, always verified), so a flow can set up offline access; `{"offline": true}` cuts the browser's connection (`false` restores it) and `{"reload": true}` reloads the page, through the service worker when offline.
  - `{"long_names": ", a suffix"}` adds the suffix to the names in the Stats reply (`name`, `city` and `hotel`) for the page's later loads, so a flow shows long names in every list; the demo data itself doesn't change. Put it before a `reload`.
  - `{"fake_labels": "Japan 2026, Taxes"}` answers the page's later requests for a mailbox's Gmail labels with those made-up names (the demo mailbox can't reach Google), and accepts a save.
  - `{"fake_ignored": "news.example, deals.example"}` answers the page's later requests for a mailbox's ignored senders with those made-up domains, and drops a domain from the list when it is stopped (nothing is stored); `{"fake_ignore": "news.example"}` answers an ignore on Review as done for that domain without changing the demo data.
  - `{"fake_destination": "Colorado & Texas"}` makes the page's later loads of the app's state say the AI fallback is on, and answers a request for a trip's suggested destination with that made-up text (the demo has no AI to ask). Put it before a `reload`.
  - `{"fake_first_run": "connect"}` makes the page's later loads show a household with no trips, in the given first-run state: `connect` (no mailbox), `scanning`, `review` (3 emails waiting) or `manual` (a connected mailbox, nothing waiting); nothing is stored. Put it before a `reload`.
  - `{"fake_merge_warning": "Sam Doe | Mia Doe"}` answers the page's later request to merge a trip with the warning a member gets when the two trips involve different people (the names before the bar will newly see this trip's bookings, the names after it the other trip's), and lets the confirmed request through to the demo data; the demo's household view is never asked, so a flow needs it to show the dialog.
  - `{"fake_archive": 400}` adds that many made-up past trips to the page's later loads of the trip list (copies of a demo trip with other names, places, airlines and dates; nothing is stored), to show a list the size of a long archive. Put it before a `reload`.
  - `{"wait_for": selector}` waits for it to appear; `{"expect_text": {"selector": …, "text": …}}` fails unless it contains the text within the timeout (it keeps looking while the page settles).
  - `{"screenshot": "name"}` saves `flow-<flow name>-<name>-<viewport>.png` (full page) and `…-<viewport>-top.png` (the top of the page, the size of the viewport).
- `host` (default the server's own address, 127.0.0.1) opens the flow on another name for the same server: passkeys need a host name such as `localhost`, not an IP address.
- `phone_agent` (true) makes the phone-width visit look like an iPhone to the page, for features that only show on a phone (the app's own `isMobile()` reads the user agent); tablet and desktop visits are unchanged.
- `allow_console` (a list of texts) names console errors a flow expects, such as the browser's own "net::ERR_INTERNET_DISCONNECTED" while it is offline on purpose.
- A flow also ends with a screenshot, and fails the run on a failed step, a console error or a 5xx response.

Flows run against the demo data only.
