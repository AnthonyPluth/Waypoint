# Arrival codes on the iPhone: signed-off design

This is the design for [#819](https://github.com/AnthonyPluth/Waypoint/issues/819): when you arrive near the address of a booking on a saved trip, the iPhone app brings up that booking's code (a parking lot's gate QR code, a rental pickup's or a hotel's confirmation number) so you don't have to dig for it. **The owner signed off the frames and wording on 2026-11-18, with one change (no Settings switch or card), recorded in [this comment on #819](https://github.com/AnthonyPluth/Waypoint/issues/819#issuecomment-6981807369).** Nothing is left open. The build issues are listed under [Build](#build).

Owner context: no Live Activities and no Wallet passes (Wallet and the airline apps already do those), no clutter, and the phone's location never leaves the phone.

Each file is a self-contained HTML page (vector only, no raster images, dark only, phone width 390 px only). The pages use Waypoint's tokens from `frontend/src/app.css` and add none. The iOS lock screen, banner, permission alerts and iOS Settings are drawn only to place Waypoint's parts; their look is Apple's. Every place, name, code and time in them is made up, and the QR pattern is random.

| Screen | File | What it shows |
| --- | --- | --- |
| A | [a-arrival.html](a-arrival.html) | The notification on the lock screen (parking, rental pickup, hotel; worded by kind only), the same notification as a banner over another app, the card at the top of Upcoming when you open Waypoint near the place, and the owner's decisions |
| B | [b-opened-code.html](b-opened-code.html) | What opens: the existing QR code dialog for parking (online, or from the saved trips with no connection), the same dialog when no picture is saved yet, and the confirmation number for a rental pickup and a hotel |
| C, D | [c-permissions.html](c-permissions.html) | iOS's own asks in context (location While Using, the Always upgrade straight after, notifications) over the page that is open, and iOS Settings, Waypoint, the only place to stop it |

The draft issue bodies the build issues were made from are in [build-plan.md](build-plan.md).

## Owner decisions

Decided by the owner in chat on [PR #832](https://github.com/AnthonyPluth/Waypoint/pull/832), **2026-11-18**; the sign-off and the last two decisions are recorded in [a comment on #819](https://github.com/AnthonyPluth/Waypoint/issues/819#issuecomment-6981807369):

1. **Bookings: parking, rental pickup and hotel. Flights stay out.** A hotel has no check-in code, so its arrival opens the confirmation number (frame B3b).
2. **The iPhone app keeps the parking QR picture with its saved trips**, so it shows with no connection. The server's offline reply carries it for the parking bookings the person can see only. This changes a promise: [The parking QR picture on the phone](#the-parking-qr-picture-on-the-phone) says exactly which wording changes, how the picture is stored and which check holds it. It is the first build issue, ahead of the arrival feature.
3. **Finding places: Apple's geocoder on the phone.** The booking's address text goes to Apple once per save; the phone's location is never sent.
4. **Opening the app near the place: a card on Upcoming with one tap to the code** (A3), never opening the code by itself.
5. **No Settings switch and no card.** The feature has no toggle of its own and is always on once iOS permission is granted. iOS's own asks (location While Using, then the explicit Always request, then notifications) appear the first time a saved trip has a parking, rental pickup or hotel booking; granting them is the opt-in. Turning Location or Notifications off in iOS Settings, or signing out, stops it.
6. **Defaults as recommended**: the lock-screen wording names the kind only; 250 m around a parking lot, from 2 h before entry until exit; 300 m around a rental pickup (2 km around the airport when only its code is known), from 2 h before to 4 h after; hotels as recommended (200 m, on the check-in day).

The frames and their wording are signed off with these.

## What each booking holds today

Checked on `main` at the time of writing (`waypoint/storage/schema.py`, `waypoint/domain/trips.py`'s `DETAIL_KEYS`, `waypoint/domain/offline.py`, `waypoint/storage/geocode.py`, `frontend/src/lib/components/GateCode.svelte`).

| Kind | The code Waypoint holds | On the phone's saved copy today? | Where it is, and how precisely | Missing for this feature |
| --- | --- | --- | --- | --- |
| Parking | The gate's QR picture (`segment_codes`, sealed, served only by `GET /api/segments/{id}/code`), and the confirmation number | Confirmation: yes. **QR picture: no.** `offline.py` blanks `gate_code`, emails are saved without images, and the promise says the picture is "absent from the offline copy" (decision 2 changes this) | The lot's address in `details.address` when the email gave one (SpotHero's parser, a calendar invite's location, schema.org markup). Server coordinates are only postcode or city precision | A street-level coordinate (decision 3). The picture in the saved copy (decision 2) |
| Rental car | The confirmation number; `car_class` | Yes | The pickup address in `details.address` from schema.org markup, or only the pickup airport's code in `origin`. Server coordinates: postcode, city or airport | A street-level coordinate. No pickup code, locker code or QR is parsed or stored |
| Hotel | The confirmation number; `room` when known; `phone` | Yes | `details.address` from markup or the lodging reader. Server coordinates: postcode or city | A street-level coordinate. No check-in code, check-in QR or mobile key is parsed or stored (a mobile key lives in the hotel's own app or Wallet) |
| Flight (out) | The confirmation number (record locator); `terminal`, `seat`, `flight_number` | Yes | The airports' codes. The airports' coordinates are bundled reference data on the server (`airports` table), not in the saved copy | No boarding pass is stored, and it stays out of scope |

Two facts shape the design:

- **The server's coordinates are too coarse.** `segments.latitude`/`longitude` come from the bundled geocoder (`geocode.locate`), whose best precision is a postcode centroid, often a kilometre or more from the lot; they are also not in the `Segment` reply or the saved copy. A street-level point is looked up on the phone (decision 3).
- **The saved copy is unreadable while the phone is locked.** `OfflineStore` writes with `.complete` file protection, so when iOS wakes the app for a region while the phone is locked, it can't read the trips. What the wake-up needs is kept in a small separate file (see Privacy below).

## The parking QR picture on the phone

Owner decision 2 lets the iPhone app keep the gate's QR picture with the saved trips. This is how, and what it changes.

**What the server sends, and how the phone finds a ready code.** The picture travels inside the offline reply itself; the shell never fetches `GET /api/segments/{id}/code` and never has to guess which bookings have a code. For a request made with the iPhone app's token (scope `app`), `GET /api/offline` changes in two ways:

- `offline.py` stops blanking `gate_code` for that request: each parking segment keeps `gate_code` exactly as the trip reply has it (`{state, day}`, no picture; `null` when the booking has no code), so the saved copy says which bookings have a ready code, the same metadata the online dialog reads.
- Each saved trip gains a `codes` list beside `messages`: `{segment_id, type, data}` (the picture's type and base64 bytes, exactly as `GET /api/segments/{id}/code` would serve them), one entry for each of the parking bookings the person can see on that trip whose `gate_code.state` is `ready` and that isn't cancelled.

So in the saved copy a ready code is a segment whose `gate_code.state` is `ready` with an entry for its id in its trip's `codes`; the dialog (offline, in the shell) shows that entry's picture, and a `ready` segment with no entry (the code was chosen after the last save) is frame B2. "Can see" means a parking booking, including a co-traveller's on a shared trip, that the requester can see on a trip saved for them, through the same visibility helper as every trip route; another member's booking they can't see is never in it. Both fields are optional for readers, so `version` stays 1. A browser session's reply is unchanged: `gate_code` still `null` and no `codes` (browsers don't read this reply today).

**How the phone keeps it.** The iPhone app saves the reply as it does today, so the picture lands in the same files under `.complete` iOS Data Protection in the app's private storage, with no encryption of Waypoint's own, and goes into iCloud and computer backups like the rest of the copy. It is deleted with the saved trips, at every moment they are (sign-out, 401 or 403, saving off, a changed server address, no server, 3 days after the trip ends) and replaced at each save, so a picture changed or removed on the server is gone from the phone at the next online open. The bridge's `load` passes it to the web app unchanged, and the QR code dialog shows it with no connection. The browser vault, the calendar feed, reminders, `/mcp` and logs never carry it, and `/mcp` still never says a booking has one.

**Wording that changes** (in the same pull request as the code, the first build issue):

| Where | Today | Becomes |
| --- | --- | --- |
| `AGENTS.md`, "Email stays on the server" | "…served only by `GET /api/segments/{id}/code` to those who can see the booking (404 for anyone else, blocked for assistants, absent from the offline copy, the calendar feed, reminders and what `/mcp` returns, which also never says a booking has one)…" | "…served by `GET /api/segments/{id}/code` to those who can see the booking (404 for anyone else, blocked for assistants) and, for the parking bookings the person can see on the trips saved for them, in the iPhone app's copy of `GET /api/offline` (owner decision, #819, 2026-11-18), and absent from the browser's offline copy, the calendar feed, reminders and what `/mcp` returns, which also never says a booking has one…" |
| `AGENTS.md`, same promise, the device copy | "…the stored messages of the bookings on the trips saved there (…; without their images) are part of the copy the app saves there…" | adds: "and, in the iPhone app, the gate code's picture of the parking bookings the person can see on those trips" |
| `SECURITY.md`, "A signed-in person's own device" | "…bookings, confirmation codes, times, places, travellers' display names and each booking's stored confirmation message without its images…" | adds: "…and, in the iPhone app, the gate code's picture of the parking bookings they can see…" |
| `docs/src/content/docs/start/offline.md`, "What is saved" | "Never saved: loyalty and Known Traveler numbers, the QR code of a parking booking, …" | the QR code moves to the saved list for the iPhone app ("in the iPhone app, the QR code of the parking bookings you can see on those trips"); "Never saved" keeps it for browsers |
| `docs/src/content/docs/start/trips.md`, "The gate code of a parking booking" | "The picture is fetched from your server each time and is never saved in the browser, so it needs a connection; it is not in the offline copy." | "In a browser the picture is fetched from your server each time and is never saved, so it needs a connection. The iPhone app keeps it with your saved trips, so it shows with no connection there." |
| `docs/src/content/docs/start/ios.md`, "Saved trips" | lists what the saved copy holds by reference to Offline | says the copy includes the QR code of the parking bookings you can see on those trips |
| `ios/README.md`, "Offline bridge" | the `load` reply's trips are the `GET /api/offline` elements | notes the optional `codes` list, passed through unchanged |

There is no separate invariants list in the repository; these are all the places the promise is written.

**Which check holds it.** `tests/test_gate_codes.py`'s `NeverElsewhereTests.test_the_offline_copy_the_calendar_and_an_assistant_never_carry_the_code_or_say_there_is_one` asserts today that the offline copy never carries the picture; it is rewritten (not removed) to: the app's offline reply carries exactly the requester's visible ready, not cancelled parking pictures, byte for byte; a member who can't see the booking, a cancelled booking and a booking with no picture chosen get none; a browser session's reply has none; the calendar feed and `/mcp` still carry neither the picture nor its existence; and the request runs inside `tests/privacy.py`'s `no_leaks` with the picture's bytes as a canary, so nothing logs it. `tests/test_offline.py` gains the reply's shape. Decryption stays in the storage layer (`storage/gate_codes.py`), under the existing Semgrep rule.

## The six points of #819

### 1. Which bookings and which codes

- **Parking**: the gate's QR picture, from the saved trips when there is no connection.
- **Rental pickup**: the confirmation number, which is what the counter asks for. Only the pickup (`start_local`), not the return.
- **Hotel**: the confirmation number, with the room if known (B3b). Waypoint stores no check-in code.
- **Flight**: out. Waypoint has no boarding pass, and Wallet already brings one up at the airport.
- Trains, cruises and visits are not part of this. Nothing new is parsed: hotel check-in codes, rental pickup codes and boarding passes would each be new parsing and new storage, and are not built.

### 2. What happens on arrival

- **Notification** (needs Always location and notifications): one local notification when you enter a booking's circle during its window. Passive interruption level: no sound, no badge, no vibration. The wording names only the kind ("Your parking code is ready", "Your rental pickup is near", "You're near your hotel"), never the place, a name or a code (A1). Tapping it unlocks the phone and opens the code (B). It is removed from Notification Centre when the booking's window ends.
- **Card on Upcoming** (While Using is enough): opening or returning to the app inside the circle during the window puts one card at the top of Upcoming, "You're at Harbour Parking, Lot B", with one button that opens the code and a dismiss (A3). One card at a time. It never opens the code by itself.
- What opens is the existing **Show QR code** dialog for parking, unchanged, and for a rental pickup or hotel a new dialog with the confirmation number large and copyable (B3). Closing either leaves you on that booking's trip page. With no connection and no picture saved yet for that booking, the dialog keeps its failure line and adds the confirmation number (B2).

### 3. Location permission, and where it is asked

There is no Waypoint prompt, switch or card: iOS's own asks are the opt-in (C).

- **When**: the first time a save of the trips (`OfflineSync`, which runs when the app opens online, becomes active, or saving is switched on) leaves in the saved copy a parking, rental pickup or hotel booking whose window hasn't ended, while the app is in the foreground. If the app is in the background at that moment, the asks wait until it is next active. Nothing is asked, and nothing is watched, while **Save my upcoming trips** is off or nothing qualifies.
- **What, in order, each once**: (C1a) location, `requestWhenInUseAuthorization()`; if the person allows While Using, (C1b) straight away `requestAlwaysAuthorization()`, which iOS shows at once as **Keep Only While Using** / **Change to Always Allow**; then (C1c) notifications, alerts only, no sound or badge. iOS does not offer the Always upgrade by itself: Apple's documentation for `requestAlwaysAuthorization()` says an app gets Always by first requesting When In Use and then requesting Always, that the second call prompts immediately, and that further calls have no effect; Allow Once gives no Always. A per-phone flag records that the asks were made, so the app never asks again; after a refusal the only way on is iOS Settings.
- **What each answer gives**: Always and notifications: the notification and the card. While Using only: the card. Notifications refused: the card, and with Always no notification. Location refused or Allow Once: nothing (Allow Once lasts one session). Precise Location off: nothing, since region monitoring can't work with approximate location and the one-shot check can't tell a lot from its streets.
- **The explanation lives where the asks happen**: the two usage-description strings iOS shows in the location alerts, and the docs (`docs/src/content/docs/start/ios.md` gains an "Arrival codes" section; `offline.md` links to it). The notification alert's text is Apple's and can't be changed, so the docs carry that part.
  - `NSLocationWhenInUseUsageDescription`: "Waypoint uses your location on this device to bring up a booking’s code when you arrive at its parking lot, rental pickup or hotel. Your location is never sent to your Waypoint server or anyone else and is not recorded. Booking addresses are looked up with Apple Maps."
  - `NSLocationAlwaysAndWhenInUseUsageDescription`: "Waypoint uses your location on this device to tell you when you arrive at a parking lot, rental pickup or hotel on a saved trip, even when Waypoint is closed. Your location is never sent anywhere and is not recorded."
- **Which bookings get a region**: iOS allows 20 per app. The app watches at most 15 (5 to spare): every qualifying booking on the saved trips whose window hasn't ended, soonest window first. The saved trips are at most 10, so 15 covers nearly every household. The set is rebuilt after each save, each time the app becomes active, on each region event and on each permission change.

### 4. Privacy (binding)

- **The phone's location never leaves the phone.** No location, region event, arrival or "near a booking" fact is sent to the server, to Apple, or to anyone; no new server route is added. The web view is told only which booking to open (its id), never a coordinate.
- **Nothing is recorded.** The app keeps no location history: it uses iOS region monitoring (enter events) and, for the card, one current-location check when the app becomes active, compared in memory and dropped. Nothing about locations or arrivals is logged, in the app or on the server.
- **Works from the saved trips, with no connection.** The bookings and the parking pictures come from `OfflineStore`, never from a live request. Watching, the notification, the card and the code work in airplane mode.
- **Finding the places**: the phone looks each booking's address up with `CLGeocoder` once per save, only once location has been allowed, and keeps the coordinate beside the saved trips. Waypoint's server is not involved, but the booking's address text (never the phone's location) goes to Apple, and needs the connection the save already has. For a rental pickup with only an airport code, the airport's bundled coordinate is used (the server adds it to the saved copy; it is public reference data).
- **What the phone keeps for a locked wake-up.** A small arrival file beside the saved trips, readable after the first unlock since restart (`.completeUntilFirstUserAuthentication`), holding for each watched booking only its id, its trip's id, its kind, its window as two instants, the circle's centre and radius. No name, address, code or confirmation number. The looked-up coordinates live in the saved trips' own folder under `.complete`.
- **The test that proves no location reaches the server** (#819's acceptance criterion): an iOS unit test drives region events, the in-app check and the geocoding with a recording URL protocol and asserts that no request is made to the Waypoint server during them and that no request anywhere carries the test coordinates; a Python test fails if the arrival Swift files reference `URLSession`, `ServerClient` or `ServerAPI`, if `CLGeocoder` appears outside the one geocoding file, or if any `os_log`/`Logger`/`print` call appears in them.

### 5. Window and radius

Times are the booking's own wall-clock times in its zone, turned into instants on the phone.

| Kind | Circle | Window | How often | Stops |
| --- | --- | --- | --- | --- |
| Parking | 250 m around the lot's address | From 2 h before entry until the exit time | Once per arrival, at most once every 4 h (so the drop-off and the return for an exit gate each get one) | After the exit time, when cancelled, removed or its trip is no longer saved |
| Rental pickup | 300 m around the pickup address; 2 km around the airport when only an airport code is known | From 2 h before pickup until 4 h after | Once | After the first notification or card, or the window's end |
| Hotel | 200 m around the address | Check-in day, from 3 h before check-in until midnight there | Once | After the first notification or card, or the window's end |

iOS region monitoring is not precise below roughly 100 to 200 m and can fire minutes after you cross the line; the radii allow for that. A booking with no usable address (no `details.address` and no airport code) is not watched.

### 6. No switch: how it is on, and how to stop it

**There is no in-app off switch** (owner decision 5): no card in Settings, no toggle, no Waypoint prompt. The feature is on once iOS permission is granted (C), and these stop it (D):

| What the person does | What stops | What is deleted |
| --- | --- | --- |
| iOS Settings → Waypoint → Location → Never (or Ask Next Time) | Every region is stopped and pending and delivered arrival notifications are removed, at the next permission change the app sees (iOS tells the app when it next runs) | The arrival file and the looked-up coordinates. No saved trip and no saved picture |
| Location → While Using (from Always) | Regions and the notification; the card stays | Nothing |
| Precise Location off | Regions, the notification and the card | Nothing (turning it on again resumes) |
| Notifications off | The notification; the card stays | Nothing |
| Sign out, a 401 or 403, a changed server address, no server | Everything | The arrival file and coordinates, with the saved trips and pictures, as part of the purge they already do |
| Save my upcoming trips off | Everything (nothing is left to watch) | The saved copy, as today, and with it the arrival file and coordinates |

Turning location back on in iOS Settings resumes watching at the next save or activation, with no new ask. The docs' "Arrival codes" section says all of this in plain words, including that there is no switch in Waypoint and that iOS Settings is where to stop it.

## Build

The issues, in the order they land (Sonnet each; created on 2026-11-18 from [build-plan.md](build-plan.md)):

| Order | Issue | What | Depends on |
| --- | --- | --- | --- |
| 1 | [#846](https://github.com/AnthonyPluth/Waypoint/issues/846) | The iPhone app keeps the parking QR picture with the saved trips (the promise change) | This design merged |
| 2 | [#847](https://github.com/AnthonyPluth/Waypoint/issues/847) | Airport coordinates in the saved trips | #846 |
| 3 | [#848](https://github.com/AnthonyPluth/Waypoint/issues/848) | Find each watched booking's place on the phone | #846, #847 |
| 4 | [#849](https://github.com/AnthonyPluth/Waypoint/issues/849) | Ask for location in context, watch the places and post the notification (holds the no-location-to-the-server test) | #848 |
| 5 | [#850](https://github.com/AnthonyPluth/Waypoint/issues/850) | Open a booking's code from the notification or the Upcoming card | #849, #846 |

The same list is posted on [#819](https://github.com/AnthonyPluth/Waypoint/issues/819#issuecomment-6981941089).

## Accepted departures

**2026-11-18, build of #849 (owner decision, [issue #849 comment](https://github.com/AnthonyPluth/Waypoint/issues/849#issuecomment-6991020882)).** The arrival file also holds, for each watched booking, when its alert last fired (`notifiedAt`), so the "how often" rules of point 5 can be decided from the file alone on a wake-up. This is the one instant kept besides the window. The owner's words: "The `notifiedAt` ... \"once\" rule for hotel and rental pickups and the \"every 4 hours\" rule for parking can't be decided from the file without it"; the file holds "when each alert last fired, not where the person was or when they arrived". It is dropped when the window ends, deleted by every purge, and stays in iPhone backups like the saved trips (owner decision, [comment on #868](https://github.com/AnthonyPluth/Waypoint/pull/868#issuecomment-6991412916), 2026-11-18).

**The signed-off usage strings stay exactly as signed off** (same #868 comment: "No location is recorded; the arrival file holds only when each alert last fired"). "Your location ... is not recorded" remains accurate because the alert time is a time and a booking, not a location, and the owner chose to leave the strings as they are. The notification ask comes only after Always is granted; a notification is removed at the next rebuild after its window ends, not by a timer; a person already inside a circle when its window opens gets no notification until they leave and re-enter; the per-phone ask flags are not cleared on sign-out; a rental pickup or hotel that has notified no longer holds one of the 15 regions, and its delivered notification stays until its window ends. Point 4's "Nothing is recorded" is read with this exception.

## Not confirmed

None of this has run on a device. Region monitoring's wake-up with Always, its behaviour with Precise Location off, how late it fires, and whether a wake-up while locked can read the arrival file are from Apple's documentation. The build issues say what each can check in CI and what needs a phone.
