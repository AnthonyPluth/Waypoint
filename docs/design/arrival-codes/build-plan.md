# Arrival codes: draft build plan

Draft agent-task issue bodies for building [the arrival codes design](README.md) ([#819](https://github.com/AnthonyPluth/Waypoint/issues/819)), in the sections the `fleet-agent-task` skill names. **None of these is to be opened before the owner signs the design off.** They assume the recommended answers to the README's open questions; each answer that differs changes the issue it names. Issues refer to each other by key in `{{…}}` until they exist.

Order: `{{ARRIVAL-AIRPORTS}}` and `{{ARRIVAL-PLACES}}` first (they can run at once), then `{{ARRIVAL-WATCH}}`, then `{{ARRIVAL-CARD}}` and `{{ARRIVAL-OPEN}}` (at once, different files). `{{ARRIVAL-QR}}` exists only if the owner answers yes to question 2, and comes after `{{ARRIVAL-OPEN}}`.

Model: the issue for #819 names Sonnet for the build once the design is decided, and Waypoint's `CLAUDE.md` makes Sonnet the default, privacy-sensitive work included; Opus only if Sonnet's attempt keeps missing.

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
Nothing.

**Model**
Sonnet: a small, typed change to one reply.

---

## {{ARRIVAL-PLACES}} feat(ios): find each watched booking's place on the phone

**Context**
The design (#819, `docs/design/arrival-codes/README.md`, decision 4) needs a street-level point for each parking lot and rental pickup on the saved trips. The server's `segments.latitude`/`longitude` are postcode or city precision (`waypoint/storage/geocode.py`) and are not in the saved copy. The saved trips are in `ios/Waypoint/OfflineStore.swift`, filled by `OfflineSync.swift`.

**Scope**
- New `ios/Waypoint/ArrivalPlaces.swift`: from the saved trips, the qualifying bookings (parking; car pickups; hotels only if the owner kept them), not cancelled, whose window (README, point 5) hasn't ended.
- For each, the point: `details.address` looked up with `CLGeocoder` (the only file that uses it), else, for a car pickup, the airport's coordinate from `{{ARRIVAL-AIRPORTS}}`; none means the booking is not watched. Radius by kind as in the README.
- Looked up only while the arrival switch is on, after a successful save in `OfflineSync`, once per distinct address (cached by the SHA-256 of the address text), in a file inside that server's `OfflineStore` folder with `.complete` protection, replaced with each save and deleted by every purge.
- No network request other than the geocoder's; nothing logged.
- Update `ios/README.md` ("What is here") and `docs/src/content/docs/start/ios.md` with what is sent to Apple (the address text, once per save) and what never is (the phone's location).

**Out of scope**
Region monitoring, notifications and the switch (`{{ARRIVAL-WATCH}}`, `{{ARRIVAL-CARD}}`); any server change.

**Acceptance criteria**
- [ ] `ios/Tests/ArrivalPlacesTests.swift` with a fake geocoder: which bookings qualify, windows, address before airport, a booking with neither left out, the cache reused for the same address, deleted by purge, `.complete` protection.
- [ ] The iOS workflow (`.github/workflows/ios.yml`) passes.

**Tests**
`ios/Tests/ArrivalPlacesTests.swift`; the iOS workflow.

**Depends on**
`{{ARRIVAL-AIRPORTS}}` for the airport fallback (the rest can be built first).

**Model**
Sonnet.

---

## {{ARRIVAL-WATCH}} feat(ios): watch the places and post the arrival notification

**Context**
The design (#819, `docs/design/arrival-codes/`, frames A1, A2 and README points 2 to 5). `{{ARRIVAL-PLACES}}` gives the places. The iPhone app has no CoreLocation or UserNotifications code today (`ios/README.md`). The saved copy is `.complete`, unreadable while the phone is locked.

**Scope**
- New `ios/Waypoint/ArrivalWatch.swift`: region monitoring for at most 15 places, soonest window first, rebuilt after each save, on becoming active, on each region event and when the switch changes; region ids `arrival-<segment id>` only.
- The arrival file (`.completeUntilFirstUserAuthentication`, inside the server's folder): per watched booking its id, trip id, kind, window as two instants, centre and radius; no name, address or code. Read on a wake-up; the window and the "how often" rule (README point 5) decided from it alone.
- The notification: `UNUserNotificationCenter`, alerts only (no sound, no badge), `.passive` interruption level, title and body by kind exactly as frame A1a and A1b, `userInfo` holding the segment and trip ids; removed when the window ends. Removed with every pending and delivered arrival notification when the switch goes off or any purge runs (sign-out, 401 or 403, saving off, server change, no server).
- `Info.plist`: `NSLocationWhenInUseUsageDescription` and `NSLocationAlwaysAndWhenInUseUsageDescription` with the wording in frame C1a; no background mode beyond what region monitoring needs.
- The app keeps no location history, and nothing about locations or arrivals is logged.
- Update `ios/README.md` and `docs/src/content/docs/start/ios.md`.

**Out of scope**
The Settings card and bridge (`{{ARRIVAL-CARD}}`); opening the code (`{{ARRIVAL-OPEN}}`); Live Activities, Wallet passes; any server change.

**Acceptance criteria**
- [ ] `ios/Tests/ArrivalWatchTests.swift` with a fake location manager and notification centre: the 15 chosen, rebuilds, the window and frequency rules per kind, the notification's text and settings, nothing posted outside a window, everything stopped and deleted by the switch and each purge.
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

## {{ARRIVAL-CARD}} feat: the Arrival codes card in Settings (iPhone app)

**Context**
The design (#819, `docs/design/arrival-codes/c-settings.html`, signed off on #819). Settings, Offline & notifications (`frontend/src/pages/Settings.svelte`) has the iPhone app's Offline access card (`frontend/src/lib/components/settings/OfflineShellCard.svelte`), talking to the shell over the offline bridge (`frontend/src/lib/offline-shell.ts`, `ios/Waypoint/OfflineBridge.swift`, contract in `ios/README.md`).

**Scope**
- Bridge: `{type: "arrivalStatus"}` and `{type: "setArrival", on}` replying `{version: 1, on, location: "notAsked"|"denied"|"whenInUse"|"always", precise, notifications: "notAsked"|"denied"|"allowed", saving, watching: [{segmentId, name, day}]}`, and `{type: "openSystemSettings"}`. Turning on asks for location, then notifications, as in C1. Written into `ios/README.md`'s "Offline bridge".
- The per-phone flag `arrivalCodes` (missing means off); `ServerSession.signOut()` removes it.
- `frontend/src/lib/components/settings/ArrivalShellCard.svelte`, below the Offline access card, only in the shell (`inShell()`): every state in C0 to C3d, words exactly as drawn, existing tokens and components only. No card in a browser.
- Docs: `docs/src/content/docs/start/ios.md` gains an "Arrival codes" section.

**Out of scope**
Watching and notifications (`{{ARRIVAL-WATCH}}`); opening the code (`{{ARRIVAL-OPEN}}`).

**Acceptance criteria**
- [ ] The UI matches the design signed off on #819; any change to layout, flow or visual style needs the owner's sign-off before merge; the PR shows `make verify` images at phone and desktop width (the card is phone-only in the app; desktop shows the page without it).
- [ ] `ArrivalShellCard.svelte.test.ts` covers each state and that no card shows outside the shell; `ios/Tests/OfflineBridgeTests.swift` covers the new requests.
- [ ] `make check` and the iOS workflow pass.

**Tests**
`frontend/src/lib/components/settings/ArrivalShellCard.svelte.test.ts`, `frontend/src/lib/offline-shell.test.ts`, `ios/Tests/OfflineBridgeTests.swift`; `make verify PAGES="settings"`; `make check`.

**Depends on**
`{{ARRIVAL-WATCH}}`.

**Model**
Sonnet.

---

## {{ARRIVAL-OPEN}} feat: open a booking's code from the notification or the Upcoming card

**Context**
The design (#819, frames A3 and B). The QR code dialog is `frontend/src/lib/components/GateCode.svelte`. The shell loads the person's server or the cached page (`ios/Waypoint/ShellViewController.swift`, `OfflinePageHandler.swift`).

**Scope**
- Tapping an arrival notification brings the app forward and opens that booking's trip page with its code open: the shell hands the web view the segment id (bridge request `{type: "pendingArrival"}`, answered once, or a URL query; ids only, never a coordinate). Works on the server and on the cached page.
- Parking: `GateCode.svelte`'s dialog, unchanged online; with no picture available it shows the existing failure line plus the confirmation number (B2).
- Rental pickup (and hotel if kept): a new confirmation dialog (B3) with the number large in the mono face, Copy, and the rows drawn.
- The Upcoming card (A3): the shell answers `{type: "arrivalHere"}` with the one booking whose circle you are in during its window, checked once when the app becomes active (one location request, While Using, compared in memory, nothing kept); dismiss hides it until you leave and arrive again.
- Docs: `docs/src/content/docs/start/ios.md`, and `docs/src/content/docs/start/trips.md`'s gate code section.

**Out of scope**
Keeping the QR picture on the phone (`{{ARRIVAL-QR}}`); new code types.

**Acceptance criteria**
- [ ] The UI matches the design signed off on #819; the PR shows `make verify` images at phone and desktop width.
- [ ] Vitest covers the dialog's three states and the card; a Swift test covers the pending arrival being answered once and only with ids.
- [ ] `make check` and the iOS workflow pass.

**Tests**
`GateCode.svelte.test.ts` (extended), a new test for the confirmation dialog and the Upcoming card, `ios/Tests/OfflineBridgeTests.swift`; `make verify PAGES="upcoming"`; `make check`.

**Depends on**
`{{ARRIVAL-WATCH}}`.

**Model**
Sonnet.

---

## {{ARRIVAL-QR}} feat(ios): keep the parking QR picture with the saved trips (only if the owner says yes)

**Context**
Today the gate's QR picture is never in the saved copy (`waypoint/domain/offline.py` blanks it; AGENTS.md's "Email stays on the server" promise says "absent from the offline copy"). Question 2 of #819's design asks whether the iPhone app may keep it.

**Scope**
- After each save, for each parking booking on the saved trips whose `gate_code.state` is `ready`, `OfflineSync` fetches `GET /api/segments/{id}/code` with the app's token and keeps the bytes in that trip's `OfflineStore` folder (`.complete`), replaced with each save and deleted by every purge and by the trip's expiry; a failed fetch keeps the older picture.
- The bridge's `load` reply gains the picture for those bookings as a `data:` URL the dialog shows; the browser path is unchanged.
- Update AGENTS.md's promise wording (with the owner's decision, dated), `docs/src/content/docs/start/offline.md`, `trips.md` and `ios/README.md`. No server change.

**Out of scope**
Browsers; any other picture.

**Acceptance criteria**
- [ ] `ios/Tests/OfflineSyncTests.swift`: fetched only for ready parking codes, kept, replaced, purged, expiry; never logged.
- [ ] `tests/test_offline.py` and `tests/test_gate_codes.py` still show the server's reply without the picture.
- [ ] `make check` and the iOS workflow pass.

**Tests**
As above.

**Depends on**
`{{ARRIVAL-OPEN}}`, and the owner's yes to question 2.

**Model**
Sonnet.
