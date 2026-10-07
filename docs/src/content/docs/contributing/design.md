---
title: Design
description: The web app's dark palette, status, elevation and type tokens, and the status chip, airport code and route line.
sidebar:
  order: 3
---

The web app's look is one file of tokens and three shared components. Pages compose them; nothing invents a colour or a badge of its own.

## Dark only

Waypoint has one theme: dark. `frontend/src/app.css` sets `color-scheme: dark` on `:root` and writes the palette once — there is no light block and no `prefers-color-scheme` handling anywhere in `frontend/`. A browser asking for light gets the dark app, which is intended.

ESLint's `waypoint/no-light-theme` (in `frontend/eslint.config.js`) keeps it that way. It fails a change that:

- adds a `dark:` variant (there is no light theme for it to switch to),
- handles `prefers-color-scheme` or declares `color-scheme: light`,
- paints a white surface (`bg-white`),
- gives a `--…` token a light colour: any `#` value with a relative luminance of 0.6 or more, except in a token whose name ends in `-ink` or `-foreground`, which are meant to be light on a dark ground.

It runs over `frontend/**/*.css`, `frontend/index.html` and the app's TypeScript and Svelte. The rule can't check the file that defines its own patterns (`frontend/eslint.config.js`) or the file that holds its failing examples (`frontend/src/lint-rules.test.ts`), so those two are exempt; every other file in `frontend/` is checked. `frontend/src/lint-rules.test.ts` carries one failing and one passing example of each of its four messages.

## Tokens

Everything is in `frontend/src/app.css`, and `@theme inline` exposes it to Tailwind, so a class like `bg-card` or `text-title` refers to a token rather than a colour of its own.

| Tokens | What they are |
| --- | --- |
| `--background`, `--card`, `--popover`, `--secondary`, `--muted`, `--accent`, `--sidebar` | The dark surfaces, from the page (`#07090e`) up to the panels a booking sits on. |
| `--foreground`, `--card-foreground`, `--muted-foreground` | Text: bright, then dimmer, for the secondary line under a heading. |
| `--primary`, `--ring`, `--signal` | The blue accent (links, the countdown, focus rings) and the amber used for a time that moved. |
| `--border`, `--input`, `--destructive` | Hairlines, field outlines, and the red of a destructive action. |

### Status colours

One soft background and one ink colour per state, and nothing else in the app borrows them:

| Token pair | State |
| --- | --- |
| `--confirmed-soft` / `--confirmed-ink` | A booking is confirmed. |
| `--changed-soft` / `--changed-ink` | A booking changed after it was made. |
| `--cancelled-soft` / `--cancelled-ink` | A booking or a flight is cancelled. |
| `--ontime-soft` / `--ontime-ink` | Live status: the flight is on time. |
| `--delayed-soft` / `--delayed-ink` | Live status: delayed. |
| `--airborne-soft` / `--airborne-ink` | Live status: departed or landed. |
| `--diverted-soft` / `--diverted-ink` | Live status: diverted. |

Every ink is at least 4.5:1 against its own soft background, which is what `StatusChip.svelte.test.ts` asserts by reading `app.css` — a new pair has to hold that too, at the same WCAG AA level as any other text.

### Elevation and type

- `--elevation-1`, `--elevation-2`, `--elevation-3` are the three shadow steps (`shadow-elevation-2` is also `shadow-card`, what a card and a `.rows` panel sit on). Elevation 3 is the highest: a sheet or a dialog.
- `--type-display`, `--type-title`, `--type-heading`, `--type-subheading`, `--type-body`, `--type-small`, `--type-micro` are the type scale, in `rem` (`text-title` is 2.25rem, `text-micro` 0.75rem), and `text-display` is the largest.
- Geist is the typeface (`--font-sans`), with a monospace stack in `--font-mono`; the accent stays the blue it has been.

## The three components

All three live in `frontend/src/lib/components/` and are imported by path:

```svelte
import RouteLine from "$lib/components/RouteLine.svelte";
```

### StatusChip

One word and one colour per state, and the word carries the meaning on its own — colour only reinforces it, so the chip still reads in greyscale.

```svelte
<StatusChip status={b.status} />
<StatusChip kind="live" status={s.state} delay={s.delay_minutes} />
```

`status` takes a booking's status (`confirmed`, `changed`, `cancelled`) or a `FlightStatus` state (`scheduled`, `delayed`, `departed`, `landed`, `cancelled`, `diverted`); `cancelled` is the same state in both. The label is `Confirmed`, `Changed`, `Cancelled`, `On time`, `Delayed 50 min` (with `delay`, `Delayed` without), `Departed`, `Landed` or `Diverted`.

The two kinds differ in size, not in colour: `booking` (the default) is the one every booking has, leading the booking's line; `live` is smaller and secondary, and `FlightStatus` renders it only when live status is switched on. `StatusChip.svelte.test.ts` covers the mapping for every status and both kinds.

### AirportCode

```svelte
<AirportCode code="JFK" />
```

A monospace IATA code, `font-mono font-semibold`, in the size of whatever it is inside — inside a heading that makes it large, which is the point. Anything that shows a route ends its two ends with these.

### RouteLine

```svelte
<RouteLine segment={s} progress={0.5} />
```

The route as an airport code, a line with a plane on it, and the other airport code: `JFK ✈ LHR`, which reads to a screen reader as `JFK → LHR`. `progress` is a value from 0 to 1 that puts the plane that far along, fills the line behind it and leaves it dashed ahead; with no value (or 0) the plane sits at the origin, and at 1 it is at the destination. Values outside 0 to 1 stay on the line.

A segment with no route — a stay, a car, a cruise — renders its headline instead, so a heading can always use `RouteLine` and never has to branch.

## Where they are used

- The trip page leads each booking with a `StatusChip` and writes the segment's heading as a `RouteLine`.
- The Upcoming page's next-up card and the trip page's card heading are `RouteLine`s.
- `FlightStatus` shows the live `StatusChip` beside the times it fetched.

## Checks

`make frontend-lint` runs the light-theme rule, and `make frontend-test` runs the chip mapping, the route line at progress 0, 0.5 and 1 and with no value, and the chip contrast test. `make verify` shows all three components on demo data at phone, tablet and desktop widths.
