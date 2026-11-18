# Siri and Shortcuts in the iPhone app

Exploration for [#820](https://github.com/AnthonyPluth/Waypoint/issues/820). Nothing here is built. The owner chose which intents to build and how they speak on 2026-11-18 ("Owner decisions" below). The look of the frames, the phrases and the wording are **not signed off yet**, and the questions still open are at the end. The mock frames are self-contained HTML pages (vector only, no raster images, dark only, phone width 390 px only), using Waypoint's tokens from `frontend/src/app.css` and adding none. Every trip, hotel, flight and time in them is made up. The system parts of each frame (Siri's glow, the unlock prompt, the Shortcuts app) are drawn roughly, only to place Waypoint's card; Apple draws them, not us.

| Screen | File | What it shows |
| --- | --- | --- |
| a | [a-answers.html](a-answers.html) | The four chosen intents on an unlocked phone: next flight (later this week, today, across zones), tonight's stay and its check-out phrase (including check-out morning), parking code (opens the booking; none saved), open my trip (a saved trip; a place with no saved trip), and the four actions in the Shortcuts app |
| b | [b-states.html](b-states.html) | What the intents say when they can't answer: phone locked, not signed in, saving switched off, nothing saved yet, a copy that can't be read, no flight or stay in the saved trips, a saved copy that is days old, and a copy saved before it carried city names |

Owner context (2026-11-18): interested in Siri; no Live Activities; doesn't want clutter.

## Owner decisions (2026-11-18, in chat on PR #831)

1. **Build A (next flight), B (tonight's stay, with check-out), C (parking code) and D (open my trip to a place).** E (live flight status) is not built, so no intent calls the server.
2. **Spoken answers use city names**, not the flight number and the zone's name: "Your next flight leaves Denver for Grand Junction on Thursday at 7:40 am, local time." The saved copy has airport codes only, so `GET /api/offline` first carries the cities of each saved trip's airports, and the app keeps them with the rest of the copy. That is its own build issue, which the intents depend on ({{OFFLINE-CITIES}} below).
3. **"My next flight" is anyone's flight on a trip the person is on**, the same rule as Upcoming's next flight. No `person_id` is needed.
4. **Siri's own handling is accepted.** The spoken request and answer pass through Apple's Siri, as Apple's Siri settings describe. The never-spoken list is unchanged: confirmation codes, gates, loyalty numbers, seats, rooms and other travellers' names (with the rest of section 3's list).

Not decided yet, so the frames and drafts use these defaults and the questions stay open at the end:

- **Phrases:** the ones in section 1.
- **Whether the zone is always said:** yes, as "local time" after the departure city, which says whose time it is.
- **The street address on the stay card:** shown on the card, never spoken.
- **Saying the age of an old saved copy:** on the card only.

## What exists today

Facts from `main` that bind the design:

- **The saved trips are the `GET /api/offline` reply, kept as raw JSON.** `OfflineStore.swift` writes it as files in Application Support, one folder per server address, and never decodes a trip beyond its `name` and dates (for expiry and the bridge's `status`). The reply holds the trips the signed-in person may see that are under way, starting within 7 days, or the next upcoming one, at most 10 (`domain/offline.py`). Each trip is the web app's `Trip` (`server/contract.py`): bookings with `kind`, `status`, `confirmation`, `provider`, `start_local`/`start_zone`, `end_local`/`end_zone`, `origin`, `destination`, `details` (`flight_number`, `terminal`, `seat`, `room`, `address`, `phone` and the rest of `DETAIL_KEYS`), `travelers`, and the kept emails. It never holds loyalty or Known Traveler numbers (`tests/test_offline.py` checks with canaries), live flight status, or a parking booking's QR code (`gate_code` is set to `None`).
- **The files are readable only while the phone is unlocked.** They are written with `.complete` file protection. On a locked phone the app cannot read them at all, whatever an intent asks. The server address and tokens are in the Keychain with `AfterFirstUnlockThisDeviceOnly`, so they are readable on a locked phone after the first unlock; the trips are not.
- **The copy is refreshed only when the app is opened or comes back to the front** (`OfflineSync`), with the app's token. An intent that runs in the background does not refresh it, so an answer is as old as the last time the person opened Waypoint online.
- **Times are wall-clock times at the place** (`start_local` in `start_zone`); nothing converts them.
- **The copy has airport codes, not city names**, for flights (`origin`, `destination`); city names come from the server's `/api/trips/{id}/places`, which isn't saved. A hotel's name is its `origin`, its city its `destination` (the web app's `headline` in `frontend/src/lib/trips.ts`).
- **Trip pages are hash routes** in the web app: `#trip/{id}` and `#trip/{id}/flight/{segmentId}`.
- **The app targets iOS 16.0** (`ios/project.yml`), builds with Xcode 26 on `macos-26`, and CI (`.github/workflows/ios.yml`) builds it and runs `WaypointTests` on a simulator, unsigned. App Intents exist from iOS 16.
- **The web app's next flight** on Upcoming is the next timed, not-cancelled flight among the trips you can see, whoever is on it; it is not narrowed to the signed-in person's own seat. The saved copy has no `person_id` for "me" (that is in `GET /api/state`, which is not saved).

## 1. Candidate intents

Apple's way in is App Intents. Each intent below is an `AppIntent` in the app target, listed in an `AppShortcutsProvider` so it works by voice with no setup and shows in the Shortcuts app and Spotlight. **Apple requires every App Shortcut phrase to contain the app's name**, so "When is my next flight?" on its own won't reach Waypoint; "When is my next flight in Waypoint?" or "Waypoint, next flight" will. A person can make their own shortcut in the Shortcuts app with any phrase they like, from the same action.

"Card" is the snippet Waypoint draws under Siri's spoken answer (a small SwiftUI view, `ShowsSnippetView`). Tapping it opens the app at the booking.

| # | Intent | Phrases (each also accepts the app name at the start) | Spoken answer | On screen |
| --- | --- | --- | --- | --- |
| A | **Next flight** | "When is my next flight in Waypoint", "Waypoint next flight", "When do I fly in Waypoint" | "Your next flight leaves Denver for Grand Junction on Thursday at 7:40 am, local time." Today: "Your flight leaves Denver for Grand Junction today at 7:40 am, local time, in 3 hours." (Owner's decision: city names.) | Card: flight number, `DEN → GJT` with each city, departs and arrives as wall-clock times with each airport's zone, the trip name, "Booked times · saved 2 hours ago". Tap opens `#trip/{id}/flight/{segmentId}`. |
| B | **Tonight's stay** (also answers "when do I check out") | "Where am I staying tonight in Waypoint", "When do I check out in Waypoint", "Waypoint hotel" | "Tonight you're staying at Hotel Example in Grand Junction. You check out Sunday at 11 am." Check-out phrase: "You check out of Hotel Example on Sunday at 11 am." | Card: hotel name and city, the street address (on screen only), check-in and check-out with the hotel's zone, nights. Tap opens `#trip/{id}`. |
| C | **Parking code** | "Show my parking code in Waypoint", "Waypoint parking" | "Opening your parking at Lot Example." Never the code, never the confirmation. | Opens the app at the parking booking, where the existing **Show QR code** button is. The QR code comes from the server (`GET /api/segments/{id}/code`) and is never saved on the phone, so with no connection the booking opens without it. |
| D | **Open my trip to a place** | "Open my trip to \<place\> in Waypoint", "Waypoint open \<place\>" | "Opening your trip to Grand Junction." | Opens `#trip/{id}`. \<place\> is a trip from the saved copy, matched by its name or destination. |
| E | **Live flight status** (as asked: "is my flight on time"; not chosen) | "Is my flight on time in Waypoint" | "Your flight to Grand Junction is delayed 35 minutes; it now leaves at 8:15 am." | Card like A with the status pill. Needs the server (below). |

"When do I check out?" is folded into B, not a separate intent: one intent that answers both, behind two phrases, gives the same answers with one tile less in Shortcuts. The issue's five candidates are A, B (twice), C and D; E is listed because a person asking about their flight will expect it, and it is where the server comes in.

## 2. From the saved trips alone, or the server

| Intent | Saved copy alone | Needs the server |
| --- | --- | --- |
| A Next flight | Yes, once the copy carries the airports' cities ({{OFFLINE-CITIES}}): the next timed, not-cancelled flight in the saved trips, anyone's on a trip the person is on, from its booked times (the same rule as Upcoming's next flight). Untimed flights (`details.time_unknown`) are skipped. A flight in a trip further out than the saved window isn't seen, so the answer says "in the trips saved on this iPhone" when there is none. A copy saved before the cities were added speaks the flight number instead, until the next online open replaces it. | The cities, once, in the saved copy (`GET /api/offline`), not at the moment of asking. |
| B Tonight's stay | Yes. The two phrases select differently. **Tonight:** a not-cancelled hotel whose nights include tonight (tonight is today in the hotel's own zone: check-in day on or before today, check-out day after it), else the next saved stay. **Check-out:** the not-cancelled stay under way now, from its check-in time until its check-out time (`start_local` to `end_local`, wall-clock in the hotel's zone). So at 8 am on check-out morning it is still that stay, until 11 am. With two under way it is the one that checks out first; past the check-out time, or with none under way, it is the next saved stay. | Nothing. |
| C Parking code | Finding the parking booking: yes. | The QR code itself, as today, once the app is open. |
| D Open my trip | Yes: the saved trips' names and destinations. A trip outside the saved window can't be named by voice (the app could still open it online). | Nothing. |
| E Live status | No: live status is never saved, and the gate is never in the copy. | `GET /api/flight-status` with the app's token, a native request the app doesn't make today. It sends nothing new to the server (the server already holds the booking and the status), but it is a new request at a new moment, which the issue rules out ("nothing new is sent to the server") unless the owner decides otherwise. |

## 3. Privacy, per intent

The rules for every intent:

- **Locked phone: every intent that reads trips asks for the phone to be unlocked first.** Each one sets `authenticationPolicy = .requiresAuthentication`, so Siri shows the system's unlock prompt before Waypoint runs, and nothing is said or shown until it is unlocked. That is not only a choice: with `.complete` file protection the app can't read the saved trips while the phone is locked. If it is ever asked to (a race at the moment of locking), the read fails and the answer is "Unlock your iPhone to see your trips in Waypoint", with no trip in it. The same applies with AirPods or CarPlay while the phone is locked: Siri asks for an unlock, and Waypoint says nothing first. Siri on a HomePod, which can't unlock the phone, gets no answer at all.
- **What is never spoken:** a confirmation code or record locator, a gate, a loyalty or Known Traveler number (never in the copy anyway), a parking code, a seat, a room number, a phone number, a street address, an email's subject or text, other travellers' names. What can be spoken: the departure and arrival cities, the day and the time, the hotel's name and city, the parking lot's name, the trip's destination or name (and the flight number, only for a copy saved before it carried cities). A spoken answer can be heard by anyone nearby, so it says only what a person needs to act on.
- **What is never on the card**, though the phone is unlocked: a confirmation code, a gate, the QR code, loyalty and Known Traveler numbers, a seat or room number, email text. The card is a glance, not the booking: the app (one tap) shows the rest, behind its own screens as today. The street address of a stay is on B's card (open question 3). No seat is on A's card: the flight is anyone's on the trip (owner's decision), so there is no one seat to show.
- **Only the signed-in person's saved trips.** An intent reads only `OfflineStore` for the server in `ServerSession.shared.server`, the same folder the bridge reads, and only while that session exists. Signed out, there is no copy (sign-out deletes it) and no answer: "Sign in to Waypoint on this iPhone first." The copy holds only trips that person may see (`domain/offline.py`, through `visibility`), so nothing else can be answered.
- **Nothing new sent to the server, and nothing to anyone else.** A, B, C and D make no network request: the answer code takes the saved copy and the clock and has no `ServerClient`. C and D open the app, which then does what it does on any open (load the server, refresh the copy). E would have been the exception and is not built. The cities come with the saved copy the app already fetches ({{OFFLINE-CITIES}}): reference data about airports on bookings the person can already see, with no new request.
- **Nothing handed to the system's indexes.** No `IndexedEntity` or Core Spotlight items, no `IntentDonationManager` donations, no `NSUserActivity` carrying a trip, and no Apple Intelligence schemas (`AssistantSchemas`), so trip names, places and times are not put into Spotlight's index or Siri's suggestions. The App Shortcuts themselves (the phrases and the action names) do show in Spotlight and Shortcuts; they hold no trip data. D is the one exception, now chosen: a voice phrase with a trip in it needs the saved trips' places given to the system's phrase list (`updateAppShortcutParameters()`), on the phone. They are replaced on every save and cleared on every purge (sign-out, 401 or 403, saving off, a changed server). Only the saved trips' destinations and names are given, never a booking.
- **Apple's side, accepted by the owner (2026-11-18).** Siri turns speech into text on the phone for most requests on recent iPhones, but Apple says some requests are sent to its servers, and a person who opted into "Improve Siri & Dictation" shares audio with Apple. Nothing read for this note says whether the dialog text an App Intent returns leaves the phone; that is still worth confirming on a device. The owner accepted that the request and answer pass through Siri, with the never-spoken list unchanged.

Per intent:

| Intent | Locked phone | Spoken | On the card |
| --- | --- | --- | --- |
| A Next flight | Unlock first | Departure and arrival cities, day, time ("local time") | Flight number, airport codes and cities, times with zones, trip name, how old the copy is |
| B Tonight's stay | Unlock first | Hotel name, city, check-out day and time | Hotel name, city, address, check-in and check-out with zone, nights |
| C Parking code | Unlock first (it opens the app) | "Opening your parking at \<lot\>" | Nothing: the app opens |
| D Open my trip | Unlock first (it opens the app) | "Opening your trip to \<place\>" | Nothing: the app opens. The saved trips' places stay in the system's phrase list until the next save or purge |
| E Live status (not built) | Unlock first | As A, with the delay; never the gate | As A, with the status pill; never the gate |

## 4. How it is built and tested

**Where the code goes.** In the app target, `ios/Waypoint/`, not an App Intents extension: an extension runs in its own process and would need the saved trips moved to an App Group container, which changes where the copy lives (the promises name the app's own private storage). Intents in the app target run in the app's process, in the background unless they open the app.

- `SavedTripsReader.swift`: decodes the saved copy into a small read model of only what the intents use (trip id, name, dates; per booking id, kind, status, start and end with zones, origin, destination, `provider`, and from `details` only `flight_number`, `address` and `time_unknown`; and each saved trip's `cities`, from {{OFFLINE-CITIES}}). It never decodes `confirmation`, `manage_url`, `travelers`, seats, rooms, phone numbers or the emails, so they can't reach an answer by accident. It reads through `SavedTrips.read(_:server:)`, like the bridge.
- `TripAnswers.swift`: pure functions from that model, the clock and the phone's time zone to an `Answer` (the spoken text, the card's fields and the page to open), plus the fixed answers for locked, signed out, saving off, nothing saved and nothing found. No `URLSession`, no `ServerClient`, no Keychain.
- `WaypointIntents.swift`: the `AppIntent`s and the `AppShortcutsProvider`, thin wrappers that read the session, call `TripAnswers` and return its dialog and card. Opening the app at a page sets the web view's address (as `ShellViewController.serverURL` does at launch), with `#trip/{id}`.
- `TripAnswerCard.swift`: the SwiftUI card.
- `ios/README.md`'s table and "Not built yet", and `docs/src/content/docs/start/ios.md`, get a "Siri and Shortcuts" section saying what each intent answers, that it needs the phone unlocked and that it answers from the saved trips only.

**Unit tests (CI can run these)**, in `ios/Tests/TripAnswersTests.swift`, with fixtures like `TripFixtures` in `OfflineBridgeTests.swift` (made-up trips, a fixed `now`, a fixed calendar):

- Next flight: the next timed flight, skipping cancelled, untimed and past ones; a flight today versus later this week; times read as wall-clock times in the flight's own zone (a fixture where the phone's zone differs, and one across a date line), never converted; the departure and arrival cities in the spoken text; a copy without `cities` falling back to the flight number; a flight with other travellers on a trip the person is on still counts.
- Tonight's stay: tonight inside the stay, the last night, no stay tonight with a later one, none at all.
- Check-out: for a stay checking out Sunday at 11 am in its own zone, asking at 8 am that Sunday answers "You check out of Hotel Example today at 11 am" (that hotel, not the next one, and not "no stay"). Asking at 11:01 am answers with the next saved stay, or none. A stay ending today and another starting today answers with the one ending. The phone's zone differs from the hotel's in one fixture.
- The empty states: no session, saving off, nothing saved, an unreadable copy, a copy for another server, a read that fails as if locked: each answers its fixed text and holds no trip data.
- Parking and open my trip: the current or next parking booking; a trip matched by destination or name, two matches, none; the phrase parameters replaced on save and emptied on purge.
- No leaks: fixtures carry canary values in `confirmation`, `details.seat`, `details.room`, `details.phone`, `details.terminal`, `travelers` and an email's text; no spoken text or card field contains any of them (the Swift twin of `tests/privacy.py`'s `no_leaks`).
- No network: a `URLProtocol` registered for the test fails on any request; running every intent's `perform()` against a saved copy makes none.
- Each intent's `authenticationPolicy` is `.requiresAuthentication` (a static property, readable in a test).

**What CI also checks.** The `xcodebuild test` step builds the app, and Xcode's App Intents metadata step runs in that build, so a phrase without the app name or a malformed `AppShortcutsProvider` fails the build. CI does not run Siri, speak a phrase, show a card or lock a simulator (the simulator doesn't enforce Data Protection).

**What only a device can check** (TestFlight, which the "iOS TestFlight" workflow already ships):

- Siri hears each phrase and runs the right intent; how it reads a flight number, a time and a zone's name aloud.
- On a locked phone, Siri asks for the unlock before anything is said, with the phone in hand, with AirPods and in CarPlay; a HomePod gets nothing.
- The card's look in Siri and in Shortcuts, at the text sizes people use.
- The actions show in the Shortcuts app and Spotlight, and nothing else of Waypoint does (no trip in Spotlight's search).
- After sign-out, or with saving switched off, every intent gives its empty answer.
- Tapping the card opens the app at the right booking, online and with no connection (the cached page).

## 5. Recommendation, and what was chosen

The first draft recommended A and B as the smallest first set. They answer from the saved trips alone, with no network, so they work in the air and at a hotel with bad Wi-Fi. They need the phone unlocked, and they hand no trip data to Spotlight or Siri's suggestions. On 2026-11-18 the owner chose A, B, C and D, and not E (see "Owner decisions"). What that adds:

- **C, parking code** only opens the app at the parking booking. The code itself still comes from the server once the app is open, so at a gate with no signal the booking opens without it. Location-triggered codes stay a separate issue.
- **D, open my trip** gives the saved trips' places to the system's phrase list on the phone. It must replace that list on every save and empty it on every purge, which its build issue tests.
- **City names** need the saved copy to carry the cities of its airports first, so the build starts with that server change.

Build order: {{OFFLINE-CITIES}}, then {{SIRI-ANSWERS}} (A and B), then {{SIRI-PARKING}} (C) and {{SIRI-OPEN-TRIP}} (D), which can be built at the same time as each other.

## Draft build issues

These are not opened yet. They are drafts written in the `fleet-agent-task` sections, using the owner's decisions above and the defaults for what is still open. The model is Sonnet, per `CLAUDE.md`'s routing (privacy-sensitive work included) and the issue's own Model line. Before any issue that draws the card ({{SIRI-ANSWERS}}) merges, the owner signs off on the card's design: the frames here are not signed off.

### {{OFFLINE-CITIES}} feat: the saved trips carry the cities of their airports

**Context**
On #820 the owner chose spoken Siri answers with city names ("leaves Denver for Grand Junction"); design: `docs/design/siri-shortcuts/README.md`. The saved copy is the `GET /api/offline` reply (`waypoint/server/api/offline.py`, `waypoint/domain/offline.py`, contract `Offline` and `OfflineTrip` in `waypoint/server/contract.py`). It holds each flight's airports as codes (`origin`, `destination`) only. The airports table has the city of each code (`waypoint/domain/airports.py`, `lookup`). The iPhone app saves the reply as raw JSON (`ios/Waypoint/OfflineStore.swift`) when `version` is 1 (`OfflineSync.supportedVersion`). The bridge's `load` (`ios/Waypoint/OfflineBridge.swift`) passes each saved trip to the web app unchanged. The browser saves the same reply through `frontend/src/lib/offline.ts`.

**Scope**
- `waypoint/domain/offline.py`: each `SavedTrip` gains `cities`, a map from airport code to city name. It covers only the `origin` and `destination` of the trip's flight bookings that the airports table knows. A code it doesn't know is left out, and a trip with no flights gets `{}`. The map is built inside `_saved`, from the trip `trips.get` already returned for the viewer, so it covers only bookings the person can see.
- `waypoint/server/contract.py`: `OfflineTrip.cities: dict[str, str]`. `waypoint/server/api/offline.py` passes it through. Run `make api-contract` (`docs/openapi.json`, `frontend/src/lib/api-types.ts`).
- **Version:** `version` stays 1. The field is additive, and readers ignore what they don't use: the web app spreads the trip, and the app saves the raw reply. Bumping to 2 would make every installed app that knows only 1 keep its old copy and show "Couldn't save the trips" until it is updated, as `OfflineSync` does for an unknown version. `ios/README.md` says to change the number only together with the web app. If the owner wants a bump anyway (open question 5), this issue ships the app accepting 1 and 2 first, then the server sending 2.
- iPhone app: no change to `OfflineStore` or `OfflineSync`, which keep the reply as it came. A test shows `cities` survives save, load, expiry pruning and the bridge's `load`.
- Docs: `docs/src/content/docs/start/offline.md` ("What is saved": "the cities of the trip's airports") and the reply shape under "The reply, and the iPhone app".

**Out of scope**
The Siri intents ({{SIRI-ANSWERS}}). Station or port cities for trains and cruises. City names anywhere else in the web app.

**Acceptance criteria**
- [ ] `tests/test_offline.py` shows `cities` holds exactly the cities of the saved trip's own flight airports. A booking the viewer can't see, and a trip they aren't on, adds nothing.
- [ ] The existing canary test (`test_no_loyalty_or_known_traveler_number_is_in_the_reply`) still passes, and `no_leaks` holds for the reply.
- [ ] `ios/Tests/OfflineStoreTests.swift` and `ios/Tests/OfflineBridgeTests.swift` show `cities` kept through save, load, pruning and the bridge's `load`. "iOS build and tests" passes.
- [ ] `make check` passes, including `make api-contract-check`.

**Tests**
Extend `tests/test_offline.py`, `ios/Tests/OfflineStoreTests.swift` and `ios/Tests/OfflineBridgeTests.swift`. Run `make check` and "iOS build and tests".

**Depends on**
Nothing.

**Model**
Sonnet: a small additive field on a privacy-sensitive route, held by the existing offline tests.

### {{SIRI-ANSWERS}} feat(ios): Siri and Shortcuts answers for the next flight and tonight's stay

**Context**
On #820 the owner chose these intents. The design is in `docs/design/siri-shortcuts/README.md`, with frames `a-answers.html` and `b-states.html`. The iPhone app keeps the signed-in person's upcoming trips as the raw `GET /api/offline` reply in `ios/Waypoint/OfflineStore.swift`, read through `SavedTrips.read(_:server:)` in `ios/Waypoint/OfflineBridge.swift`. The files have `.complete` file protection, so they can't be read while the phone is locked. Since {{OFFLINE-CITIES}}, each saved trip carries `cities`. The app targets iOS 16.0 (`ios/project.yml`). CI (`.github/workflows/ios.yml`, "iOS build and tests") builds it and runs `WaypointTests` on a simulator.

**Scope**
- `ios/Waypoint/SavedTripsReader.swift`: a `Decodable` read model of the saved copy. It decodes only:
  - trip `id`, `name`, `start_date`, `end_date`, `destination` and the saved trip's `cities`;
  - per booking `id`, `kind`, `status`, `start_local`, `start_zone`, `end_local`, `end_zone`, `origin`, `destination`, `provider`, `details.flight_number`, `details.address` and `details.time_unknown`.

  It does not decode `confirmation`, `manage_url`, `travelers`, any other `details` key or `messages`. It reads through `SavedTrips.read` for `ServerSession.shared.server`.
- `ios/Waypoint/TripAnswers.swift`: pure functions returning an `Answer` (spoken text, card fields, page to open) for "next flight" and "tonight's stay". It also returns the fixed answers for: not signed in, saving off, nothing saved, saved copy unreadable, nothing found, and read failed (locked). The wording is exactly as in the frames.
  - **Times:** the booking's wall-clock time in its own zone, spoken as "local time" after the departure city, never converted.
  - **Next flight:** the next flight on any saved trip (anyone's, the Upcoming rule) that has a time, isn't cancelled and hasn't departed. It is spoken with the departure and arrival cities from `cities`. When a city is missing (a copy saved before {{OFFLINE-CITIES}}), the flight number is spoken instead.
  - **Tonight's stay**, for the tonight phrase: a hotel that isn't cancelled whose nights include today in the hotel's zone (check-in day on or before today, check-out day after it), else the next saved stay.
  - **Check-out**, for the check-out phrase: the stay under way now, from its check-in time until its check-out time, as wall-clock times in the hotel's zone. So on check-out morning it is still that stay until the check-out time. With two under way it is the one that checks out first; past the check-out time, or with none under way, it is the next saved stay.
  - **Both:** the street address is on the card, never spoken.
  - **Telling the phrases apart:** the stay intent takes an `AppEnum` parameter (`tonight`, `checkOut`), and each phrase is bound to its case, so Shortcuts keeps one tile. Confirm in Xcode that an App Shortcut phrase can carry a fixed case. If it can't, use two intents that share `TripAnswers`, and ask the owner about the second tile.
  - **The card** says how old the copy is ("saved 2 hours ago"). The spoken answer doesn't.
- `ios/Waypoint/WaypointIntents.swift`: `NextFlightIntent` and `TonightStayIntent`. Each is an `AppIntent` with `authenticationPolicy = .requiresAuthentication`, returning a dialog and `TripAnswerCard`. `WaypointShortcuts: AppShortcutsProvider` holds the phrases from the design (section 1) unless the owner changes them on #820. Tapping the card opens the app at `#trip/{id}/flight/{segmentId}` or `#trip/{id}`.
- `ios/Waypoint/TripAnswerCard.swift`: the SwiftUI card as the frames show it, once the owner signs it off.
- No network request, and no `IndexedEntity`, Core Spotlight, `IntentDonationManager`, `NSUserActivity` or `AssistantSchemas`.
- Docs: `ios/README.md` ("What is here", "Not built yet") and a "Siri and Shortcuts" section in `docs/src/content/docs/start/ios.md`. They say what each intent answers: from the saved trips only, with the phone unlocked, and what is never spoken.

**Out of scope**
Parking code ({{SIRI-PARKING}}), open my trip ({{SIRI-OPEN-TRIP}}), live flight status (not chosen), location-triggered codes (separate issue), Live Activities, Wallet, widgets, any server change.

**Acceptance criteria**
- [ ] "iOS build and tests" passes, including the new tests.
- [ ] A test puts canary values in `confirmation`, seats, rooms, phone, terminal, travellers and email text, and finds none of them in any spoken text or card field.
- [ ] A test asks the check-out question at 8 am on check-out morning (check-out at 11 am, hotel's zone) and gets that hotel: "You check out of Hotel Example today at 11 am". At 11:01 am it gets the next saved stay, or none. The tonight question keeps its own rule.
- [ ] A test with a failing `URLProtocol` shows that running both intents makes no request.
- [ ] A test reads `authenticationPolicy` as `.requiresAuthentication` for both intents.
- [ ] The card matches the frames the owner signed off on #820. Any change to layout, wording or style needs the owner's sign-off before merge.
- [ ] The pull request lists the device checks from the design's section 4 as not verified, for the owner to run on TestFlight.

**Tests**
Add `ios/Tests/TripAnswersTests.swift`, with fixtures like `TripFixtures` in `ios/Tests/OfflineBridgeTests.swift`. Run "iOS build and tests".

**Depends on**
{{OFFLINE-CITIES}}, and the owner's sign-off on the card's frames.

**Model**
Sonnet: the design and privacy choices are settled on #820, and the rest follows the existing Swift patterns.

### {{SIRI-PARKING}} feat(ios): a Siri and Shortcuts action that opens the parking booking

**Context**
Intent C in `docs/design/siri-shortcuts/README.md`, chosen by the owner on 2026-11-18. A parking booking's QR code is served only by `GET /api/segments/{id}/code` and is never saved on the phone. The web app's booking shows it behind **Show QR code** (`frontend/src/lib/components/GateCode.svelte`).

**Scope**
- `OpenParkingIntent` in `ios/Waypoint/WaypointIntents.swift`:
  - `authenticationPolicy = .requiresAuthentication`, and it opens the app (`openAppWhenRun`).
  - It opens the trip of the current parking booking (entry passed, exit not yet) that isn't cancelled, else the next one, from the saved copy, at `#trip/{id}`.
  - It says "Opening your parking at \<lot\>." and nothing else. The lot is the booking's `origin`, else its `provider`, else "Parking", as `headline` in `frontend/src/lib/trips.ts`.
  - With no parking booking it says "There's no parking in the trips saved on this iPhone."
- Its answer logic goes in `TripAnswers.swift`. Its phrases from the design go in `WaypointShortcuts`.

**Out of scope**
Showing or speaking the code from Siri, saving the code on the phone, location triggers.

**Acceptance criteria**
- [ ] "iOS build and tests" passes.
- [ ] Tests show the spoken text never holds the confirmation or a code, that the intent requires authentication and that it makes no request.

**Tests**
Extend `ios/Tests/TripAnswersTests.swift`.

**Depends on**
{{SIRI-ANSWERS}}.

**Model**
Sonnet: one more intent on the pattern {{SIRI-ANSWERS}} sets.

### {{SIRI-OPEN-TRIP}} feat(ios): "Open my trip to a place" in Siri and Shortcuts

**Context**
Intent D in `docs/design/siri-shortcuts/README.md`, chosen by the owner on 2026-11-18. For one phrase to name a trip ("Open my trip to Grand Junction in Waypoint"), the place must be one of the App Shortcut's parameter values, given to the system with `updateAppShortcutParameters()`. Saves and purges happen in `ios/Waypoint/OfflineSync.swift`.

**Scope**
- `TripEntity` (`AppEntity`) for a saved trip, shown by its destination (else its name) and dates, with an `EntityQuery` that reads only the saved copy.
- `OpenTripIntent` (`authenticationPolicy = .requiresAuthentication`, `openAppWhenRun`):
  - It opens `#trip/{id}` and says "Opening your trip to \<place\>."
  - When two saved trips match, Siri asks which, by their dates.
  - When none matches, it says "There's no trip to \<place\> saved on this iPhone. Opening Waypoint." and opens Upcoming.
- After every save, `OfflineSync` calls `updateAppShortcutParameters()`. The entity query then answers from the new copy. After every purge (sign-out, 401 or 403, saving off, a changed server, no server) the query answers empty and `updateAppShortcutParameters()` is called again.
- Only the saved trips' destinations and names are given to the system, never a booking.

**Out of scope**
Trips outside the saved copy, Spotlight indexing (`IndexedEntity`), donations.

**Acceptance criteria**
- [ ] "iOS build and tests" passes.
- [ ] Tests show the entity query returns only saved trips, returns none after each kind of purge, and calls the parameter update after each save and purge (through an injected hook).
- [ ] Tests show the intent requires authentication and makes no request.

**Tests**
Extend `ios/Tests/TripAnswersTests.swift` and `ios/Tests/OfflineSyncTests.swift`.

**Depends on**
{{SIRI-ANSWERS}}.

**Model**
Sonnet: the privacy rule (replace on save, empty on purge) is settled here, and the tests hold it.

## Open questions for the owner

Decided on 2026-11-18 (see "Owner decisions"): which intents (A, B, C, D), city names, whose flight, and Apple's side. Still open, with the default the frames and drafts use:

1. **Phrases.** Apple needs "Waypoint" in every phrase. Default: the ones in section 1 ("When is my next flight in Waypoint", "Waypoint next flight", "When do I fly in Waypoint", "Where am I staying tonight in Waypoint", "When do I check out in Waypoint", "Waypoint hotel", "Show my parking code in Waypoint", "Waypoint parking", "Open my trip to \<place\> in Waypoint").
2. **The zone in spoken times.** Default: always said, as "local time" after the departure city. Leave it out when the place is in the phone's own zone?
3. **The stay's street address.** Default: on the card, never spoken. Name and city only?
4. **An old copy.** Default: the age is on the card only. Should the spoken answer say "as of Monday" too?
5. **Version of the saved copy.** {{OFFLINE-CITIES}} keeps `version` 1 because the field is additive, and a bump would stop every not-yet-updated app from saving. Bump to 2 anyway?
6. **The look of the frames** (`a-answers.html`, `b-states.html`): not signed off yet.
