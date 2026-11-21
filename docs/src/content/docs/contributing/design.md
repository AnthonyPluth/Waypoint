---
title: Design
description: The dark-only design foundation, status colours, kind tiles, avatar stacks, and the shared chip, airport code and route line.
sidebar:
  order: 2
---

Waypoint is dark only. There is no light palette and no theme setting. Lint rejects a `dark:` variant, a light palette and `prefers-color-scheme` in `frontend/` (and `make fleet-checks` rejects them in the static files), so a new screen never needs to think about themes.

The specimen page at `#design` (Settings, then Design) shows everything below on one screen. `make verify` captures it at phone and desktop widths: `poetry run python run.py verify design`.

## Tokens

Tokens live in `frontend/src/app.css`: one `:root`, then `@theme inline` to expose them to Tailwind.

- **Surfaces**: the page is `#0d0c12` (`bg-background`) and a card is raised slate `#1a1922` (`bg-card`; the owner chose “option A, raised slate” on 2026-11-21 because black cards faded into the page). The top header strip of a card that has its own surface, the “Next up” band of the pass card, is `#201f2a` (`bg-card-header`), and secondary buttons and fills inside cards (`--secondary`, `--muted`, `--accent`, `bg-surface-3`) are `#262531`. `bg-surface-1`, `bg-surface-2` and `bg-surface-3` raise from there, with `shadow-elevation-1`, `-2` or `-3`. `--border` is the hairline `#2e2d38`; cards in the clean and bold look carry no border or shadow, but `--shadow` and `--elevation-*` stay until each component is rebuilt.
- **Text**: `text-foreground` is white, `text-muted-foreground` the secondary grey (`#a9a8b2`) and `text-label` the grey for small uppercase labels (`#8f8e98`).
- **Colour rules**: blue (`--primary`, `#3d8ef7`) is live, now and the one primary action; green (`--success`, `#4cc38a`) is confirmed, on time and good news; amber (`--signal`, `#eba43b`) is changed or needs attention. They feed `status-{ok,warn,bad,info,quiet}-soft` (the background) and `-ink` (the text); use those through the chip, not by hand.
- **Kind colours**, used as the icon stroke: flight `#4f9dff`, stay `#38c6d9`, car `#f4d35e`, train `#c79bff`, cruise `#ff8fab`. Flight and car have values of their own, so a status change no longer moves them, and the car colour and the stay colour are never a status colour (a test holds it).
- **Radius**: `rounded-hero` (30 px) for the flight hero card and `rounded-booking` (24 px) for booking cards. `--radius` is unchanged for everything else.
- **Type scale**: `text-display` (40 px, weight 800; `text-display-lg` is 64 px on desktop), `text-hero-fact` (34 px; `-lg` 44 px), `text-airport` (36 px; `-lg` 44 px), `text-fact` (22 px; `-lg` 26 px), `text-fact-card` (17 px), `text-title`, `text-heading`, `text-body`, `text-caption` and `text-eyebrow` (11 px, weight 600, uppercase, 0.09em). Each sets size, line height, letter spacing and weight.

Every status ink meets WCAG AA (4.5:1) on its soft colour, the card and the page background; the white text and the secondary and label greys meet 4.5:1 on the page, the card, its header strip and the secondary fill, and every kind colour 3:1 on the card. `src/app.css.test.ts` parses the tokens and fails if a change breaks that.

## Status chips

`frontend/src/lib/status.ts` maps state to a chip; `StatusChip.svelte` draws it.

| Source | States | Tone |
| --- | --- | --- |
| Booking (only for an exception) | Changed / Cancelled | warn / bad |
| Live (only when live flight status is on) | On time / Delayed N min / Departed | info / warn / info |
| | Landed | quiet |
| | Cancelled / Diverted | bad |

`bookingChip(status)` always returns a chip, and the Design page lists all three. `segmentChips(status, flight, liveOn)` returns both, with `booking` null for a confirmed booking (a confirmed booking is the expected state, so `PassCard` shows no chip for it and leaves no gap) and `live` null when live status is off or there is no flight status. The booking chip leads; the live chip is the smaller one.

## Airport code

`AirportCode.svelte` shows an IATA code in the monospaced display face, at `large`, `medium` or `small`. Pass `name` and the code renders as an `<abbr>` with the airport name as its title.

## Route line

`RouteLine.svelte` draws the origin, the destination and an arched dashed line between them, with a plane riding the arc at `progress`, from 0 (departure) to 1 (arrival).

- The arc is a quadratic curve in a stretched SVG, so x is linear in progress and the plane’s height is `1 − 2t(1 − t)` of the box. The plane tilts up on the way out and down on the way in.
- Out-of-range or missing values clamp to 0 and 1 (`clampProgress`).
- Progress comes from the booked times, so the line needs no live data.
- Pass `label` to give the line an accessible description; otherwise it is hidden from assistive technology.

## Booking card

`BookingCard.svelte` is the card for a stay, car, train, cruise, parking booking or past visit on a trip that is not over (`pages/Trip.svelte`). The design is `docs/design/clean-and-bold/` (#876, #878); the card is built in #882.

- A raised slate card (`bg-card`) with 24 px corners and no border or shadow. The header row is the tap target (at least 64 px): a button with `aria-expanded` and `aria-controls` that expands the card in place (one card open at a time, focus staying on the button) to show the booking’s detail, `BookingDetailBody.svelte`, the body `BookingDetail.svelte` shows in its sheet on a completed trip and on Upcoming (#924).
- The header: the kind icon as a coloured outline with no chip (`KindTile` with `outline`), the name in bold, a grey line such as “Stay · Alfama” or “Train · Sat, Mar 13” ending in an amber “Changed” or “Cancelled” only when the booking is one of those (a confirmed booking shows no status word), and a chevron that turns over when the card is open.
- Three label-over-value facts from `cardFacts` in `frontend/src/lib/trips.ts`: stay Check-in, Nights, Check-out; car Pick-up, Days, Return; train Departs, From, Arrives; cruise Embarks, Nights, Disembarks; parking Entry, Days, Exit; visit From, Days, To. The mockup words Nights, Days, Return and From sit beside today’s `START_WORD` and `END_WORD`. Times are in Geist Mono.
- “Show code” is the one blue button, on a parking booking that has a QR code and has not ended (`showsCode` in `gate-code.ts`, the rule `GateCode` uses), and nowhere else.
- No confirmation code, cost, address, traveller or loyalty number is on the card. They are in the detail, with the actions (booking link, directions, call, the email, Edit, Move, Remove), which `Trip.svelte` passes to `BookingDetailBody` as its `above` and `below` snippets while the trip is not over, with Edit and **More** (Move, Remove) at the foot of the open card for a trip that is not Done.

`PassCard.svelte` is still the card for flights `FlightCard` does not draw (cancelled, or with no time recorded), for the Upcoming page’s next booking and day list, for the offline trip and for this design page.

## Pass card

`PassCard.svelte` is the one card for a booking you are planning or checking in for, with a variant for each kind (flight, hotel, car, train, cruise). Top to bottom:

- a headline line;
- the confirmation code as the largest element (the first focusable control, tap to copy);
- the flight, its date and departure time, and the booking link;
- the airport codes with the route line and the times at each airport;
- below the tear line, the terminal, gate, seat and cabin, the booking chip (only when the booking is changed or cancelled) and, when live flight status is on, the live chip and a quiet line.

The headline, the plane and the Next up card follow set rules:

- **Headline.** It comes from `passHeadline(segment, now, live, online)` in `frontend/src/lib/trips.ts`.
  - A terminal live status (landed, cancelled, diverted) always wins, at any age. Any other live status wins only while fresh (`flightEvidence`): “Delayed … min, …”, “Departed, expected to arrive in …”, “Diverted”, “Landed” and “Cancelled by the airline” (red).
  - Without live status, or when it is older than `LIVE_STALE_HOURS`, or when the device is offline, the clock decides. A flight reads “Check-in opens in …” until `CHECK_IN_WINDOW_HOURS` before departure, then “Check-in is open, departs in …”, then “Under way, arrives in …”, then “Landed”. A cancelled booking reads “Cancelled”.
- **Plane.** A flight’s plane comes from `flightProgress(segment, now, live, online)`, which reads the same evidence as the headline. Without fresh live status it is `routeProgress(segment, now)`: `(now − departure) ÷ (arrival − departure)` on the segment’s instants, clamped to 0–1, and 0 for a segment with no times. With a fresh “delayed” status that has no actual departure, or an actual or estimated departure still ahead, it sits at the start whatever the booked times say. Once departed it runs from the actual (or estimated) departure to the estimated arrival (the booked arrival when none), held short of the end (`AIRBORNE_MAX`) until the status says landed; a diverted flight is held the same way. Live “landed” moves it to the end and live “cancelled” parks it at the start. Trains and cruises keep `routeProgress`.
- **Layout.** `RouteLine` spans the full width between the two airport codes. The airports’ city and name sit in a row of their own beneath, wrapping within each side, so they never narrow the line. The card carries no “Based on schedule” label.
- **Next up.** The Next up card on Upcoming is chosen by `nextUp` in `frontend/src/lib/trips.ts`, in this order:
  1. a flight, train, cruise or visit that is under way (earliest start first);
  2. otherwise the booking that starts soonest;
  3. otherwise, when only background reservations remain, the hotel, rental car or parking booking that ends soonest.

  Hotels, rental cars and parking are background reservations: while one is under way and something else is still ahead, it never takes the card. It appears under “Also under way”, soonest end first, with its check-out, drop-off or exit time, and opens like any booking (QR code included). Ties break by segment id. Times are compared as instants from each place’s own zone, across every trip the person can see.
- **Times.** They are the wall-clock times at each place, as stored, and are never shown in the viewer’s own zone.
- **Boarding card.** On the Next up (boarding) card a flight draws the same arched `RouteLine` as the standard card, with the plane at `flightProgress` (the booked times without live status: at the start before departure, at the end once the arrival has passed). A train keeps a straight line with a train icon. A cruise keeps a straight dashed line with the ship tile at `shipLeft(shipProgress(segment, now))`: `routeProgress`, or 0 for a cancelled cruise, placed by `calc((100% - 2.25rem) * progress)` so the tile and its card-coloured padding stay inside the line (left edge at 0, right edge at 1); the line carries `data-progress` and the tile `data-ship`, and nothing animates. Behind the ship a solid `border-kind-cruise` segment (`shipTrail`, from the line’s start to the middle of the tile, `aria-hidden`, absent at progress 0) covers the dashed grey line, as the flight’s travelled path does in `--primary`. A stay, car, parking booking or visit keeps its centered tile. The departure and arrival times sit side by side on one row at every width (two equal columns), each with the time, then the day, then the zone’s city (“New York time”) on lines of their own, so a phone as narrow as an iPhone 17 Pro Max (440 px) never wraps them onto two rows.
- **Data.** The card does not read the API for gate or city: a gate shows only from live flight status, and the airport name is not shown.

## Flight card

`FlightCard.svelte` is the card the next flight has on the trip page while its trip isn’t over; every other booking there is a `BookingCard`, and a flight on a trip that is over keeps the pass card. The design is `docs/design/flights/a-flight-card.html`, signed off on #666. `flightCardView` in `frontend/src/lib/flightcard.ts` works out everything it shows from the segment, the flight’s live status (if any) and the clock, so the component only draws:

- **State.** Live evidence (`flightEvidence`) gives landed, cancelled, diverted, delayed and in the air; with none, the booked times decide in the air and landed, and Boarding is a status with a gate within `BOARDING_MINUTES` (40) before departure, because the status service folds boarding into scheduled. With no live status at all and a departure more than `LIVE_STATUS_STARTS_DAYS` (1) away, the card has no pill and says when live status starts.
- **Facts.** Four, each with a source: Terminal and Gate from live status (the booking’s own terminal when live status has none), Seat and Cabin from the booking; the arrival side (Terminal, Gate, Belt) in the air and once landed. The status has no belt, so Belt is a dash. An unknown value is a dash with the hidden text “Not known yet”, never a missing row.
- **Times.** Wall-clock times at their airport with the zone, never converted; a delay shows the booked time struck through above the new one, read as “Originally …”. The accessible name of the article is built in the same function.

### The hero card

`FlightHero.svelte` draws the clean and bold hero card for all eight states, to the frames in `docs/design/clean-and-bold/` (`e-flight-states.html`, `k-travellers-connection.html`). `FlightCard.svelte` (trip page) and `FlightHome.svelte` (Upcoming) are thin wrappers around it; `heroView` in `frontend/src/lib/flighthero.ts` turns the `flightCardView` into the words, and `FlightArc` draws the route with `hero`.

- **Top line.** The carrier and flight number in plain grey text, never a logo or a mark tile. At the right, one fact: the blue countdown (“In 3 days”) or the blue “Boarding” with a dot, the amber “Delayed”, “Cancelled” or “Diverted” pill, the blue time left with a plane in the air, or the green “7 min early” (“On time” green, “N min late” amber) once landed.
- **Sentence, big fact, quiet line.** “Your flight to Lisbon”, “Boarding now, to Lisbon”, “In the air to Lisbon”, “You are in Lisbon” or “Diverted to Porto” over “Departs 6:10 AM”, “Lands 10:55 PM”, “Landed 10:48 PM” or “Cancelled”; then one quiet line: the date and a green “on time”, “45 min late · was 6:10 AM” with the old time struck through, “Updated 9 minutes ago”, “Times from your booking” (with “Live status starts 1 day before.” when the flight is more than a day away with no status), “Contact … about rebooking.”, or “Was headed to Lisbon”.
- **Route.** The airport codes in Geist Mono (`font-mono`) at weight 800 with a dotted arc between them; the plane is blue at the origin and along the arc with the travelled part solid blue, and white at the destination once landed; a cancelled flight has no plane and grey, struck times. Under each code, its time (amber when changed, with the booked time struck above it) and its zone on its own line. A diverted flight shows the new airport with the booked one struck above it.
- **Facts.** One hairline, then three label-over-value facts, left, centre and right: Terminal, Gate and Seats before departure; Arrival term, Arrival gate and Bag claim from take-off. An unknown value is a dash with the hidden text “Not known yet”. Seats list each seat, or the first with “+N” from three. On the trip page, when travellers are shown, a row lists each traveller beside their seat.
- **Detail row.** A last row “Confirmation, travellers and price” shows the booking’s detail: on the trip page it expands in place under the card, like a `BookingCard` (`aria-expanded`, `aria-controls`); on Upcoming it opens `BookingDetail` in a sheet. On Upcoming it holds what the card’s footer used to: the confirmation codes with their copy buttons, the travellers, the cost (when costs are shown), Show QR code and Open trip, as the `above` snippet and rows of `BookingDetail` (`canChange` off there: no Edit, Move or Remove). The card’s footer keeps only the airline action, Directions, Call and the times-differ note, and is not drawn when none applies. A tap on the card still opens the live status.
- **Colour.** Blue is live, now and the primary action; green is confirmed, on time and good news; amber is changed or needs attention. Nothing else on the card is coloured.
- **Type and edge.** Airport codes (the struck booked one of a diverted flight too), times (the big fact’s, the struck old departure) and seat values are `font-mono`, Geist Mono, as “Monospace type” below says; the labels, the sentence and the other facts are Inter. The card is raised slate (`bg-card`) with 30 px corners and no border and no shadow, like the booking cards; a highlighted card keeps its focus ring.
- **A connection.** On Upcoming and on the trip page’s Next up card, when the next flight is one leg of a journey the server linked (`segment.journey`, below), the hero follows frame k in two moments and nowhere else: before the first leg (still scheduled) and during the connection (the leg you are on is scheduled and the leg before it has landed). The codes are the whole journey (BOS to LIS) with each stop a dot on the arc and “1 stop, JFK” under it (“2 stops, JFK, LIS”); the carrier line, the big fact, the facts and the seats stay the leg you are on, and the destination time is the last leg’s, in its own zone. Before the first leg a hairline and **Then, at JFK** name the next leg: its number, its departure time (amber when that leg is delayed), its terminal when known and the time to connect (“2 h 12 min to connect”, amber and bold under 45 minutes, the owner’s accepted suggestion on frame k). During the connection the sentence is “Your connection to Lisbon”, the top line “Departs in 1 h 50 min”, the quiet line “Leg 2 of 2” with the usual “on time”, the plane waits at the stop with the travelled part blue and “At JFK” under the arc, and **Earlier** names the leg before (“AU 1402 landed at JFK 7:28 AM”). Every other state of every leg (boarding, delayed, in the air, landed, cancelled, diverted), a cancelled or diverted leg anywhere in the journey, a saved copy with no `journey`, and the compact booking cards keep what they were. `connectionStage` and `overConnection` in `flighthero.ts` decide and write it; `journeyLegs` in `lib/journey.ts` walks the linked legs.
- **How legs are linked.** On the server, in `link_journeys` (`waypoint/domain/trips.py`), and returned as `journey` (`{lead, leg, legs, previous, next}`, the ids being each leg’s first live booking) on every segment of a linked flight in the trip and segment replies, the saved copy of `GET /api/offline` included; nothing is stored, so edits, moves and merges stay right. Two flights are consecutive legs when they are live (not cancelled), timed, in one trip, the next one leaving the airport the first landed at, less than 24 hours after it landed (both instants taken in each leg’s airport zone, never the stored wall-clock values), and every booking of the one flight card has a booking with the same company and confirmation code on the other, and the other way round. A round trip on one code is therefore two journeys, and separate reservations are not linked. It is computed only from the segments the viewer’s visibility helper returned, and carries no confirmation code.

## Trip page

`pages/Trip.svelte` assembles the page of a trip that is not over (`PastTrip.svelte` keeps a trip that is over), to the frames in `docs/design/clean-and-bold/` and the build issue #883:

- **Header.** The back link (only when the page is not beside the Trips list) and, at the right, the pencil that opens `TripDetails` (`bare`, as `PastTrip` uses it) and **Trip options** (`tripOptions`: Add a booking, Merge another trip, Delete trip). Under it the trip’s name in `text-display` (`text-display-lg` from a 52 rem page), the dates and destination, `TripSummary` as facts, and a neutral `AvatarStack` where `showTripTravellers` allows it. The trip total, notes and the offline status follow.
- **Next up and Then.** `nextUp([trip], now)` picks the booking for the hero: a flight is `FlightCard` with its travellers on the hero’s rows and its last row opening the detail; any other kind (today’s rendering until the owner decides otherwise, #878 point 11) is its `BookingCard`. Every other card, a cancelled or untimed flight included, is a `BookingCard` in date order under a **Then** label, and the footer line holds the booking count and **Add booking**.
- **Columns.** The page is a container; from 52 rem wide (`@[52rem]`) **Next up** and **Then** sit side by side, and below it they stack. `layout.wide` gives the page the 80 rem width cap a completed trip has, while it is not beside the Trips list.
- **Booking detail.** On a trip that is not over, a booking’s detail expands inside its card (one at a time; the hero flight’s last row does the same) and is `BookingDetailBody`, with the action row, the itinerary and loyalty numbers added; a link to one booking opens that card expanded. A completed trip, and the Upcoming page’s hero, still open the same body in the `BookingDetail` sheet.
- **Not drawn.** A connection between two flights (#903).

## Live status view

`pages/FlightStatus.svelte` is the page for one flight at `#trip/<trip id>/flight/<segment id>` (`route.rest` holds what follows the trip id, and `pageFor(route.page, route.rest)` in `frontend/src/lib/nav.ts` maps it to the page; `App.svelte` gives it the 960 px column). The design is `docs/design/flights/b-live-status.html`, signed off on #666. It loads the trip with `GET /api/trips/{id}` (a 404 for anyone who can’t see it, shown as the error) and finds the flight in it. `flightLiveView` in `frontend/src/lib/flightlive.ts` builds on `flightCardView`, so the state, pill, times, facts and progress are the card’s:

- **Headline.** `Departs in …` (scheduled and delayed), `Boarding now at gate …`, `Landing in …`, `Landed … early`, `Landed … late` or `Landed on time`, `Cancelled`, `Diverted`; the page’s `h1` and a polite live region. The line under it is drawn for a flight in the air (phone: where it is expected and how it departed; desktop: how it departed and whether it is expected on time) and is the card’s sentence for the states the design doesn’t draw.
- **Timeline.** A list named “Flight timeline” with the steps that apply to the state; each shows the scheduled and actual time at its airport, never converted.
- **Refresh.** `refreshFlightStatus` from `flightstatus.svelte.ts`, shown only while live status is on, not paused and the flight is within 6 hours of landing (or has a status). A failed Refresh keeps the data on screen and says “Couldn’t refresh. Last updated <time>.”; the view never says “Updated just now”.
- **Phone and desktop.** The page branches on `viewport.phone` where the design draws different things (the icon Refresh button, the seats on one line, the line under the headline) and on CSS where it only moves them.

## Kind tiles and avatar stacks

`KindTile.svelte` is a 28 or 36 px square holding a booking kind’s icon on its tint. A stay is a bed (Lucide’s `bed`) wherever a tile shows one, in the tinted and the outline form, and keeps its accessible name “stay”. With `outline` it is the clean and bold form: the icon alone, 26 px, in the kind’s colour, with no square or tint; the booking card and the booking detail use it, and other pages keep the tinted form until #879 decides them. The kinds use `--kind-flight`, `--kind-stay`, `--kind-train` and `--kind-car` as the icon stroke; cruise, parking and past visit use `--kind-quiet`. Each has a `-soft` tint for the background. A tile has an accessible name matching its kind’s label in `TripKinds`, unless you pass `decorative`. `TripKinds.svelte` is a row of them.

`AvatarStack.svelte` overlaps up to four initials circles and then shows a “+N” circle.

- `avatarTone(person)` in `frontend/src/lib/avatar.ts` picks each person’s tone: by id when they have one, otherwise by name, so the same person keeps the same colour.
- The six tones are `--avatar-1` to `--avatar-6` with their `-ink` text, all in `app.css`.
- Give the stack one accessible label; its circles are hidden from assistive technology.

## Monospace type

Text is set in Inter, a variable font bundled under `waypoint/static/fonts` with its licence, with tabular figures. Times, airport codes, confirmation codes and seat numbers use `font-mono`: Geist Mono, bundled under `waypoint/static/fonts`, with tabular and slashed-zero figures. The `.mono` class sets them on any element, and `.code` adds the confirmation-code style. No font is loaded from outside Waypoint.

## Navigation

Which page goes where is `TABS` and `MORE` in `frontend/src/lib/nav.ts`.

- **Below the `lg` breakpoint** (phones and tablets), `TabBar.svelte` shows Upcoming, Trips, Stats and Review (with its count of items waiting) and a More button.
  - More is a disclosure (`aria-expanded`, `aria-controls`) that opens a list with People and Settings. It closes on Escape (focus returns to the button), on a tap elsewhere and when the page changes.
  - While People or Settings is the current page, More is marked with `aria-current` and says which page in its accessible name, and the page’s link in the list carries `aria-current="page"`.
  - The Settings avatar link in `TopBar.svelte` stays at every width.
- **From `lg` up**, `SideNav.svelte` lists all six pages.

The phone tab bar is a frosted glass bar: the page background at 75% over a 28px backdrop blur with `saturate(2)` and `brightness(1.1)`, no outline (the border is transparent) and a faint inner top highlight for the edge. Content scrolling behind it shows through blurred and slightly lightened. Browsers without `backdrop-filter` get the solid `surface-2` background.

The labels keep their contrast over bright content too (an expanded email preview is white, a primary button is bright): the `tab-bar-contrast` verify flow scrolls a primary button under the bar and fails if the audit finds a label below 4.5:1.

## Sheet

`ui/sheet/Sheet.svelte` is the one panel for detail and editing that sits over a page. It is built on bits-ui’s `Dialog`, the primitive `ConfirmDialog` uses, with its own layout: `ConfirmDialog` is a centred confirmation with a fixed form, so it could not be extended into a sheet and the two share only the primitive. Pass `title` (the dialog’s name), an optional `description` and bind `open`.

- **Placement.** On a phone (`viewport.phone`, the same query as the `phone:` variant) it slides up from the bottom, capped at 92% of the screen height, over a dimmed page, with a grab handle. Dragging the handle down 96 px or more closes it; less springs back. On a wider screen it is a side panel on the right, 34 rem at most.
- **Closing and focus.** It closes with the close button, Escape, a tap on the dimmed page or the swipe. Focus is trapped inside while it is open and returns to the control that opened it.
- **Reduced motion.** With `prefers-reduced-motion: reduce` it fades in and out and does not slide.
- **Headings.** Content that already has a heading of its own should drop it (`SegmentForm`’s `titled={false}`), since the sheet’s title names the dialog.
- **Trip page.** **Edit** (and **Add address**) in a booking’s detail opens `SegmentForm` in a sheet at every width, with the detail closed.
- **Upcoming.** A booking in the day-by-day list opens its pass card in the sheet at every width (a modified click still follows the link to the trip page).
  - The Next up card passes `boarding` to `PassCard`, which draws it as a boarding pass: a header strip with the eyebrow, trip name, status chips and countdown; the route or place and times; and a stub with the confirmation code, the details and the travellers. Every other `PassCard` keeps the full pass.
  - `Upcoming.svelte` splits the list at today, with earlier days in a native `<details>` so the toggle is keyboard accessible without script.
  - The flight hero on this page keeps no confirmation code, travellers or cost on its face (owner decision, #876, 2026-11-21): they, Open trip and Show QR code are in the opened booking, behind the hero’s last row. A day row keeps opening the booking sheet it opened before.
  - The page is the title in the large heavy face (`text-display`, `text-display-lg` from `md`), the review line, the next-up hero and the day list, to `docs/design/clean-and-bold/i-upcoming.html`. From a container width of 900px the hero and what goes with it sit in the left column and the day list, headed “Coming up”, in the right; below it the list goes under the hero. There are no stat tiles and no banners.
  - The review line is one link of at least 44px, with an amber dot, the count in the muted text colour and a chevron, shown only when `review_count` is above zero; it carries the count and nothing of any email.
  - A day is a small uppercase label over its rows. The first day with a booking that is not cancelled and still has something to come, at the times of its places, carries a blue dot and “Next”; a day whose bookings are all over or cancelled never does. A row is the time in bold tabular figures, the booking’s brand logo (or its outline `KindTile` when it has none), the title and a grey line, at least 44px, with a hairline under it, and opens what it opened before. A parking booking whose gate code is ready (`showsCode` in `frontend/src/lib/gate-code.ts`) shows a blue “Show code”, `RowShowCode.svelte`, in place of the chevron.
  - The small date on each Later trip, on the phone tiles and in the desktop list, is amber (`text-signal`): the owner chose to keep it, although amber elsewhere means changed or needing attention.
  - Not drawn in the designs and kept as they were, on the new tokens: the hero when the next booking is not a flight, Also under way, and the arrival card.
  - The offline status card is gone from this page and from the trip page (owner decision, #921, 2026-11-21, by direct request, with no mockup). The green **Saved for offline** button at the right of the header stays as it was, shown only while saving works, and now links to Settings → Offline & notifications (`OfflinePill`), where saving is set up, switched off and checked.
- **Review: the form.** The add-by-hand and check-suggestion form, with the email, opens in the sheet at every width.
  - It takes `wide` (a side sheet of up to 40rem), `split` (from 1100px, `SPLIT_QUERY` in `phone.svelte.ts`, up to 72rem with the email beside the form) and `onOpenAutoFocus` to choose where focus lands.
  - Closing a changed form asks “Discard changes?” first.
  - On a phone the sheet switches between the email and the form with two buttons. The action bar is sticky at the bottom of the sheet (`scroll-padding-bottom` keeps a focused field above it) rather than fixed to the screen, so it never sits over the keyboard.
- **Review: the page.** Items are grouped by the decision they need (Check suggestions, Add missing details, Match bookings, Match people), each with a count and one prominent button per row. Less common actions go in `ActionMenu.svelte`, a disclosure (`details`) labelled More that closes on Escape (focus returns to its button) and on an outside click. The page passes `returnFocus` to `ConfirmDialog` so a cancelled question returns focus to it.
- **Drafts.** Every form that can hold typing (a booking being added or edited, a trip’s details, a person, a membership, a Review form) registers a draft guard (`frontend/src/lib/drafts.svelte.ts`) and shows `DiscardDialog`.
  - These ask first, with **Keep editing** and **Discard changes**, and only when the form was changed: dismissing a sheet (Escape, the close button, the backdrop, a swipe down), Cancel, starting another edit, picking another trip or changing the trips filter, browser Back or any other change of the address, and closing or reloading the tab. Nothing leaves a form while it is saving.
  - Drafts live in memory only, never in browser storage, so a loyalty number typed into a form is never kept anywhere else.
  - A `Sheet` takes the guard of its form (`guard`), or picks up the guards of forms inside it.
- **Session expiry.** While a form is changed, **Sign in** opens in a new tab so the form stays on this page, and coming back to the tab clears the banner once you are signed in.
- **People.** The forms (a guest, a membership) open in the sheet on a phone and inline on a computer, decided when they open. Page titles use `text-display`.
