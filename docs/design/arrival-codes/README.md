# Arrival codes on the iPhone: draft design

This is the design for [#819](https://github.com/AnthonyPluth/Waypoint/issues/819): when you arrive near the address of a booking on a saved trip, the iPhone app brings up that booking's code (a parking lot's gate QR code, a rental pickup's confirmation number) so you don't have to dig for it. **It is a draft. The owner has not signed it off, and nothing is built until they do.** The recommendations below are proposals; the open questions at the end are the owner's to answer.

Owner context from the issue and from 2026-11-18: no Live Activities and no Wallet passes (Wallet and the airline apps already do those), no clutter, and the phone's location never leaves the phone.

Each file is a self-contained HTML page (vector only, no raster images, dark only, phone width 390 px only). The pages use Waypoint's tokens from `frontend/src/app.css` and add none. The iOS lock screen, banner and permission alerts are drawn only to place Waypoint's parts; their look is Apple's. Every place, name, code and time in them is made up, and the QR pattern is random.

| Screen | File | What it shows |
| --- | --- | --- |
| A | [a-arrival.html](a-arrival.html) | The closed notification on the lock screen (parking, rental pickup, hotel; the recommended wording and the place-name alternative), the same notification as a banner over another app, and the card at the top of Upcoming when you open Waypoint near the place |
| B | [b-opened-code.html](b-opened-code.html) | What opens: the existing QR code dialog for parking, the same dialog with no connection when the picture isn't on the phone, and the confirmation number for a rental pickup and a hotel |
| C | [c-settings.html](c-settings.html) | The Arrival codes card in Settings, Offline & notifications: in place, off by default, the location and notification permission steps, on (Always, While Using, nothing to watch), and each missing piece (location refused, Precise Location off, notifications refused, saving trips off) |

The draft build plan, as agent-task issue bodies, is in [build-plan.md](build-plan.md).

## What each booking holds today

Checked on `main` at the time of writing (`waypoint/storage/schema.py`, `waypoint/domain/trips.py`'s `DETAIL_KEYS`, `waypoint/domain/offline.py`, `waypoint/storage/geocode.py`, `frontend/src/lib/components/GateCode.svelte`).

| Kind | The code Waypoint holds | On the phone's saved copy? | Where it is, and how precisely | Missing for this feature |
| --- | --- | --- | --- | --- |
| Parking | The gate's QR picture (`segment_codes`, sealed, served only by `GET /api/segments/{id}/code`), and the confirmation number | Confirmation: yes. **QR picture: no.** `offline.py` blanks `gate_code`, emails are saved without images, and the promise says the picture is "absent from the offline copy" | The lot's address in `details.address` when the email gave one (SpotHero's parser, a calendar invite's location, schema.org markup). Server coordinates are only postcode or city precision | A street-level coordinate. The picture on the phone, if it should come up with no connection (question 2) |
| Rental car | The confirmation number; `car_class` | Yes | The pickup address in `details.address` from schema.org markup, or only the pickup airport's code in `origin`. Server coordinates: postcode, city or airport | A street-level coordinate. No pickup code, locker code or QR is parsed or stored |
| Hotel | The confirmation number; `room` when known; `phone` | Yes | `details.address` from markup or the lodging reader. Server coordinates: postcode or city | A street-level coordinate. No check-in code, check-in QR or mobile key is parsed or stored (a mobile key lives in the hotel's own app or Wallet) |
| Flight | The confirmation number (record locator); `terminal`, `seat`, `flight_number` | Yes | The airports' codes. The airports' coordinates are bundled reference data on the server (`airports` table), not in the saved copy | No boarding pass is stored, and it stays out of scope (Wallet and the airline's app show it near the airport already) |

Two facts shape the design:

- **The server's coordinates are too coarse.** `segments.latitude`/`longitude` come from the bundled geocoder (`geocode.locate`), whose best precision is a postcode centroid, often a kilometre or more from the lot; they are also not in the `Segment` reply or the saved copy. A street-level point has to be found another way (decision 4).
- **The saved copy is unreadable while the phone is locked.** `OfflineStore` writes with `.complete` file protection, so when iOS wakes the app for a region while the phone is locked, it can't read the trips. What the wake-up needs is kept in a small separate file (decision 4).

## The six points, answered

### 1. Which bookings and which codes

**Recommended for the first build: parking and rental pickup.**

- **Parking**: the gate's QR picture, the one real "code" Waypoint holds. This is the case the idea is for.
- **Rental pickup**: the confirmation number, which is what the counter asks for. Only the pickup (`start_local`), not the return.
- **Hotel**: the confirmation number and room if known. Useful at a front desk, but they usually ask for a name; proposed **off** unless the owner wants it (question 1), to keep clutter down.
- **Flight**: **left out.** Waypoint has no boarding pass, Wallet already brings one up at the airport, and an airport-sized circle fires at every drop-off and pickup there.
- Trains, cruises and visits are not part of this.

Nothing new is parsed for this. Hotel check-in codes, rental pickup codes and boarding passes would each be new parsing and new storage of a code; they are listed as missing above and are not in the plan.

### 2. What happens on arrival

**Both, at different permission levels.**

- **Notification** (needs Always location and notifications): one local notification when you enter a booking's circle during its window. Passive interruption level: no sound, no badge, no vibration. It names only the kind ("Your parking code is ready"), never the place, a name or a code (frame A1a; A1c shows the place-name alternative). Tapping it unlocks the phone and opens the code (B). It is removed from Notification Centre when the booking's window ends.
- **Card on Upcoming** (While Using is enough): opening or returning to the app inside the circle during the window puts one card at the top of Upcoming, "You're at Harbour Parking, Lot B", with one button that opens the code and a dismiss (A3). One card at a time. It does not open the code by itself (question 3).
- What opens is the existing **Show QR code** dialog for parking, unchanged, and for a rental pickup or hotel a new dialog with the confirmation number large and copyable (B3). Closing either leaves you on that booking's trip page. Online, the parking dialog fetches the picture as today; with no connection and no picture on the phone, it says so and also shows the confirmation number (B2).

### 3. Location permission

**Recommended: one switch, asking for While Using first; Always is what makes the notification work.**

- Switching on asks iOS for location (While Using) and then for notifications (alerts only, no sound or badge). While Using gives the card (A3). iOS later offers, by itself, to change to Always; with Always, region monitoring wakes the app and the notification works. The card says which of the two you have (C2a, C2b) and points to iOS Settings for the rest. The app never asks twice.
- Region monitoring can't work with approximate location, so with Precise Location off the card says it isn't working (C3b). This and the wake-up behaviour come from Apple's documentation and are not confirmed on a device.
- **Which bookings get a region**: iOS allows 20 per app. The app watches at most 15 (5 to spare): every qualifying booking on the saved trips whose window hasn't ended, soonest window first. The saved trips are at most 10 (under way, starting within 7 days, and the next one), so 15 covers nearly every household; past 15, the soonest 15. The set is rebuilt after each save of the trips, each time the app becomes active, on each region event and when the switch changes.

### 4. Privacy (binding)

- **The phone's location never leaves the phone.** No location, region event, arrival or "near a booking" fact is sent to the server, to Apple, or to anyone; no new server route is added. The web view is told only which booking to open (its id), never a coordinate.
- **Nothing is recorded.** The app keeps no location history: it uses iOS region monitoring (enter events) and, for the card, one current-location check when the app becomes active, compared in memory and dropped. Nothing about locations or arrivals is logged, in the app or on the server.
- **Works from the saved trips, with no connection.** The bookings come from `OfflineStore`, never from a live request. Watching, the notification and the card work in airplane mode. (The parking picture still needs a connection unless question 2 says the app may keep it.)
- **Finding the places.** Recommended: the phone looks each booking's address up with Apple's geocoder (`CLGeocoder`) once, when the trips are saved, and keeps the coordinate beside the saved trips. This is "on the device" in that Waypoint's server is not involved, but **it sends the booking's address text (not the phone's location) to Apple, and needs a connection at that moment.** For a rental pickup with only an airport code, the airport's bundled coordinate is used (the server adds it to the saved copy; it is public reference data). The alternatives are in question 4. The card says so in one plain line (C).
- **What the phone keeps for a locked wake-up.** A small arrival file beside the saved trips, readable after the first unlock since restart (`.completeUntilFirstUserAuthentication`), holding for each watched booking only its id, its trip's id, its kind, its window as two instants, the circle's centre and radius. No name, address, code or confirmation number. The geocoded coordinates live in the saved trips' own folder under `.complete`.
- **Turning it off** stops every region, removes pending and delivered arrival notifications and deletes the arrival file and the looked-up coordinates. It deletes no saved trip. **Signing out**, a 401 or 403, switching saving off, a changed server address and launching with no server do the same, as part of the purge they already do. Switching saving off also turns the card to C3d: arrival codes need the saved trips.
- **The card says what it does** in plain words (C), saying "this device" as the Offline access card does: what it brings up, that location stays on the phone and is not recorded, and that addresses are looked up with Apple Maps. (The Offline access card has no privacy sentence by the owner's decision of 2026-11-17; #819 asks for one here.)
- **The test that proves no location reaches the server** (#819's acceptance criterion): an iOS unit test drives region events, the in-app check and the geocoding with a recording URL protocol and asserts that no request is made to the Waypoint server at all during them and that no request anywhere carries the test coordinates; a Python test fails if the arrival Swift files reference `URLSession`, `ServerClient` or `ServerAPI`, if `CLGeocoder` appears outside the one geocoding file, or if any `os_log`/`Logger`/`print` call appears in them. Server side, nothing changes but the airport coordinates in `GET /api/offline` (`tests/test_offline.py`).

### 5. Window and radius

Proposed defaults. Times are the booking's own wall-clock times in its zone, turned into instants on the phone.

| Kind | Circle | Window | How often | Stops |
| --- | --- | --- | --- | --- |
| Parking | 250 m around the lot's address | From 2 h before entry until the exit time | Once per arrival, at most once every 4 h (so the drop-off and the return for an exit gate each get one) | After the exit time, when cancelled, removed, its trip is no longer saved, or the switch is off |
| Rental pickup | 300 m around the pickup address; 2 km around the airport when only an airport code is known | From 2 h before pickup until 4 h after | Once | After the first notification or card, or the window's end |
| Hotel (if kept) | 200 m around the address | Check-in day, from 3 h before check-in until midnight there | Once | After the first notification or card, or the window's end |

iOS region monitoring is not precise below roughly 100 to 200 m and can fire minutes after you cross the line; these radii allow for that and are to be tuned on a device. A booking with no usable address (no `details.address` and no airport code) is not watched.

### 6. Where the switch lives, and its default

**Settings → Offline & notifications → Arrival codes**, a card of its own directly below Offline access (C0), only inside the iPhone app; in a browser there is no card (browsers can't watch places). The switch is **Bring up codes when I arrive**. It is **off** until the person switches it on and allows location. It is per phone (a `UserDefaults` flag, missing means off), and signing out turns it off again (unlike saving trips, which signing in turns on), so a new sign-in never watches places without being asked. It needs **Save my upcoming trips**: while saving is off, the switch is disabled and says so (C3d).

## Proposed decisions (2026-11-18, not signed off)

- First build: parking (QR picture) and rental pickup (confirmation number). Hotel off unless the owner keeps it; flights left out.
- No Live Activities, no Wallet pass, no new parsing of codes.
- Notification with Always; card on Upcoming with While Using; one switch, While Using asked first.
- Passive notification, no sound, no badge, wording by kind only, nothing identifying on the lock screen.
- The existing QR code dialog opens unchanged; a confirmation dialog for rental pickup and hotel.
- Location never leaves the phone and isn't recorded; no new server route; the web view gets a booking id only.
- Addresses looked up with Apple's geocoder once per save, coordinates kept beside the saved trips; airport coordinates from the server for airport-only pickups.
- At most 15 regions, soonest window first, rebuilt on save, activation, region event and switch.
- Windows and radii as in the table above, to be tuned on a device.
- Settings card below Offline access, off by default, per phone, off again after sign-out, needs saved trips.
- Turning it off stops everything and deletes the derived arrival file and coordinates, never a trip.

## Open questions for the owner

1. **Which kinds?** Parking and rental pickup as recommended? Keep hotels (confirmation number at the front desk)? Confirm flights are left out.
2. **May the iPhone app keep the parking QR picture with the saved trips**, so it comes up with no connection? Today the picture is never on any device ("absent from the offline copy" in AGENTS.md's promise, and the docs). Proposed: yes, in the iPhone app only, fetched with the app's token from the existing `GET /api/segments/{id}/code` for parking bookings on saved trips, kept in the same protected store and deleted with it; browsers unchanged. If no, B2 is what you see offline.
3. **Opening the app near the place**: a card with one tap to the code (recommended), or open the code straight away?
4. **Finding the places**: accept that the phone sends each booking's address to Apple's geocoder once when the trips are saved (recommended; the phone's location is never sent)? The alternatives are the server's postcode-level coordinates (no outside service, but often a kilometre off, too coarse for a lot) or watching only bookings with an airport code.
5. **Lock screen wording**: kind only, "Your parking code is ready" (recommended), or the place's name (A1c), which also puts the name in the file readable while locked?
6. **Windows and radii**: are the defaults in the table right, in particular the second notification for a parking exit?
7. **The card**: the names "Arrival codes" and "Bring up codes when I arrive", its place below Offline access, off after sign-out, and the two privacy lines on the card?
8. **Turning it off** deletes the derived arrival file and coordinates but no trip: is that what #819 means by "deletes nothing"?

## Not confirmed

None of this has run on a device. Region monitoring's wake-up with Always, its behaviour with Precise Location off, how late it fires, and whether a wake-up while locked can read the arrival file are from Apple's documentation. The build plan says what each issue can check in CI and what needs a phone.
