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

- **Surfaces**: the page is `#0d0c12` (`bg-background`) and a card is pure black (`bg-card`). `bg-surface-1`, `bg-surface-2` and `bg-surface-3` raise from there, with `shadow-elevation-1`, `-2` or `-3`. `--border` is the hairline `#27262c`; cards in the clean and bold look carry no border or shadow, but `--shadow` and `--elevation-*` stay until each component is rebuilt.
- **Text**: `text-foreground` is white, `text-muted-foreground` the secondary grey (`#a9a8b2`) and `text-label` the grey for small uppercase labels (`#8f8e98`).
- **Colour rules**: blue (`--primary`, `#3d8ef7`) is live, now and the one primary action; green (`--success`, `#4cc38a`) is confirmed, on time and good news; amber (`--signal`, `#eba43b`) is changed or needs attention. They feed `status-{ok,warn,bad,info,quiet}-soft` (the background) and `-ink` (the text); use those through the chip, not by hand.
- **Kind colours**, used as the icon stroke: flight `#4f9dff`, stay `#38c6d9`, car `#f4d35e`, train `#c79bff`, cruise `#ff8fab`. Flight and car have values of their own, so a status change no longer moves them, and the car colour and the stay colour are never a status colour (a test holds it).
- **Radius**: `rounded-hero` (30 px) for the flight hero card and `rounded-booking` (24 px) for booking cards. `--radius` is unchanged for everything else.
- **Type scale**: `text-display` (40 px, weight 800; `text-display-lg` is 64 px on desktop), `text-hero-fact` (34 px; `-lg` 44 px), `text-airport` (36 px; `-lg` 44 px), `text-fact` (22 px; `-lg` 26 px), `text-fact-card` (17 px), `text-title`, `text-heading`, `text-body`, `text-caption` and `text-eyebrow` (11 px, weight 600, uppercase, 0.09em). Each sets size, line height, letter spacing and weight.

Every status ink meets WCAG AA (4.5:1) on its soft colour, the card and the page background; the secondary and label greys meet 4.5:1 on the page and the card, and every kind colour 3:1 on the card. `src/app.css.test.ts` parses the tokens and fails if a change breaks that.

## Status chips

`frontend/src/lib/status.ts` maps state to a chip; `StatusChip.svelte` draws it.

| Source | States | Tone |
| --- | --- | --- |
| Booking (always shown) | Confirmed / Changed / Cancelled | ok / warn / bad |
| Live (only when live flight status is on) | On time / Delayed N min / Departed | info / warn / info |
| | Landed | quiet |
| | Cancelled / Diverted | bad |

`bookingChip(status)` always returns a chip. `segmentChips(status, flight, liveOn)` returns both, with `live` null when live status is off or there is no flight status. The booking chip leads; the live chip is the smaller one.

## Airport code

`AirportCode.svelte` shows an IATA code in the monospaced display face, at `large`, `medium` or `small`. Pass `name` and the code renders as an `<abbr>` with the airport name as its title.

## Route line

`RouteLine.svelte` draws the origin, the destination and an arched dashed line between them, with a plane riding the arc at `progress`, from 0 (departure) to 1 (arrival).

- The arc is a quadratic curve in a stretched SVG, so x is linear in progress and the plane’s height is `1 − 2t(1 − t)` of the box. The plane tilts up on the way out and down on the way in.
- Out-of-range or missing values clamp to 0 and 1 (`clampProgress`).
- Progress comes from the booked times, so the line needs no live data.
- Pass `label` to give the line an accessible description; otherwise it is hidden from assistive technology.

## Pass card

`PassCard.svelte` is the one card for a booking you are planning or checking in for, with a variant for each kind (flight, hotel, car, train, cruise). Top to bottom:

- a headline line;
- the confirmation code as the largest element (the first focusable control, tap to copy);
- the flight, its date and departure time, and the booking link;
- the airport codes with the route line and the times at each airport;
- below the tear line, the terminal, gate, seat and cabin, the booking chip and, when live flight status is on, the live chip and a quiet line.

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

`FlightCard.svelte` is the card a flight has on the trip page while its trip isn’t over; other kinds, and a flight on a trip that is over, an untimed flight or a cancelled booking, keep the pass card. The design is `docs/design/flights/a-flight-card.html`, signed off on #666. `flightCardView` in `frontend/src/lib/flightcard.ts` works out everything it shows from the segment, the flight’s live status (if any) and the clock, so the component only draws:

- **State.** Live evidence (`flightEvidence`) gives landed, cancelled, diverted, delayed and in the air; with none, the booked times decide in the air and landed, and Boarding is a status with a gate within `BOARDING_MINUTES` (40) before departure, because the status service folds boarding into scheduled. With no live status at all and a departure more than `LIVE_STATUS_STARTS_DAYS` (1) away, the card has no pill and says when live status starts.
- **Facts.** Four, each with a source: Terminal and Gate from live status (the booking’s own terminal when live status has none), Seat and Cabin from the booking; the arrival side (Terminal, Gate, Belt) in the air and once landed. The status has no belt, so Belt is a dash. An unknown value is a dash with the hidden text “Not known yet”, never a missing row.
- **Times.** Wall-clock times at their airport with the zone, never converted; a delay shows the booked time struck through above the new one, read as “Originally …”. The accessible name of the article is built in the same function.

## Live status view

`pages/FlightStatus.svelte` is the page for one flight at `#trip/<trip id>/flight/<segment id>` (`route.rest` holds what follows the trip id, and `pageFor(route.page, route.rest)` in `frontend/src/lib/nav.ts` maps it to the page; `App.svelte` gives it the 960 px column). The design is `docs/design/flights/b-live-status.html`, signed off on #666. It loads the trip with `GET /api/trips/{id}` (a 404 for anyone who can’t see it, shown as the error) and finds the flight in it. `flightLiveView` in `frontend/src/lib/flightlive.ts` builds on `flightCardView`, so the state, pill, times, facts and progress are the card’s:

- **Headline.** `Departs in …` (scheduled and delayed), `Boarding now at gate …`, `Landing in …`, `Landed … early`, `Landed … late` or `Landed on time`, `Cancelled`, `Diverted`; the page’s `h1` and a polite live region. The line under it is drawn for a flight in the air (phone: where it is expected and how it departed; desktop: how it departed and whether it is expected on time) and is the card’s sentence for the states the design doesn’t draw.
- **Timeline.** A list named “Flight timeline” with the steps that apply to the state; each shows the scheduled and actual time at its airport, never converted.
- **Refresh.** `refreshFlightStatus` from `flightstatus.svelte.ts`, shown only while live status is on, not paused and the flight is within 6 hours of landing (or has a status). A failed Refresh keeps the data on screen and says “Couldn’t refresh. Last updated <time>.”; the view never says “Updated just now”.
- **Phone and desktop.** The page branches on `viewport.phone` where the design draws different things (the icon Refresh button, the seats on one line, the line under the headline) and on CSS where it only moves them.

## Kind tiles and avatar stacks

`KindTile.svelte` is a 28 or 36 px square holding a booking kind’s icon on its tint. The kinds use `--kind-flight`, `--kind-stay`, `--kind-train` and `--kind-car` as the icon stroke; cruise, parking and past visit use `--kind-quiet`. Each has a `-soft` tint for the background. A tile has an accessible name matching its kind’s label in `TripKinds`, unless you pass `decorative`. `TripKinds.svelte` is a row of them.

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
- **Trip page.** **Edit** (and **Add address**) opens `SegmentForm` in the sheet on a phone and inline under the booking on a computer. Which one is decided when it opens, so a form being filled in does not jump if the window is resized.
- **Upcoming.** A booking in the day-by-day list opens its pass card in the sheet at every width (a modified click still follows the link to the trip page).
  - The Next up card passes `boarding` to `PassCard`, which draws it as a boarding pass: a header strip with the eyebrow, trip name, status chips and countdown; the route or place and times; and a stub with the confirmation code, the details and the travellers. Every other `PassCard` keeps the full pass.
  - `Upcoming.svelte` splits the list at today, with earlier days in a native `<details>` so the toggle is keyboard accessible without script.
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
