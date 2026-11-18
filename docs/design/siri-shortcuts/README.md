# Siri and Shortcuts in the iPhone app: exploration for the owner to choose from

Exploration for [#820](https://github.com/AnthonyPluth/Waypoint/issues/820). Nothing here is built, and nothing is signed off: the owner picks which intents to build, in chat, before any build issue is opened. The open questions at the end are what needs an answer. The mock frames are self-contained HTML pages (vector only, no raster images, dark only, phone width 390 px only), using Waypoint's tokens from `frontend/src/app.css` and adding none. Every trip, hotel, flight and time in them is made up. The system parts of each frame (Siri's glow, the unlock prompt, the Shortcuts app) are drawn roughly, only to place Waypoint's card; Apple draws them, not us.

| Screen | File | What it shows |
| --- | --- | --- |
| a | [a-answers.html](a-answers.html) | The two recommended intents answered on an unlocked phone: next flight (later this week, today, across zones), tonight's stay and its check-out phrase, and how the two appear in the Shortcuts app |
| b | [b-states.html](b-states.html) | What the same intents say when they can't answer: phone locked, not signed in, saving switched off, nothing saved yet, a copy that can't be read, no flight or stay in the saved trips, and a saved copy that is days old |

Owner context (2026-11-18): interested in Siri; no Live Activities; doesn't want clutter.

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
| A | **Next flight** | "When is my next flight in Waypoint", "Waypoint next flight", "When do I fly in Waypoint" | "Your next flight, EA 214, leaves Thursday at 7:40 AM, Denver time." Today: "Your flight, EA 214, leaves today at 7:40 AM, Denver time, in 3 hours." | Card: flight number, `DEN → GJT`, departs and arrives as wall-clock times with each airport's zone, the trip name, "Booked times · saved 2 hours ago". Tap opens `#trip/{id}/flight/{segmentId}`. |
| B | **Tonight's stay** (also answers "when do I check out") | "Where am I staying tonight in Waypoint", "When do I check out in Waypoint", "Waypoint hotel" | "Tonight you're staying at Hotel Example in Grand Junction. You check out Sunday at 11 AM." Check-out phrase: "You check out of Hotel Example on Sunday at 11 AM." | Card: hotel name and city, the street address (on screen only), check-in and check-out with the hotel's zone, nights. Tap opens `#trip/{id}`. |
| C | **Parking code** | "Show my parking code in Waypoint", "Waypoint parking" | "Opening your parking at Lot Example." Never the code, never the confirmation. | Opens the app at the parking booking, where the existing **Show QR code** button is. The QR code comes from the server (`GET /api/segments/{id}/code`) and is never saved on the phone, so with no connection the booking opens without it. |
| D | **Open my trip to a place** | "Open my trip to \<place\> in Waypoint", "Waypoint open \<place\>" | "Opening Grand Junction." | Opens `#trip/{id}`. \<place\> is a trip from the saved copy, matched by its name or destination. |
| E | **Live flight status** (as asked: "is my flight on time") | "Is my flight on time in Waypoint" | "EA 214 is delayed 35 minutes; it now leaves at 8:15 AM, Denver time." | Card like A with the status pill. Needs the server (below). |

"When do I check out?" is folded into B, not a separate intent: one intent that answers both, behind two phrases, gives the same answers with one tile less in Shortcuts. The issue's five candidates are A, B (twice), C and D; E is listed because a person asking about their flight will expect it, and it is where the server comes in.

## 2. From the saved trips alone, or the server

| Intent | Saved copy alone | Needs the server |
| --- | --- | --- |
| A Next flight | Yes: the next timed, not-cancelled flight in the saved trips, from its booked times (the same rule as Upcoming's next flight). Untimed flights (`details.time_unknown`) are skipped. A flight in a trip further out than the saved window isn't seen, so the answer says "in the trips saved on this iPhone" when there is none. | Nothing, unless E is added to it. |
| B Tonight's stay | Yes: a not-cancelled hotel whose nights include tonight (tonight is today in the hotel's own zone); check-out is its `end_local`. With no stay tonight it names the next saved stay. | Nothing. |
| C Parking code | Finding the parking booking: yes. | The QR code itself, as today, once the app is open. |
| D Open my trip | Yes: the saved trips' names and destinations. A trip outside the saved window can't be named by voice (the app could still open it online). | Nothing. |
| E Live status | No: live status is never saved, and the gate is never in the copy. | `GET /api/flight-status` with the app's token, a native request the app doesn't make today. It sends nothing new to the server (the server already holds the booking and the status), but it is a new request at a new moment, which the issue rules out ("nothing new is sent to the server") unless the owner decides otherwise. |

## 3. Privacy, per intent

The rules for every intent:

- **Locked phone: every intent that reads trips asks for the phone to be unlocked first.** Each one sets `authenticationPolicy = .requiresAuthentication`, so Siri shows the system's unlock prompt before Waypoint runs, and nothing is said or shown until it is unlocked. That is not only a choice: with `.complete` file protection the app can't read the saved trips while the phone is locked. If it is ever asked to (a race at the moment of locking), the read fails and the answer is "Unlock your iPhone to see your trips in Waypoint", with no trip in it. The same applies with AirPods or CarPlay while the phone is locked: Siri asks for an unlock, and Waypoint says nothing first. Siri on a HomePod, which can't unlock the phone, gets no answer at all.
- **What is never spoken:** a confirmation code or record locator, a gate, a loyalty or Known Traveler number (never in the copy anyway), a parking code, a seat, a room number, a phone number, a street address, an email's subject or text, other travellers' names. What can be spoken: the flight number, the day and time with the zone's name, the hotel's name and city, the trip's name. A spoken answer can be heard by anyone nearby, so it says only what a person needs to act on.
- **What is never on the card**, though the phone is unlocked: a confirmation code, a gate, the QR code, loyalty and Known Traveler numbers, a seat or room number, email text. The card is a glance, not the booking: the app (one tap) shows the rest, behind its own screens as today. The street address of a stay is on B's card; a seat could be added to A's once the app knows whose seat is whose (open question 4).
- **Only the signed-in person's saved trips.** An intent reads only `OfflineStore` for the server in `ServerSession.shared.server`, the same folder the bridge reads, and only while that session exists. Signed out, there is no copy (sign-out deletes it) and no answer: "Sign in to Waypoint on this iPhone first." The copy holds only trips that person may see (`domain/offline.py`, through `visibility`), so nothing else can be answered.
- **Nothing new sent to the server, and nothing to anyone else.** A, B, C and D make no network request: the answer code takes the saved copy and the clock and has no `ServerClient`. C and D open the app, which then does what it does on any open (load the server, refresh the copy). E is the one exception and is not recommended.
- **Nothing handed to the system's indexes.** No `IndexedEntity` or Core Spotlight items, no `IntentDonationManager` donations, no `NSUserActivity` carrying a trip, and no Apple Intelligence schemas (`AssistantSchemas`), so trip names, places and times are not put into Spotlight's index or Siri's suggestions. The App Shortcuts themselves (the phrases and the action names) do show in Spotlight and Shortcuts; they hold no trip data. D is the exception that would hand data over: a voice phrase with a trip in it needs the trip names given to the system (`updateAppShortcutParameters()`), on the phone, and cleared on every purge. That is one reason D is not in the first set.
- **Apple's side, to confirm on a device.** Siri turns speech into text on the phone for most requests on recent iPhones, but Apple says some requests are sent to its servers, and a person who opted into "Improve Siri & Dictation" shares audio with Apple. Whether the dialog text an App Intent returns (the spoken answer) leaves the phone is not stated in anything read for this note: **confirm**. That is a second reason to keep the spoken answer to the flight number, a day, a time and a hotel's name.

Per intent:

| Intent | Locked phone | Spoken | On the card |
| --- | --- | --- | --- |
| A Next flight | Unlock first | Flight number, day, time, zone's name | Flight number, airport codes, times with zones, trip name, how old the copy is |
| B Tonight's stay | Unlock first | Hotel name, city, check-out day and time | Hotel name, city, address, check-in and check-out with zone, nights |
| C Parking code | Unlock first (it opens the app) | "Opening your parking at \<lot\>" | Nothing: the app opens |
| D Open my trip | Unlock first (it opens the app) | "Opening \<trip\>" | Nothing: the app opens |
| E Live status | Unlock first | As A, with the delay; never the gate | As A, with the status pill; never the gate |

## 4. How it is built and tested

**Where the code goes.** In the app target, `ios/Waypoint/`, not an App Intents extension: an extension runs in its own process and would need the saved trips moved to an App Group container, which changes where the copy lives (the promises name the app's own private storage). Intents in the app target run in the app's process, in the background unless they open the app.

- `SavedTripsReader.swift`: decodes the saved copy into a small read model of only what the intents use (trip id, name, dates; per booking id, kind, status, start and end with zones, origin, destination, `provider`, and from `details` only `flight_number`, `address` and `time_unknown`). It never decodes `confirmation`, `manage_url`, `travelers`, seats, rooms, phone numbers or the emails, so they can't reach an answer by accident. It reads through `SavedTrips.read(_:server:)`, like the bridge.
- `TripAnswers.swift`: pure functions from that model, the clock and the phone's time zone to an `Answer` (the spoken text, the card's fields and the page to open), plus the fixed answers for locked, signed out, saving off, nothing saved and nothing found. No `URLSession`, no `ServerClient`, no Keychain.
- `WaypointIntents.swift`: the `AppIntent`s and the `AppShortcutsProvider`, thin wrappers that read the session, call `TripAnswers` and return its dialog and card. Opening the app at a page sets the web view's address (as `ShellViewController.serverURL` does at launch), with `#trip/{id}`.
- `TripAnswerCard.swift`: the SwiftUI card.
- `ios/README.md`'s table and "Not built yet", and `docs/src/content/docs/start/ios.md`, get a "Siri and Shortcuts" section saying what each intent answers, that it needs the phone unlocked and that it answers from the saved trips only.

**Unit tests (CI can run these)**, in `ios/Tests/TripAnswersTests.swift`, with fixtures like `TripFixtures` in `OfflineBridgeTests.swift` (made-up trips, a fixed `now`, a fixed calendar):

- Next flight: the next timed flight, skipping cancelled, untimed and past ones; a flight today versus later this week; times read as wall-clock times in the flight's own zone (a fixture where the phone's zone differs, and one across a date line), never converted; the zone named in the spoken text.
- Tonight's stay: tonight inside the stay, the last night, check-out morning, no stay tonight with a later one, none at all; the check-out phrase's answer.
- The empty states: no session, saving off, nothing saved, an unreadable copy, a copy for another server, a read that fails as if locked: each answers its fixed text and holds no trip data.
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

## 5. Recommendation: the smallest first set

**A (next flight) and B (tonight's stay, which also answers check-out).** Two actions, four phrases, two tiles in Shortcuts.

- Both answer from the saved trips alone, with no network, so they work in the air and at a hotel with bad Wi-Fi, which is when they are asked.
- Both need the phone unlocked and speak only a flight number, a day, a time and a hotel's name.
- Neither hands trip data to Spotlight or Siri's suggestions.
- They are the two questions a traveller asks most, and the one card each says what the person needs at a glance; everything else is one tap away in the app.

Not in the first set:

- **C, parking code**: it is only "open the app at the parking booking", and the code needs the server, so at a gate with no signal it opens a booking without its code. Worth it once location-triggered codes (separate issue) settle how the code reaches the phone.
- **D, open my trip**: it needs the trip names given to the system for the voice phrase, and kept in step with every purge; Upcoming already opens on the trip under way.
- **E, live status**: it needs the server, which the issue rules out for now.

## Draft build issues

Not opened. These are for after the owner picks; the bodies follow the `fleet-agent-task` sections. The model is Sonnet, per `CLAUDE.md`'s routing and the issue's own Model line (the open privacy choices are made here, by the owner). Each needs the owner's sign-off on the card's design (the frames here, once the owner answers) before merge.

### {{SIRI-ANSWERS}} feat(ios): Siri and Shortcuts answers for the next flight and tonight's stay

**Context**
The owner chose, on #820, to build Siri answers for the next flight and tonight's stay (design: `docs/design/siri-shortcuts/README.md`, frames `a-answers.html` and `b-states.html`). The iPhone app keeps the signed-in person's upcoming trips as the raw `GET /api/offline` reply in `ios/Waypoint/OfflineStore.swift`, read through `SavedTrips.read(_:server:)` in `ios/Waypoint/OfflineBridge.swift`, with `.complete` file protection (unreadable while the phone is locked). The app targets iOS 16.0 (`ios/project.yml`); CI (`.github/workflows/ios.yml`, "iOS build and tests") builds it and runs `WaypointTests` on a simulator.

**Scope**
- `ios/Waypoint/SavedTripsReader.swift`: a `Decodable` read model of the saved copy with only trip `id`, `name`, `start_date`, `end_date`, and per booking `id`, `kind`, `status`, `start_local`, `start_zone`, `end_local`, `end_zone`, `origin`, `destination`, `provider`, and `details.flight_number`, `details.address`, `details.time_unknown`. It does not decode `confirmation`, `manage_url`, `travelers`, any other `details` key or `messages`. It reads through `SavedTrips.read` for `ServerSession.shared.server`.
- `ios/Waypoint/TripAnswers.swift`: pure functions returning an `Answer` (spoken text, card fields, page to open) for "next flight" and "tonight's stay", and the fixed answers for: not signed in, saving off, nothing saved, saved copy unreadable, nothing found, read failed (locked). Wording exactly as in `docs/design/siri-shortcuts/b-states.html`. Times are the booking's wall-clock time in its own zone, spoken with the zone's name ("Denver time", from the IANA id), never converted. Next flight: the next flight with a time that isn't cancelled and hasn't departed. Tonight's stay: a hotel that isn't cancelled whose nights include today in the hotel's zone; else the next saved stay. The card says how old the copy is ("saved 2 hours ago").
- `ios/Waypoint/WaypointIntents.swift`: `NextFlightIntent` and `TonightStayIntent` (`AppIntent`, `authenticationPolicy = .requiresAuthentication`, returning a dialog and `TripAnswerCard`), and `WaypointShortcuts: AppShortcutsProvider` with the phrases the owner chose on #820. Tapping the card opens the app at `#trip/{id}/flight/{segmentId}` or `#trip/{id}`.
- `ios/Waypoint/TripAnswerCard.swift`: the SwiftUI card as the frames show it.
- No network request, no `IndexedEntity`, Core Spotlight, `IntentDonationManager`, `NSUserActivity` or `AssistantSchemas`.
- `ios/README.md` ("What is here", "Not built yet") and `docs/src/content/docs/start/ios.md` (a "Siri and Shortcuts" section): what each answers, from the saved trips only, with the phone unlocked.

**Out of scope**
Parking code, open my trip, live flight status (#820 keeps them for later), location-triggered codes (separate issue), Live Activities, Wallet, widgets, any server change.

**Acceptance criteria**
- [ ] "iOS build and tests" passes, including the new tests.
- [ ] A test feeds canary values in `confirmation`, seats, rooms, phone, terminal, travellers and email text and finds none in any spoken text or card field.
- [ ] A test with a failing `URLProtocol` shows that running both intents makes no request.
- [ ] A test reads `authenticationPolicy` as `.requiresAuthentication` for both intents.
- [ ] The card matches the frames the owner signed off on #820; any change to layout, wording or style needs the owner's sign-off before merge.
- [ ] The pull request lists the device checks from the design's section 4 as not verified, for the owner to run on TestFlight.

**Tests**
Add `ios/Tests/TripAnswersTests.swift` (fixtures like `TripFixtures` in `ios/Tests/OfflineBridgeTests.swift`); run "iOS build and tests".

**Depends on**
The owner's choice on #820.

**Model**
Sonnet: the design and privacy choices are settled on #820; the rest follows the existing Swift patterns.

### {{SIRI-PARKING}} feat(ios): a Shortcuts action that opens the parking booking (only if the owner picks C)

**Context**
Intent C in `docs/design/siri-shortcuts/README.md`. A parking booking's QR code is served only by `GET /api/segments/{id}/code` and never saved on the phone.

**Scope**
- `OpenParkingIntent` in `ios/Waypoint/WaypointIntents.swift`: `authenticationPolicy = .requiresAuthentication`, opens the app (`openAppWhenRun`) at the current or next not-cancelled parking booking in the saved copy; says "Opening your parking at \<lot\>." and nothing else; with none, "There's no parking in the trips saved on this iPhone."
- The phrases the owner chose on #820, in `WaypointShortcuts`.

**Out of scope**
Showing or speaking the code from Siri, saving the code on the phone, location triggers.

**Acceptance criteria**
- [ ] "iOS build and tests" passes; tests show the spoken text never holds the confirmation or a code, and the intent makes no request.

**Tests**
Extend `ios/Tests/TripAnswersTests.swift`.

**Depends on**
{{SIRI-ANSWERS}}.

**Model**
Sonnet: one more intent on the pattern {{SIRI-ANSWERS}} sets.

## Open questions for the owner

1. **Which intents to build first?** The recommendation is A (next flight) and B (tonight's stay with check-out). Add C (parking), D (open my trip) or E (live status)?
2. **Phrases.** Apple needs "Waypoint" in every phrase. Which do you want: "When is my next flight in Waypoint", "Waypoint next flight", "Where am I staying tonight in Waypoint", "When do I check out in Waypoint", others?
3. **The zone in spoken times.** Always say it ("7:40 AM, Denver time"), or leave it out when the place is in the phone's own zone? The card always shows it.
4. **Whose flight.** Upcoming's next flight is anyone's on a trip you're on. Should Siri's be only flights you're a traveller on? That needs the app to know who "you" are (your `person_id`, which the saved copy doesn't carry today, so the server's `GET /api/offline` would add it).
5. **Flight number aloud, or places?** The copy has airport codes, not cities, so the proposal speaks the flight number and the zone's name. Speaking "to Grand Junction" would need city names added to the saved copy (a server change).
6. **The stay's street address on the card** (never spoken): keep it, or name and city only?
7. **An old copy.** When the copy is more than a day old, should the spoken answer say so ("as of Monday"), or only the card?
8. **Apple's side.** Is it acceptable that Siri, not Waypoint, handles the spoken request and answer, with what Apple's Siri settings say about that (to be confirmed on a device)?
