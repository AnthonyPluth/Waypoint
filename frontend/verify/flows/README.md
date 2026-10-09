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

- `page` is the route the flow starts on (default `upcoming`); `viewports` defaults to all three. The app is dark only, so every flow runs in the dark colour scheme.
- A step has one action, and an optional `timeout` in milliseconds (default 10000). Selectors are [Playwright selectors](https://playwright.dev/docs/other-locators) (CSS, `text=…`, `role=…`).
  - `{"goto": "#route"}` opens a route of the app (or a full URL).
  - `{"select": {"selector": "label:has-text('When') select", "index": 2}}` chooses an option of a `<select>` by its position.
  - `{"click": selector}`, `{"fill": {"selector": …, "text": …}}`, `{"press": {"selector": …, "key": "Enter"}}`.
  - `{"upload": {"selector": "input[type=file]", "file": "tests/fixtures/flight_import/flighty.csv"}}` chooses a file of the repository (made-up data) in a file input; `{"scroll_to": selector}` scrolls it to the top of the screen, so the `-top` screenshot shows it.
  - `{"download": {"selector": "button:has-text('Save as image')", "name": "saved-image"}}` clicks it, waits for the file the browser downloads and saves it as `flow-<flow name>-<name>-<viewport>.png` (and `...-top.png`), so a PR can show what was saved.
  - `{"authenticator": "add"}` gives the page a virtual device check (a platform passkey with PRF, always verified), so a flow can set up offline access; `{"offline": true}` cuts the browser's connection (`false` restores it) and `{"reload": true}` reloads the page, through the service worker when offline.
  - `{"wait_for": selector}` waits for it to appear; `{"expect_text": {"selector": …, "text": …}}` fails unless it contains the text within the timeout (it keeps looking while the page settles).
  - `{"screenshot": "name"}` saves `flow-<flow name>-<name>-<viewport>.png` (full page) and `…-<viewport>-top.png` (the top of the page, the size of the viewport).
- `host` (default the server's own address, 127.0.0.1) opens the flow on another name for the same server: passkeys need a host name such as `localhost`, not an IP address.
- `allow_console` (a list of texts) names console errors a flow expects, such as the browser's own "net::ERR_INTERNET_DISCONNECTED" while it is offline on purpose.
- A flow also ends with a screenshot, and fails the run on a failed step, a console error or a 5xx response.

Flows run against the demo data only.
