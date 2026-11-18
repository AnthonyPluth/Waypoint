# Arrival codes: build plan

Draft agent-task issue bodies for building [the arrival codes design](README.md) ([#819](https://github.com/AnthonyPluth/Waypoint/issues/819)), in the sections the `fleet-agent-task` skill names. The design is signed off ([comment on #819](https://github.com/AnthonyPluth/Waypoint/issues/819#issuecomment-6981807369), 2026-11-18): parking, rental pickup and hotel; the parking QR picture kept by the iPhone app; Apple's geocoder on the phone; a card on Upcoming, never auto-open; no Settings switch or card, iOS's own asks being the opt-in; the lock-screen wording by kind only and the windows and radii as recommended. The issues were created from these bodies; the README's "Build" section lists their numbers. Here they refer to each other by key in `{{…}}`; the created issues use the real numbers.

Order: `{{ARRIVAL-QR}}` first, on its own, because it changes a promise (owner decision 2). Then `{{ARRIVAL-AIRPORTS}}` and `{{ARRIVAL-PLACES}}` (they can run at once; `{{ARRIVAL-AIRPORTS}}` touches the same reply as `{{ARRIVAL-QR}}`), then `{{ARRIVAL-WATCH}}`, then `{{ARRIVAL-OPEN}}`. There is no Settings card issue: the owner decided on no switch or card (2026-11-18).

Model: the issue for #819 names Sonnet for the build once the design is decided, and Waypoint's `CLAUDE.md` makes Sonnet the default, privacy-sensitive work included; Opus only if Sonnet's attempt keeps missing.

---

## {{ARRIVAL-QR}} feat: the iPhone app keeps the parking QR picture with the saved trips

**Context**
Owner decision on #819 (PR #832, 2026-11-18): the iPhone app may keep a parking booking's gate QR picture with its saved trips so it shows with no connection, and the server's offline reply carries it for the person's own parking bookings only. Today `waypoint/domain/offline.py` blanks `gate_code`, and the "Email stays on the server" promise in `AGENTS.md` says the picture is "absent from the offline copy". The picture is sealed in `segment_codes` and read through `waypoint/storage/gate_codes.py`; `GET /api/segments/{id}/code` serves it today. `docs/design/arrival-codes/README.md`, "The parking QR picture on the phone", is the specification, including every wording change.

**Scope**
- `GET /api/offline`, only for a request made with the iPhone app's token (scope `app`): `offline.py` no longer blanks `gate_code` (each segment keeps `{state, day}` as the trip reply has it, `null` when there is no code), and each saved trip gains `codes: [{segment_id, type, data}]` for the requester's own parking bookings on it (seen through the visibility helper) whose `gate_code.state` is `ready` and that aren't cancelled, with the bytes exactly as `GET /api/segments/{id}/code` serves them. A browser session's reply is unchanged (`gate_code` `null`, no `codes`). The shell discovers a ready code only from this reply: `gate_code.state == "ready"` plus an entry for that segment id in its trip's `codes`; it never fetches the code route. Typed in `waypoint/server/contract.py` (`OfflineTrip`); run `make api-contract` and commit the generated files. `version` stays 1.
- Nothing else carries the picture: the browser vault, the calendar feed, reminders, `/mcp` (which still never says a booking has one) and logs are unchanged.
- The iPhone app stores the reply as today (`ios/Waypoint/OfflineSync.swift`, `OfflineStore.swift`); no Swift change beyond tests. The bridge's `load` passes `codes` through.
- `frontend/src/lib/components/GateCode.svelte`: in the shell with no connection, shows the saved picture for that booking; with none saved, the existing failure line plus the confirmation number (frame B2). Online and in browsers, unchanged.
- The promise and docs, word for word as the README's table: `AGENTS.md` (the two places), `SECURITY.md`, `docs/src/content/docs/start/offline.md`, `trips.md`, `ios.md`, `ios/README.md`, each naming the owner's decision and its date.

**Out of scope**
Anything about location or arrival (the issues below); browsers keeping the picture; any other picture.

**Acceptance criteria**
- [ ] `tests/test_gate_codes.py`'s `NeverElsewhereTests` offline test is rewritten (not removed or skipped) to: the app's reply carries exactly the requester's own ready, not cancelled parking pictures, byte for byte; a member who can't see the booking, a cancelled booking, a booking with no picture chosen and a browser session's reply carry none; the calendar feed and `/mcp` carry neither the picture nor that it exists; the request runs inside `no_leaks` with the picture's bytes as a canary.
- [ ] `tests/test_offline.py` covers the reply's shape for the app's token (a ready parking segment keeps `gate_code` `{state: "ready", day}` and has a `codes` entry with its id; a parking segment with no code keeps `gate_code` `null` and has none) and for a browser session (`gate_code` `null`, no `codes`).
- [ ] `ios/Tests/OfflineBridgeTests.swift` and `OfflineSyncTests.swift`, with a fixture in the new reply shape: `gate_code` and `codes` saved and passed through `load` unchanged, purged with the trips, and no request to `/api/segments/{id}/code` made by the sync.
- [ ] Vitest, from a saved trip in the new reply shape: the dialog offline shows the `codes` picture for a `ready` segment, and B2 for a `ready` segment with no entry.
- [ ] The UI matches the design signed off on #819; the PR shows `make verify` images at phone and desktop width.
- [ ] `make check` and the iOS workflow pass.

**Tests**
`tests/test_gate_codes.py`, `tests/test_offline.py`, `ios/Tests/OfflineBridgeTests.swift`, `frontend/src/lib/components/GateCode.svelte.test.ts`; `make check`.

**Depends on**
Nothing.

**Model**
Sonnet (Waypoint's routing puts privacy-sensitive work on Sonnet, held by the checks above).

---

## {{ARRIVAL-AIRPORTS}} feat: airport coordinates in the saved trips

**Context**
The arrival codes design (#819, `docs/design/arrival-codes/`) watches a rental pickup that has only an airport code (`origin`) around that airport. The phone's saved copy (`GET /api/offline`, `waypoint/domain/offline.py`, `waypoint/server/api/offline.py`) carries airport codes but no coordinates; the bundled `airports` table (`waypoint/storage/schema.py`, loaded by `waypoint/storage/reference.py`) has them. They are public reference data, not anyone's location.

**Scope**
- Add to each saved trip in the `GET /api/offline` reply an `airports` list, `{code, latitude, longitude}`, for the airport codes its car bookings name in `origin` (only those; no other kind). Type it in `waypoint/server/contract.py` (`OfflineTrip`), run `make api-contract` and commit the generated files.
- The field is optional for readers, so `version` stays 1 (`ios/README.md`'s "Offline bridge" and `docs/src/content/docs/start/offline.md`'s "What is saved" say so).
- Nothing else in the reply changes.

**Out of scope**
Any iPhone code (`{{ARRIVAL-PLACES}}`); street-level coordinates; the browser vault.

**Acceptance criteria**
- [ ] `tests/test_offline.py` shows the list for a trip with an airport-only car pickup, an empty list for a trip without one, and the reply unchanged otherwise.
- [ ] `make check` passes.

**Tests**
Extend `tests/test_offline.py`. `make check`.

**Depends on**
`{{ARRIVAL-QR}}` (it changes the same reply and contract type; land it after).

**Model**
Sonnet: a small, typed change to one reply.

---

## {{ARRIVAL-PLACES}} feat(ios): find each watched booking's place on the phone

**Context**
The design (#819, `docs/design/arrival-codes/README.md`, decision 4) needs a street-level point for each parking lot and rental pickup on the saved trips. The server's `segments.latitude`/`longitude` are postcode or city precision (`waypoint/storage/geocode.py`) and are not in the saved copy. The saved trips are in `ios/Waypoint/OfflineStore.swift`, filled by `OfflineSync.swift`.

**Scope**
- New `ios/Waypoint/ArrivalPlaces.swift`: from the saved trips, the qualifying bookings (parking; car pickups; hotels), not cancelled, whose window (README, point 5) hasn't ended.
- For each, the point: `details.address` looked up with `CLGeocoder` (the only file that uses it), else, for a car pickup, the airport's coordinate from `{{ARRIVAL-AIRPORTS}}`; none means the booking is not watched. Radius by kind as in the README.
- Looked up only while Waypoint has location permission (While Using or Always; there is no switch of Waypoint's own), after a successful save in `OfflineSync`, once per distinct address (cached by the SHA-256 of the address text), in a file inside that server's `OfflineStore` folder with `.complete` protection, replaced with each save and deleted by every purge.
- No network request other than the geocoder's; nothing logged.
- Update `ios/README.md` ("What is here") and `docs/src/content/docs/start/ios.md` with what is sent to Apple (the address text, once per save; owner decision, 2026-11-18) and what never is (the phone's location).

**Out of scope**
Region monitoring, notifications and the permission asks (`{{ARRIVAL-WATCH}}`); any server change.

**Acceptance criteria**
- [ ] `ios/Tests/ArrivalPlacesTests.swift` with a fake geocoder: which bookings qualify, windows, address before airport, a booking with neither left out, the cache reused for the same address, deleted by purge, `.complete` protection.
- [ ] The iOS workflow (`.github/workflows/ios.yml`) passes.

**Tests**
`ios/Tests/ArrivalPlacesTests.swift`; the iOS workflow.

**Depends on**
`{{ARRIVAL-QR}}` (the promise change lands before any arrival code); `{{ARRIVAL-AIRPORTS}}` for the airport fallback (the rest can be built first).

**Model**
Sonnet.

---

## {{ARRIVAL-WATCH}} feat(ios): watch the places and post the arrival notification

**Context**
The design (#819, `docs/design/arrival-codes/`, frames A1, A2, C and D and README points 2 to 6). There is no switch or card in Waypoint (owner decision, 2026-11-18): iOS's own permission asks are the opt-in, and iOS Settings or signing out is how to stop it. `{{ARRIVAL-PLACES}}` gives the places. The iPhone app has no CoreLocation or UserNotifications code today (`ios/README.md`). The saved copy is `.complete`, unreadable while the phone is locked.

**Scope**
- The permission asks (C1), from `ArrivalWatch.swift`, with no Waypoint prompt of our own: the first time a save leaves a parking, rental pickup or hotel booking whose window hasn't ended in the saved copy while the app is in the foreground (otherwise at the next activation), ask `requestWhenInUseAuthorization()`; if While Using is granted, `requestAlwaysAuthorization()` straight away (iOS never offers the upgrade by itself and ignores later calls); then notifications with `.alert` only. Each once, recorded in a per-phone flag; never asked while saving is off or nothing qualifies.
- New `ios/Waypoint/ArrivalWatch.swift`: region monitoring for at most 15 places, soonest window first, only with Always and Precise Location, rebuilt after each save, on becoming active, on each region event and on each authorization change; region ids `arrival-<segment id>` only.
- Authorization changes, as the README's "No switch" table: location Never or Ask Next Time stops every region, removes pending and delivered arrival notifications and deletes the arrival file and the looked-up coordinates (never a trip or picture); While Using stops regions and notifications and keeps the card; Precise Location off stops all; notifications off stops only the notification. Turning location on again resumes at the next save or activation with no new ask.
- The arrival file (`.completeUntilFirstUserAuthentication`, inside the server's folder): per watched booking its id, trip id, kind, window as two instants, centre and radius; no name, address or code. Read on a wake-up; the window and the "how often" rule (README point 5) decided from it alone.
- The notification: `UNUserNotificationCenter`, alerts only (no sound, no badge), `.passive` interruption level, title and body by kind exactly as frame A1a and A1b, `userInfo` holding the segment and trip ids; removed when the window ends. Removed with every pending and delivered arrival notification, with the arrival file and coordinates, when location is revoked or any purge runs (sign-out, 401 or 403, saving off, server change, no server).
- `Info.plist`: `NSLocationWhenInUseUsageDescription` and `NSLocationAlwaysAndWhenInUseUsageDescription` with the exact strings in the README's point 3 (frames C1a and C1b); no background mode beyond what region monitoring needs.
- The app keeps no location history, and nothing about locations or arrivals is logged.
- Docs: `ios/README.md`, and an "Arrival codes" section in `docs/src/content/docs/start/ios.md` (linked from `offline.md`) saying what it does, what is asked and when, that location never leaves the phone and addresses go to Apple Maps, that there is no switch in Waypoint, and how to stop it in iOS Settings, as the README's "No switch" table.

**Out of scope**
Any Settings card or switch in Waypoint (the owner decided there is none); opening the code (`{{ARRIVAL-OPEN}}`); Live Activities, Wallet passes; any server change.

**Acceptance criteria**
- [ ] `ios/Tests/ArrivalWatchTests.swift` with a fake location manager and notification centre: the 15 chosen, rebuilds, the window and frequency rules per kind, the notification's text and settings, nothing posted outside a window; the asks made once each, in order, only when a qualifying booking is saved and the app is in the foreground, Always requested only after While Using; each authorization change stopping and deleting what the table says; everything stopped and deleted by each purge.
- [ ] **No location reaches the server**: `ios/Tests/ArrivalPrivacyTests.swift` drives region events, the in-app check and geocoding with a recording `URLProtocol` and asserts no request goes to the Waypoint server during them and none anywhere carries the test coordinates.
- [ ] `tests/test_ios_arrival_privacy.py` fails if an `ios/Waypoint/Arrival*.swift` file names `URLSession`, `ServerClient` or `ServerAPI`, if `CLGeocoder` appears outside `ArrivalPlaces.swift`, or if any of them logs (`os_log`, `Logger`, `print`, `NSLog`).
- [ ] The iOS workflow and `make check` pass. Region wake-up, Precise Location off and timing are listed in the PR as not confirmed on a device.

**Tests**
The two Swift test files above, `tests/test_ios_arrival_privacy.py`; the iOS workflow; `make check`.

**Depends on**
`{{ARRIVAL-PLACES}}`.

**Model**
Sonnet.

---

## {{ARRIVAL-OPEN}} feat: open a booking's code from the notification or the Upcoming card

**Context**
The design (#819, frames A3 and B). The QR code dialog is `frontend/src/lib/components/GateCode.svelte`. The shell loads the person's server or the cached page (`ios/Waypoint/ShellViewController.swift`, `OfflinePageHandler.swift`).

**Scope**
- Tapping an arrival notification brings the app forward and opens that booking's trip page with its code open: the shell hands the web view the segment id (bridge request `{type: "pendingArrival"}`, answered once, or a URL query; ids only, never a coordinate). Works on the server and on the cached page.
- Parking: `GateCode.svelte`'s dialog, as `{{ARRIVAL-QR}}` leaves it (the saved picture offline, B2 when none).
- Rental pickup and hotel: a new confirmation dialog (B3) with the number large in the mono face, Copy, and the rows drawn.
- The Upcoming card (A3): the shell answers `{type: "arrivalHere"}` with the one booking whose circle you are in during its window, checked once when the app becomes active (one location request, While Using, compared in memory, nothing kept); dismiss hides it until you leave and arrive again.
- Docs: `docs/src/content/docs/start/ios.md`, and `docs/src/content/docs/start/trips.md`'s gate code section.

**Out of scope**
The saved picture itself (`{{ARRIVAL-QR}}`); new code types; opening the code by itself (the owner decided on a card, 2026-11-18).

**Acceptance criteria**
- [ ] The UI matches the design signed off on #819; the PR shows `make verify` images at phone and desktop width.
- [ ] Vitest covers the dialog's three states and the card; a Swift test covers the pending arrival being answered once and only with ids.
- [ ] `make check` and the iOS workflow pass.

**Tests**
`GateCode.svelte.test.ts` (extended), a new test for the confirmation dialog and the Upcoming card, `ios/Tests/OfflineBridgeTests.swift`; `make verify PAGES="upcoming"`; `make check`.

**Depends on**
`{{ARRIVAL-WATCH}}` and `{{ARRIVAL-QR}}`.

**Model**
Sonnet.
