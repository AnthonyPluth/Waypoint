# Scripted flows

Each `*.json` file here is a flow that `make verify` runs after visiting the pages, at phone and desktop widths (or the `viewports` it lists). A pull request adds steps by adding or editing a file.

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

## Fields

- `page` is the route the flow starts on (default `upcoming`).
- `viewports` defaults to phone and desktop. `laptop` (1024 px), `wide` (1440 px) and `zoomed` (853 px, a 1280 px window at 150% zoom) are there for a flow that lists them. The app is dark only, so every flow runs in the dark colour scheme.
- `host` (default the server’s own address, 127.0.0.1) opens the flow on another name for the same server. Passkeys need a host name such as `localhost`, not an IP address.
- `phone_agent` (true) makes the phone-width visit look like an iPhone to the page, for features that only show on a phone (the app’s own `isMobile()` reads the user agent). Desktop visits are unchanged.
- `signed_in` (true) runs the flow on a demo server where every request is the signed-in demo member Jane, so the photo routes answer (in the default local mode they answer 404). make verify starts that server, with its own copy of the data, only when a flow asks for it; `tools/control flow` needs a session started with `start --signed-in jane`. Flows that set it share one server and always run one after another on the same worker, in order. The flow's images go to `artifacts/verify/`, like any flow's.
- `mapkit` (`"none"`, `"error"` or `"blocked"`) says what Apple's MapKit does for the flow. Without it, MapKit is on: every demo server make verify starts has `WAYPOINT_MAPKIT_ENABLED` left at its default (on), a key made for the run (never one of yours) and `WAYPOINT_PUBLIC_URL` set to that server, so `/api/mapkit/token` signs a real token, and the run answers every request to `*.apple-mapkit.com` itself: the script is `frontend/verify/fake-mapkit.js`, a stand-in `mapkit` that draws a plain grid with the app's annotations and polylines on it (a real tile would change between runs), and every other Apple address is refused. The browser never reaches Apple. `"none"` runs the flow on a demo server with no key, as a household that never set one up, so no map and no replay show; it fails the flow if the page asks any Apple host for anything. make verify starts that server, with its own copy of the data, only when a flow asks for it, and it isn't the signed-in one, so `"none"` and `signed_in` don't go together. `"error"` serves the stand-in and then makes it raise an `Unauthorized` error about two seconds after the map is built, to show a map that fails after it showed; `"blocked"` refuses the script, as an unreachable Apple would. `tools/control flow` runs `"error"` and `"blocked"` flows on any session, and a `"none"` flow on a session started with `start --no-key`.
- The stand-in map also draws what the Stats map hands MapKit: filled polygons for the visited countries and states, the arcs as polylines, MapKit's **+** and **−** (`[data-zoom='in']`, `[data-zoom='out']`; zoom goes round the selected airport when one is selected, else the centre of the view) and one-finger pan once `isScrollEnabled`. A polygon or arc carries `data-kind` (`country`, `state` or `route`) and `data-label`, and a small transparent `[data-hit]` circle inside it takes the click, so a flow selects it with `[data-hit][data-kind='state'][data-label='New York']`; an airport's dot is `[data-dot='JFK']`.
- `allow_console` (a list of texts) names console errors a flow expects, such as the browser’s own “net::ERR_INTERNET_DISCONNECTED” while it is offline on purpose.

A flow ends with a screenshot, and fails the run on a failed step, a console error or a 5xx response.

## Steps

A step has one action and an optional `timeout` in milliseconds (default 10000). Selectors are [Playwright selectors](https://playwright.dev/docs/other-locators) (CSS, `text=…`, `role=…`).

**Moving around and interacting**

- `{"goto": "#route"}` opens a route of the app, `{"goto": "/api/…"}` a path of the same server (a JSON reply or an image shows as the browser shows it), or a full URL.
- `{"click": selector}`, `{"fill": {"selector": …, "text": …}}` and `{"press": {"selector": …, "key": "Enter"}}`.
- `{"hover": selector}` moves the pointer over it; the hover state shows in the next screenshot.
- `{"select": {"selector": "label:has-text('What is it') select", "index": 1}}` chooses an option of a `<select>` by its position.
- `{"click_if_present": selector}` clicks it when it shows up within a second (`timeout` changes that) and does nothing when it doesn’t, for a step that only one width needs (a menu that exists on a phone).
- `{"upload": {"selector": "input[type=file]", "file": "tests/fixtures/flight_import/flighty.csv"}}` chooses a file of the repository (made-up data) in a file input.
- `{"scroll_to": selector}` scrolls it to the top of the screen. An image is always the whole page, taken from the top, so this only matters to a later step.
- `{"scroll_under_bar": selector}` scrolls the page until the element’s centre sits behind the floating tab bar (phone width), so the audit at the end of the flow checks the bar’s labels over whatever bright content is there. It fails when the page can’t scroll far enough.
- `{"audit": true}` runs the accessibility audit (axe, tap targets, focus rings) on the page as it is now, without the scroll back to the top that a screenshot makes, and fails the flow with what it finds. The audit at the end of every flow runs after that scroll, so use this step for what only shows partway down the page.

**Checking and capturing**

- `{"wait_for": selector}` waits for it to appear.
- `{"expect_absent": selector}` fails unless nothing matches it within the timeout; it keeps looking while the page settles. Put it after a `wait_for` of something that shows once the page is ready, so it isn't checked before the page has drawn.
- `{"expect_text": {"selector": …, "text": …}}` fails unless it contains the text within the timeout; it keeps looking while the page settles.
- `{"screenshot": "name"}` saves the full page as `flow-<flow name>-<name>-<viewport>.png` to `artifacts/verify/`, at phone and desktop only. Other widths run the steps and checks and write no image.
- `{"download": {"selector": "button:has-text('Save as image')", "name": "saved-image"}}` clicks it, waits for the file the browser downloads and saves it as `flow-<flow name>-<name>-<viewport>.png` in the same place.

**Offline**

- `{"authenticator": "add"}` gives the page a virtual device check (a platform passkey with PRF, always verified), so a flow can set up offline access.
- `{"offline": true}` cuts the browser’s connection (`false` restores it).
- `{"reload": true}` reloads the page, through the service worker when offline.

**Faking data**

These change what the page’s later requests see; nothing is stored. Where a step says “put it before a `reload`”, the change applies to the loads after it.

- `{"clock": "2026-08-31T12:00:00Z"}` sets the browser’s clock to that moment (an ISO time with its offset), for a page that reads the time to place something, such as the ship on a cruise. The demo server keeps its own frozen clock. Put it before a `reload`.
- `{"long_names": ", a suffix"}` adds the suffix to the names in the Stats reply (`name`, `city` and `hotel`) for the page’s later loads, so a flow shows long names in every list. The demo data itself doesn’t change. Put it before a `reload`.
- `{"fake_labels": "Japan 2026, Taxes"}` answers the page’s requests for a mailbox’s Gmail labels with those made-up names (the demo mailbox can’t reach Google), and accepts a save.
- `{"fake_ignored": "news.example, deals.example"}` answers the page’s requests for a mailbox’s ignored senders with those made-up domains, and drops a domain from the list when it is stopped.
- `{"fake_ignore": "news.example"}` answers an ignore on Review as done for that domain, without changing the demo data.
- `{"fake_dismiss": true}` answers a dismissal on Review as done, without changing the demo data, and leaves the dismissed items out of the page's later loads of the queue.
- `{"fake_destination": "Colorado & Texas"}` makes the page’s later loads of the app’s state say the AI fallback is on, and answers a request for a trip’s suggested destination with that made-up text (the demo has no AI to ask). Put it before a `reload`.
- `{"fake_first_run": "connect"}` makes the page’s later loads show a household with no trips, in the given first-run state: `connect` (no mailbox), `scanning`, `review` (3 emails waiting) or `manual` (a connected mailbox, nothing waiting). Put it before a `reload`.
- `{"fake_merge_warning": "Sam Doe | Mia Doe"}` answers the page’s request to merge a trip with the warning a member gets when the two trips involve different people: the names before the bar will newly see this trip’s bookings, the names after it the other trip’s. It lets the confirmed request through to the demo data. The demo’s household view is never asked, so a flow needs this to show the dialog.
- `{"fake_immich": "Demo Person"}` answers the page’s Test of an Immich address and key (`POST /api/photo-sources/test` and `POST /api/photo-sources/{id}/test`) with a made-up Immich user of that name, and its Save of a new library (`POST /api/photo-sources`) with a made-up library on the address typed, which the page’s later loads of the library list show after the demo’s own (the demo server can’t reach an Immich server). `{"fake_immich": "refused"}` answers both as Immich turning the key down, and `"unreachable"` as a server Waypoint can’t reach. Everything else goes through to the demo data, which nothing changes. Use it in a `signed_in` flow, since the photo routes need sign-in.
- `{"fake_resume": 12}` makes the first library you manage show as Paused, answers the page's check of what resuming it would show (`GET /api/photo-sources/{id}/resume`) with a made-up count of 12 photos on the first two trips of the demo person's trips, and answers the first confirmed Resume as refused because the trips changed meanwhile (the count then reads 15, under a new snapshot), the next one with the library resumed. The demo data is never written, so the flow leaves it as it found it. Use it in a `signed_in` flow.
- `{"fake_archive": 400}` adds that many made-up past trips to the page’s later loads of the trip list (copies of a demo trip with other names, places, airlines and dates), to show a list the size of a long archive. Put it before a `reload`.
- `{"fake_bookings": "past"}` adds a train, a rental car, parking, a visit, a changed stay and a cancelled stay to the page's later loads of any trip that has a booking (copies of its first booking with made-up places, codes and prices, starting on the trip's first day), because the demo data has none of them. The demo data doesn't change. Put it before the `goto` of the trip.
- `{"fake_flight_status": "in-the-air"}` answers the page’s later loads of the flight status list with the demo’s one delayed flight made a flight in the air: departed 6 minutes late, expected on time, arrival gate A3, fetched a minute before the browser’s clock. Put a `clock` step (mid-flight, in the flight’s own time) and a `reload` after it, so the app starts under that clock.
- `{"fake_shell": "saved"}` makes the page's later loads think they run inside the iPhone app, with a stand-in for the app's offline bridge in the state named: `saved` (two trips, saved 12 minutes ago), `one`, `ten`, `none` (saving on, nothing saved), `off`, `saving` (a fetch running), `failed` (the last save failed, two trips kept), `failed-none`, `damaged` (an unreadable reply) or `old` (an installed app too old for the bridge, which has only the older sign-out handler). Switching saving off or on in the page works against the stand-in, which keeps its state until the next load. Put it before a `reload`; a later `fake_shell` replaces the earlier one on the next load.
- `{"fake_photo_limit": 2}` trims every trip’s photo list to its first 2 photos for the page’s later loads (the best photos and the photo count in the trip’s numbers follow), to show a trip with only one or two photos. The demo data doesn’t change. Use it in a `signed_in` flow, since the photo routes need sign-in, and put it before the `goto` of the trip.

## Writing a flow

Flows run against the demo data only, on one of several servers that `make verify` runs at once (`VERIFY_JOBS`), each with its own copy of the data. A flow sees its own earlier changes and those of the flows queued before it on the same server, never another server’s. So a flow:

- finds what it needs in the untouched demo data, and doesn’t rely on another flow having added or removed something;
- puts back what it changes if a later flow could trip on it;
- works alone (`poetry run python run.py verify --flow NAME`);
- looks for a trip by what the page shows today, not by a date you remember, because dates in the demo data are relative to the frozen clock.
