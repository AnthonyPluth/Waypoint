# Arrival codes on the iPhone: design in progress

This is the design for [#819](https://github.com/AnthonyPluth/Waypoint/issues/819): when you arrive near the address of a booking on a saved trip, the iPhone app brings up that booking's code (a parking lot's gate QR code, a rental pickup's or a hotel's confirmation number) so you don't have to dig for it. **The owner decided four points on 2026-11-18 (below). The look of the frames is not signed off, four points are still open, and nothing is built until the design is signed off.**

Owner context from the issue and from 2026-11-18: no Live Activities and no Wallet passes (Wallet and the airline apps already do those), no clutter, and the phone's location never leaves the phone.

Each file is a self-contained HTML page (vector only, no raster images, dark only, phone width 390 px only). The pages use Waypoint's tokens from `frontend/src/app.css` and add none. The iOS lock screen, banner and permission alerts are drawn only to place Waypoint's parts; their look is Apple's. Every place, name, code and time in them is made up, and the QR pattern is random.

| Screen | File | What it shows |
| --- | --- | --- |
| A | [a-arrival.html](a-arrival.html) | The closed notification on the lock screen (parking, rental pickup, hotel; the default wording and the place-name alternative), the same notification as a banner over another app, the card at the top of Upcoming when you open Waypoint near the place, the owner's decisions and what is still open |
| B | [b-opened-code.html](b-opened-code.html) | What opens: the existing QR code dialog for parking (online, or from the saved trips with no connection), the same dialog when no picture is saved yet, and the confirmation number for a rental pickup and a hotel |
| C | [c-settings.html](c-settings.html) | The Arrival codes card in Settings, Offline & notifications: in place, off by default, the location and notification permission steps, on (Always, While Using, nothing to watch), and each missing piece (location refused, Precise Location off, notifications refused, saving trips off) |

The draft build plan, as agent-task issue bodies, is in [build-plan.md](build-plan.md).

## Owner decisions

Decided by the owner in chat on [PR #832](https://github.com/AnthonyPluth/Waypoint/pull/832), **2026-11-18**:

1. **Bookings: parking, rental pickup and hotel. Flights stay out.** A hotel has no check-in code, so its arrival opens the confirmation number (frame B3b).
2. **Yes, the iPhone app may keep the parking QR picture with its saved trips**, so it shows with no connection. The server's offline reply carries it for the person's own parking bookings only. This changes a promise: [The parking QR picture on the phone](#the-parking-qr-picture-on-the-phone) says exactly which wording changes, how the picture is stored and which check holds it, and it is its own build issue, ahead of the arrival feature.
3. **Finding places: Apple's geocoder on the phone.** The booking's address text goes to Apple once per save; the phone's location is never sent. The Settings card says so.
4. **Opening the app near the place: a card on Upcoming with one tap to the code**, never opening the code by itself.

Still open (the frames and the plan use the recommended default for each): the lock-screen wording, the windows and radii, the card's names, and what turning it off deletes. See [Still open](#still-open).

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
- **The saved copy is unreadable while the phone is locked.** `OfflineStore` writes with `.complete` file protection, so when iOS wakes the app for a region while the phone is locked, it can't read the trips. What the wake-up needs is kept in a small separate file (point 4 below).

## The parking QR picture on the phone

Decision 2 lets the iPhone app keep the gate's QR picture with the saved trips. This is how, and what it changes.

**What the server sends.** `GET /api/offline` gains, for each saved trip, a `codes` list beside `messages`: `{segment_id, type, data}` (the picture's type and base64 bytes, exactly as `GET /api/segments/{id}/code` would serve them) for each of the person's own parking bookings on that trip that has a picture chosen (`gate_code.state` is `ready`) and isn't cancelled. "The person's own" means a parking booking the requester can see on a trip saved for them, through the same visibility helper as every trip route; another household member's booking they can't see is never in it. `gate_code` on each segment stays as the trip reply has it (state and day only; today `offline.py` blanks it to `null`). The field is optional for readers, so `version` stays 1. Proposed, to confirm: only a request made with the iPhone app's token (scope `app`) gets `codes`; a browser session's reply is unchanged, as browsers don't read this reply today.

**How the phone keeps it.** The iPhone app saves the reply as it does today, so the picture lands in the same files under `.complete` iOS Data Protection in the app's private storage, with no encryption of Waypoint's own, and goes into iCloud and computer backups like the rest of the copy. It is deleted with the saved trips, at every moment they are (sign-out, 401 or 403, saving off, a changed server address, no server, 3 days after the trip ends) and replaced at each save, so a picture changed or removed on the server is gone from the phone at the next online open. The bridge's `load` passes it to the web app unchanged, and the QR code dialog shows it with no connection. The browser vault, the calendar feed, reminders, `/mcp` and logs never carry it, and `/mcp` still never says a booking has one.

**Wording that changes** (in the same pull request as the code, `{{ARRIVAL-QR}}` in the plan):

| Where | Today | Becomes |
| --- | --- | --- |
| `AGENTS.md`, "Email stays on the server" | "…served only by `GET /api/segments/{id}/code` to those who can see the booking (404 for anyone else, blocked for assistants, absent from the offline copy, the calendar feed, reminders and what `/mcp` returns, which also never says a booking has one)…" | "…served by `GET /api/segments/{id}/code` to those who can see the booking (404 for anyone else, blocked for assistants) and, for the person's own parking bookings on the trips saved for them, in the iPhone app's copy of `GET /api/offline` (owner decision, #819, 2026-11-18), and absent from the browser's offline copy, the calendar feed, reminders and what `/mcp` returns, which also never says a booking has one…" |
| `AGENTS.md`, same promise, the device copy | "…the stored messages of the bookings on the trips saved there (…; without their images) are part of the copy the app saves there…" | adds: "and, in the iPhone app, the gate code's picture of the person's own parking bookings on those trips" |
| `SECURITY.md`, "A signed-in person's own device" | "…bookings, confirmation codes, times, places, travellers' display names and each booking's stored confirmation message without its images…" | adds: "…and, in the iPhone app, the gate code's picture of their own parking bookings…" |
| `docs/src/content/docs/start/offline.md`, "What is saved" | "Never saved: loyalty and Known Traveler numbers, the QR code of a parking booking, …" | the QR code moves to the saved list for the iPhone app ("in the iPhone app, the QR code of your own parking bookings"); "Never saved" keeps it for browsers |
| `docs/src/content/docs/start/trips.md`, "The gate code of a parking booking" | "The picture is fetched from your server each time and is never saved in the browser, so it needs a connection; it is not in the offline copy." | "In a browser the picture is fetched from your server each time and is never saved, so it needs a connection. The iPhone app keeps it with your saved trips, so it shows with no connection there." |
| `docs/src/content/docs/start/ios.md`, "Saved trips" | lists what the saved copy holds by reference to Offline | says the copy includes the QR code of your own parking bookings |
| `ios/README.md`, "Offline bridge" | the `load` reply's trips are the `GET /api/offline` elements | notes the optional `codes` list, passed through unchanged |

There is no separate invariants list in the repository; these are all the places the promise is written.

**Which check holds it.** `tests/test_gate_codes.py`'s `NeverElsewhereTests.test_the_offline_copy_the_calendar_and_an_assistant_never_carry_the_code_or_say_there_is_one` asserts today that the offline copy never carries the picture; it is rewritten (not removed) to: the app's offline reply carries exactly the requester's own ready, not cancelled parking pictures, byte for byte; a member who can't see the booking, a cancelled booking and a booking with no picture chosen get none; a browser session's reply has none; the calendar feed and `/mcp` still carry neither the picture nor its existence; and the request runs inside `tests/privacy.py`'s `no_leaks` with the picture's bytes as a canary, so nothing logs it. `tests/test_offline.py` gains the reply's shape. Decryption stays in the storage layer (`storage/gate_codes.py`), under the existing Semgrep rule.

## The six points

### 1. Which bookings and which codes (decided)

- **Parking**: the gate's QR picture, from the saved trips when there is no connection.
- **Rental pickup**: the confirmation number, which is what the counter asks for. Only the pickup (`start_local`), not the return.
- **Hotel**: the confirmation number, with the room if known (B3b). Waypoint stores no check-in code.
- **Flight**: out. Waypoint has no boarding pass, and Wallet already brings one up at the airport.
- Trains, cruises and visits are not part of this. Nothing new is parsed: hotel check-in codes, rental pickup codes and boarding passes would each be new parsing and new storage, and are not in the plan.

### 2. What happens on arrival (the in-app part decided)

- **Notification** (needs Always location and notifications): one local notification when you enter a booking's circle during its window. Passive interruption level: no sound, no badge, no vibration. Default wording names only the kind ("Your parking code is ready"), never the place, a name or a code (A1a; A1c shows the place-name alternative, still open). Tapping it unlocks the phone and opens the code (B). It is removed from Notification Centre when the booking's window ends.
- **Card on Upcoming** (decided; While Using is enough): opening or returning to the app inside the circle during the window puts one card at the top of Upcoming, "You're at Harbour Parking, Lot B", with one button that opens the code and a dismiss (A3). One card at a time. It never opens the code by itself.
- What opens is the existing **Show QR code** dialog for parking, unchanged, and for a rental pickup or hotel a new dialog with the confirmation number large and copyable (B3). Closing either leaves you on that booking's trip page. With no connection and no picture saved yet for that booking, the dialog keeps its failure line and adds the confirmation number (B2).

### 3. Location permission

**Recommended: one switch, asking for While Using first; Always is what makes the notification work.**

- Switching on asks iOS for location (While Using) and then for notifications (alerts only, no sound or badge). While Using gives the card (A3). iOS later offers, by itself, to change to Always; with Always, region monitoring wakes the app and the notification works. The card says which of the two you have (C2a, C2b) and points to iOS Settings for the rest. The app never asks twice.
- Region monitoring can't work with approximate location, so with Precise Location off the card says it isn't working (C3b). This and the wake-up behaviour come from Apple's documentation and are not confirmed on a device.
- **Which bookings get a region**: iOS allows 20 per app. The app watches at most 15 (5 to spare): every qualifying booking on the saved trips whose window hasn't ended, soonest window first. The saved trips are at most 10, so 15 covers nearly every household; past 15, the soonest 15. The set is rebuilt after each save of the trips, each time the app becomes active, on each region event and when the switch changes.

### 4. Privacy (binding)

- **The phone's location never leaves the phone.** No location, region event, arrival or "near a booking" fact is sent to the server, to Apple, or to anyone; no new server route is added. The web view is told only which booking to open (its id), never a coordinate.
- **Nothing is recorded.** The app keeps no location history: it uses iOS region monitoring (enter events) and, for the card, one current-location check when the app becomes active, compared in memory and dropped. Nothing about locations or arrivals is logged, in the app or on the server.
- **Works from the saved trips, with no connection.** The bookings, and the parking pictures (decision 2), come from `OfflineStore`, never from a live request. Watching, the notification, the card and the code work in airplane mode.
- **Finding the places (decided: Apple's geocoder).** The phone looks each booking's address up with `CLGeocoder` once per save of the trips and keeps the coordinate beside the saved trips. Waypoint's server is not involved, but the booking's address text (never the phone's location) goes to Apple, and it needs a connection at that moment, which a save has anyway. For a rental pickup with only an airport code, the airport's bundled coordinate is used (the server adds it to the saved copy; it is public reference data).
- **What the phone keeps for a locked wake-up.** A small arrival file beside the saved trips, readable after the first unlock since restart (`.completeUntilFirstUserAuthentication`), holding for each watched booking only its id, its trip's id, its kind, its window as two instants, the circle's centre and radius. No name, address, code or confirmation number. The looked-up coordinates live in the saved trips' own folder under `.complete`.
- **Turning it off** (default; still open) stops every region, removes pending and delivered arrival notifications and deletes the arrival file and the looked-up coordinates. It deletes no saved trip and no saved picture. **Signing out**, a 401 or 403, switching saving off, a changed server address and launching with no server do the same, as part of the purge they already do. Switching saving off also turns the card to C3d: arrival codes need the saved trips.
- **The card says what it does** in plain words (C), saying "this device" as the Offline access card does. The privacy lines, as decided: "Your location stays on this device. It is never sent to your Waypoint server or anyone else, and it is not recorded." and "To find each place, this device sends the booking's address (never your location) to Apple Maps once, each time your trips are saved." (The Offline access card has no privacy sentence by the owner's decision of 2026-11-17; #819 asks for these here.)
- **The test that proves no location reaches the server** (#819's acceptance criterion): an iOS unit test drives region events, the in-app check and the geocoding with a recording URL protocol and asserts that no request is made to the Waypoint server during them and that no request anywhere carries the test coordinates; a Python test fails if the arrival Swift files reference `URLSession`, `ServerClient` or `ServerAPI`, if `CLGeocoder` appears outside the one geocoding file, or if any `os_log`/`Logger`/`print` call appears in them.

### 5. Window and radius (defaults; still open)

Times are the booking's own wall-clock times in its zone, turned into instants on the phone.

| Kind | Circle | Window | How often | Stops |
| --- | --- | --- | --- | --- |
| Parking | 250 m around the lot's address | From 2 h before entry until the exit time | Once per arrival, at most once every 4 h (so the drop-off and the return for an exit gate each get one) | After the exit time, when cancelled, removed, its trip is no longer saved, or the switch is off |
| Rental pickup | 300 m around the pickup address; 2 km around the airport when only an airport code is known | From 2 h before pickup until 4 h after | Once | After the first notification or card, or the window's end |
| Hotel | 200 m around the address | Check-in day, from 3 h before check-in until midnight there | Once | After the first notification or card, or the window's end |

iOS region monitoring is not precise below roughly 100 to 200 m and can fire minutes after you cross the line; these radii allow for that and are to be tuned on a device. A booking with no usable address (no `details.address` and no airport code) is not watched.

### 6. Where the switch lives, and its default

**Settings → Offline & notifications → Arrival codes**, a card of its own directly below Offline access (C0), only inside the iPhone app; in a browser there is no card. The switch is **Bring up codes when I arrive** (names still open). It is **off** until the person switches it on and allows location. It is per phone (a `UserDefaults` flag, missing means off), and signing out turns it off again (unlike saving trips, which signing in turns on). It needs **Save my upcoming trips**: while saving is off, the switch is disabled and says so (C3d).

## Still open

The frames and the plan use the default in brackets.

1. **Lock-screen wording**: kind only, "Your parking code is ready" (the default, A1a), or the place's name (A1c), which also puts the name in the file readable while locked?
2. **Windows and radii**: the table above, including the second notification for a parking exit?
3. **The card's names**: "Arrival codes" and "Bring up codes when I arrive", below Offline access, off after sign-out?
4. **Turning it off** deletes the derived arrival file and coordinates but no trip and no saved picture: is that what #819 means by "deletes nothing"?

Two details of decision 2 to confirm: "the person's own parking bookings" read as the parking bookings they can see on the trips saved for them; and the picture going only to the iPhone app's token, not to a browser session's reply.

## Not confirmed

None of this has run on a device. Region monitoring's wake-up with Always, its behaviour with Precise Location off, how late it fires, and whether a wake-up while locked can read the arrival file are from Apple's documentation. The build plan says what each issue can check in CI and what needs a phone.
