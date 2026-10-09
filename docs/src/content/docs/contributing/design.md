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

- The headline comes from `passHeadline(segment, now)` in `frontend/src/lib/trips.ts` and uses the booked times only. A flight reads "Check-in opens in …" until `CHECK_IN_WINDOW_HOURS` before departure, then "Check-in is open, departs in …", then "Under way, arrives in …", then "Landed". Live status never changes it. A cancelled segment reads "Cancelled".
- The plane comes from `routeProgress(segment, now)`: `(now − departure) ÷ (arrival − departure)` on the segment's instants, clamped to 0–1, and 0 for a segment with no times. It never uses live status.
- Times are the wall-clock times at each place, as stored, with the bracketed "your time" reading when your zone differs.
- The card does not read the API for gate or city: a gate shows only from live flight status, and the airport name is not shown.
