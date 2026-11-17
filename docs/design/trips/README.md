# Completed trips: designs for sign-off

These designs are for the redesign of completed trips, picked by the owner in a design session and signed off on [#705](https://github.com/AnthonyPluth/Waypoint/issues/705) (not signed off yet). Each file is a self-contained HTML page (vector only, no raster images) for one screen group. Open it in a browser and use the toggle at the top to see it at phone width (390 px) or desktop width (1280 px; the list shows the 960 px content column). The pages use Waypoint's tokens from `frontend/src/app.css`, dark only. Every name, place, code and date in them is made up. The frames leave out the app's own navigation, to show the page itself.

Each page says what it replaces: the Past list in `frontend/src/pages/Trips.svelte` (`TripCard.svelte` keeps the Upcoming cards), and the booking cards, header and options of `frontend/src/pages/Trip.svelte` for a trip that is over. Photo rules are in `docs/PHOTOS.md` and [the photo designs](../photos/README.md).

| Screen | File | What it shows |
| --- | --- | --- |
| a | [a-past-trips-list.html](a-past-trips-list.html) | The Past trips list: photo-led cards grouped by year with the year's totals, one column on phone and two across on desktop; Upcoming shown unchanged for context |
| b | [b-trip-page.html](b-trip-page.html) | The trip page of a completed trip: phone (mosaic hero, facts line, Bookings row, day timeline) and desktop (full-width hero, 400 px left column, photos by day), and the Trip options menu |
| c | [c-bookings.html](c-bookings.html) | The Bookings sheet on phone (and the option of a group for undated bookings) and the bookings list in the desktop column |
| d | [d-booking-details.html](d-booking-details.html) | The booking detail sheet for a flight, stay, car, train, cruise, parking, visit and a cancelled stay, and the desktop panel |

## Decisions the designs fix

- Past trips list: photo-led cards (design A): a photo mosaic (one large, two small) with the trip name on a scrim, a photo-count pill, and a one-line footer (dates, nights, distance) with avatars; grouped by year with the year's totals. Past trips only: Upcoming keeps its countdown cards (no photos yet). One column on phone, two across on desktop.
- Trip page, phone: a compact mosaic hero; one facts line (days, nights, distance, photos) with avatars, the total when costs are shown, a "3 photos need a look" chip and Replay; a "Bookings · 6" row (kind icons, "2 flights · 3 stays · 1 car") that opens the Bookings sheet; then a day-by-day timeline (a dot on a rail, the date, place and photo count, a small route glyph, six photos and a "+N" tile) and "Show all N days". No per-day booking chips and no "Night x of y" lines. Add a booking, Merge another trip and Delete trip live in the Trip options menu once a trip is over.
- Trip page, desktop: a full-width mosaic hero; a 400 px left column that stays in view (facts, the map with photo-count pins and Replay, the full bookings list) and the photos by day on the right (six across, "Show all N days", "Open gallery").
- Each photo appears once: the hero shows the trip's best photos and the day grids show the rest.
- Bookings: the list shows what a booking is and when, with a chevron, and no confirmation codes. A tap opens a detail sheet (a bottom sheet on phone, a right panel on desktop) with the header (kind icon, name, subtitle, an always-visible Edit, Close) and a definition list of the fields that kind has: flight (Departs, Arrives, Terminal, Seat, Cabin, Confirmation with Copy, Travellers, Price); stay (Dates, Address with Copy, Room, Confirmation with Copy, Travellers, Price; no check-in or check-out times); car; train; cruise (Embarks, Disembarks, Ports, Cabin and deck); parking; visit; and a cancelled state (a badge, struck-through dates and price, the note "Cancelled, so not in the trip's total"). Email, directions, call and the airline app stay hidden once a trip is over (the app already does this, see `Trip.svelte`). Price shows only when costs are shown. Fields come from `Segment.details` as `PassCard.svelte` lists them; where a mockup label differs from `PassCard`'s (car, cruise), the build issue settles the name.
- Photos shown follow sharing: only photos the viewer may see (see [the photo designs](../photos/README.md) and `docs/PHOTOS.md`): the hero, the grids, the pins, the counts and the need-a-look chip are built from them alone.
- Distance is shown in the household's unit, one unit throughout the app.
- Past trips list (a), decided by the owner on 2026-11-16 and built in #708: each year is an `h2` (it was an `h3`) with `N trips · N photos` beside it, the photo total counting only photos the viewer may see; on desktop the caption under the name shows the trip's destination (the frames draw a country; the owner chose the trip's destination); a Past card's footer is hidden from the reader, because the link's name already says its dates, nights, distance, photos and people (accepted by the owner).
- Past trips list on a phone, changed by the owner on 2026-11-16 (a request on the signed-off design, no new visual design): the "Show 2025", "Show 2024" buttons are gone. The newest year shows first and the next year loads by itself, one year at a time, when the person scrolls near the bottom (an IntersectionObserver on an invisible sentinel that looks 600 px ahead). While a year loads, a small quiet line, "Loading 2025…", sits under the list; a polite live region then says "Loaded 2025, 4 trips", and focus never moves. Where the browser has no IntersectionObserver, a quiet but real, focusable "Show more" button takes the place of the sentinel and reveals the next year when pressed. Desktop already lists every year and is unchanged.

## Owner decisions on the build (2026-11-16, PR #748)

The phone frames do not draw these; the owner settled them when reviewing the build of the completed trip page (#709).

1. Editing a trip's name, destination and notes: a pencil button beside Trip options.
2. The map hero (fewer than three photos to show): the title and dates, then the replay map with its controls and stops, then the quiet line "No photos yet", then the facts.
3. Replay trip in the facts line opens the replay inline under the line; a trip's notes show as a paragraph under the facts.
4. The gallery's Select is not on this page; a photo is removed from the viewer.

## Owner decisions on the desktop build (2026-11-17, PR #794)

The desktop frame b2 does not draw these; the owner settled them when reviewing the build of the desktop trip page (#710).

1. Photos by day: up to 12 photos per day, six across (two rows), as drawn. At 1024 px the right column stays about 300 px wide, which is accepted.
2. Open gallery opens a tile view of every photo (the existing gallery grid by day, the hero's photos included); a tile opens the viewer, and the button then reads Close gallery.
3. Replay trip plays in the left column in place of the map, using only the replay's own controls and with no Hide replay button; the map comes back when the replay ends (it plays to the end, or the slider is moved to the end). For a person who asks for reduced motion the replay has no controls, so Replay trip is not offered on the map.
4. The Places fact is a count, as in b2: "3 states". One place is named ("Utah", "France"); only countries is "2 countries"; a mix of states and other countries is "2 places".

## Owner decisions on the bookings build (2026-11-17, #711)

The c frames do not draw these; the owner settled them when the build of the Bookings sheet and list (#711) hit choices the issue left open.

1. `Other` is the bookings of kind parking, even when dated; it is the last group, headed `Other` (the frames call it "Not dated"). Every other booking is on its start day, and a car booking that spans more than one day is under `Whole trip`. A cancelled booking stays in its group with a quiet `Cancelled` label.
2. #711 builds the list, the sheet and the grouping only, and wires none of them into the page: the booking cards with Edit, Move and Remove stay on a completed trip until #712 wires the list, the sheet and the detail sheet together.
3. Desktop (c3) is a flat list of dated rows in the 400 px column, with no group headings, each row carrying its date; the phone sheet is the grouped list. The grouping function serves both.

Until the Bookings sheet (#711) and the booking detail sheet (#712) land, a past trip keeps its existing booking cards below the days, with Edit, Move and Remove; they go away when those land.

## Open questions for the owner

1. Six photos per day, or three on phone?
2. The hero's fallback when a trip has few or no photos, or no Immich library: map and bookings only? Decided by the owner on 2026-11-16 for the Past list card (#708): a route map in place of the photo mosaic, the same size as the mosaic, with no photo-count pill, and a plain tile with the trip's kind icons when the route cannot be placed. The trip page hero keeps its own issue.
3. How a day's cover and best photos are chosen (suggestion: the first with GPS), and who picks the hero's best photos.
4. A group for undated bookings (parking, for example) at the end of the Bookings sheet (drawn as c2)?
5. Does Edit stay in the detail sheet, or move to the Trip options menu?
6. Flight and train fields not drawn (gate and live status are hidden for past trips): confirm.
7. Day counts: the mockup's day header counts are each day's photos. If the hero's photos are taken out of the day grids, should the header count only the photos left?
8. Desktop width: the trip page route is capped at 48 rem today (`App.svelte`) and the mockup uses the full 1280 px; and with a past trip selected in the Trips two-pane view the list column is narrow, too narrow for two cards across. Decided by the owner on 2026-11-16 (#708): a past trip opens on its own page and never in the side pane, which shows only a trip still to come; with none the Past cards run two across. A booking moved from the pane into a past trip leaves the pane on the trip it was showing, as long as that trip is still to come.

## Fonts

The pages load Geist and Geist Mono from Google Fonts when you are online and fall back to system fonts otherwise. This is for viewing these design files only; the app bundles its own fonts and loads nothing from outside.
