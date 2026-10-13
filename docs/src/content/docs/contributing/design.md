---
title: Design
description: The dark-only design foundation, status colours, and the shared chip, airport code and route line.
sidebar:
  order: 2
---

Waypoint is dark only. There is no light palette and no theme setting. Lint rejects a `dark:` variant, a light palette and `prefers-color-scheme` in `frontend/` (and `make fleet-checks` rejects them in the static files), so a new screen never needs to think about themes.

The specimen page at `#design` (Settings, then Design) shows everything below on one screen. `make verify` captures it at phone, tablet and desktop widths: `poetry run python run.py verify design`.

## Tokens

Tokens live in `frontend/src/app.css`: one `:root`, then `@theme inline` to expose them to Tailwind.

- **Surfaces**: `bg-surface-1`, `bg-surface-2` and `bg-surface-3`, from the page background up to a raised card. Pair them with `shadow-elevation-1`, `-2` or `-3`.
- **Status**: `status-{ok,warn,bad,info,quiet}-soft` is the background and `-ink` is the text. Use them through the chip, not by hand.
- **Type scale**: `text-display`, `text-title`, `text-heading`, `text-body`, `text-caption` and `text-eyebrow`. Each sets size, line height, letter spacing and weight.

Every status ink meets WCAG AA (4.5:1) on its soft colour, the card and the page background. `src/app.css.test.ts` parses the tokens and fails if a change breaks that.

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

`RouteLine.svelte` draws origin, destination and a line between them with a plane placed at `progress`, from 0 (departure) to 1 (arrival). Out-of-range or missing values clamp to 0 and 1 (`clampProgress`). Progress comes from the booked times; Waypoint does not need live data for it. Pass `label` to give the line an accessible description, otherwise it is hidden from assistive tech.

## Pass card

`PassCard.svelte` is the one card for a booking you are planning or checking in for, with a variant for each kind (flight, hotel, car, train, cruise). Top to bottom: a headline line, the confirmation code as the largest element (the first focusable control, tap to copy), the flight and its date and departure time, the booking link, then the airport codes with the route line and the times at each airport. Below the tear line are the terminal, gate, seat and cabin, the booking chip and, when live flight status is on, the live chip and a quiet line.

- The headline comes from `passHeadline(segment, now, live, online)` in `frontend/src/lib/trips.ts`. Evidence decides its wording (`flightEvidence`): without live status, or when it is older than `LIVE_STALE_HOURS`, or when the device is offline, a flight reads "Check-in usually opens in …" until `CHECK_IN_WINDOW_HOURS` before departure (a reminder-style estimate, not a provider rule), then "Check-in usually open, scheduled departure in …", "Scheduled arrival in …" and "Scheduled arrival time passed"; it never says "Under way" or "Landed" from the clock. Fresh live status may say "Delayed … min, …", "Departed, expected to arrive in …", "Diverted" or, when it is the provider's word, "Landed" and "Cancelled by the airline" (red). A cancelled booking reads "Cancelled".
- The plane comes from `routeProgress(segment, now)`: `(now − departure) ÷ (arrival − departure)` on the segment's instants, clamped to 0–1, and 0 for a segment with no times. It comes from the booked times; the card labels it "Based on schedule", and only live "landed" moves it to the end or live "cancelled" parks it at the start.
- The Next up card on Upcoming is chosen by `nextUp` in `frontend/src/lib/trips.ts`, in this order: (1) a flight, train, cruise or visit that is under way (earliest start first); (2) otherwise the booking that starts soonest; (3) otherwise, when only background reservations remain, the hotel, rental car or parking booking that ends soonest. Hotels, rental cars and parking are background reservations: while one is under way and something else is still ahead, it never takes the card. It appears under "Also under way", soonest end first, with its check-out, drop-off or exit time, and opens like any booking (QR code included). Ties break by segment id. Times are compared as instants from each place's own zone, across every trip the person can see.
- Times are the wall-clock times at each place, as stored, and are never shown in the viewer's own zone.
- The card does not read the API for gate or city: a gate shows only from live flight status, and the airport name is not shown.

## Navigation

Below the `lg` breakpoint (phones and tablets) `TabBar.svelte` shows Upcoming, Trips, Stats and Review (with its count of items waiting) and a More button. More is a disclosure (`aria-expanded`, `aria-controls`) that opens a list with People and Settings; it closes on Escape (focus returns to the button), on a tap elsewhere and when the page changes. While People or Settings is the current page, More is marked with `aria-current` and says which page in its accessible name, and the page's link in the list carries `aria-current="page"`. The Settings avatar link in `TopBar.svelte` stays at every width. From `lg` up, `SideNav.svelte` lists all six pages. Which page goes where is `TABS` and `MORE` in `frontend/src/lib/nav.ts`.

## Sheet

`ui/sheet/Sheet.svelte` is the one panel for detail and editing that sits over a page. It is built on bits-ui's `Dialog`, the primitive `ConfirmDialog` uses, with its own layout: `ConfirmDialog` is a centred confirmation with a fixed form, so it could not be extended into a sheet and the two share only the primitive. Pass `title` (the dialog's name), an optional `description` and bind `open`.

- On a phone (`viewport.phone`, the same query as the `phone:` variant) it slides up from the bottom, capped at 92% of the screen height, over a dimmed page, with a grab handle: dragging the handle down 96 px or more closes it, less springs back. On a wider screen it is a side panel on the right, 34 rem at most.
- It closes with the close button, Escape, a tap on the dimmed page or the swipe. Focus is trapped inside while it is open and returns to the control that opened it.
- With `prefers-reduced-motion: reduce` it fades in and out and does not slide.
- Content that already has a heading of its own should drop it (`SegmentForm`'s `titled={false}`), since the sheet's title names the dialog.
- Trip page: **Edit** (and **Add address**) opens `SegmentForm` in the sheet on a phone and inline under the booking on a computer. Which one is decided when it opens, so a form being filled in does not jump if the window is resized. Upcoming: a booking in the day-by-day list opens its pass card in the sheet at every width (a modified click still follows the link to the trip page). The Next up card passes `compact` to `PassCard` (smaller padding, no tear line, fewer facts); the list is split at today in `Upcoming.svelte`, with earlier days in a native `<details>` so the toggle is keyboard accessible without script.
- Review: the add-by-hand and check-suggestion form, with the email, opens in the sheet at every width, with `wide` (a side sheet of up to 40rem), `split` (from 1100px, `SPLIT_QUERY` in `phone.svelte.ts`, up to 72rem with the email beside the form) and `onOpenAutoFocus` to choose where focus lands; closing a changed form asks "Discard changes?" first. On a phone the sheet switches between the email and the form with two buttons, and the action bar is sticky at the bottom of the sheet (`scroll-padding-bottom` keeps a focused field above it) rather than fixed to the screen, so it never sits over the keyboard.
- Review's page groups its items by the decision they need (Check suggestions, Add missing details, Match bookings, Match people), each with a count and one prominent button per row. Less common actions go in `ActionMenu.svelte`, a disclosure (`details`) labelled More that closes on Escape (focus returns to its button) and on an outside click; the Review page passes `returnFocus` to `ConfirmDialog` so a cancelled question returns focus to it.
- Drafts: every form that can hold typing (a booking being added or edited, a trip rename, a person, a membership, a Review form) registers a draft guard (`frontend/src/lib/drafts.svelte.ts`) and shows `DiscardDialog`. Dismissing a sheet (Escape, the close button, the backdrop, a swipe down), Cancel, starting another edit, picking another trip or changing the trips filter, browser Back or any other change of the address, and closing or reloading the tab all ask first, with **Keep editing** and **Discard changes**, and only when the form was changed. Nothing leaves a form while it is saving. Drafts live in memory only, never in browser storage, so a loyalty number typed into a form is never kept anywhere else. A `Sheet` takes the guard of its form (`guard`), or picks up the guards of forms inside it.
- Session expiry: while a form is changed, **Sign in** opens in a new tab so the form stays on this page, and coming back to the tab clears the banner once you are signed in.
- People: the forms (a guest, a membership) open in the sheet on a phone and inline on a computer, decided when they open. Page titles use `text-display`.
