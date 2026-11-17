# Flight cards and live status: designs for sign-off

These designs are for the redesign of how Waypoint shows a flight, more like a flight-tracker widget. They come from [#666](https://github.com/AnthonyPluth/Waypoint/issues/666); the owner approved them in chat on 2026-11-16, and the formal "Signed off" on #666 is still pending. Each file is a self-contained HTML page (vector only, no raster images) for one screen group. Open it in a browser and use the toggle at the top to see it at phone width (390 px) or desktop width (1280 px; the content column is 960 px). The pages use Waypoint's tokens from `frontend/src/app.css`, dark only. Every flight, name, seat and airport in them is made up, and no airline logo is used: the mark is Waypoint's own. The frames leave out the app's own navigation, to show the page itself.

Each page says what it replaces: the flight view of `frontend/src/lib/components/PassCard.svelte` and the `FlightStatus.svelte` block, the flight rows and Home card in `frontend/src/pages/Upcoming.svelte`, and the booking card in `frontend/src/pages/Trip.svelte`. Where gate and live-status data come from is in [flight-gates.md](../flight-gates.md) (#635, #638).

| Screen | File | What it shows |
| --- | --- | --- |
| a | [a-flight-card.html](a-flight-card.html) | The flight segment card in eight states (scheduled, boarding, delayed, in the air, landed, cancelled, diverted, scheduled with no live data), phone and desktop |
| b | [b-live-status.html](b-live-status.html) | The live flight status view for a flight in the air: route, headline, progress bar, timeline, arrival facts, seats, Refresh; phone and desktop |
| c | [c-elsewhere.html](c-elsewhere.html) | Where else a flight appears: the Home next-flight card, flight rows in the trip list, and the booking on the trip page (phone width; desktop keeps the layout inside its columns) |

## Decisions the designs fix

- The route is the headline: two large airport codes, a dotted arc between them and a plane marker showing progress along it.
- Flight identity is top left (Waypoint's own mark tile and the flight number, never an airline logo) and the total duration is top right.
- Departure and arrival times sit under their airports as wall-clock times with the zone, never converted. When delayed they turn amber, with the original time struck through above the new one.
- "Updated N min ago" sits between the times, and is omitted when there is no live data.
- A status pill gives the state (Scheduled, Boarding, Delayed 35 min, In the air, Landed, Cancelled, Diverted); a short line beside it appears only where it adds something (see the owner decisions below).
- Four facts in big type with small-caps labels: before departure Terminal, Gate, Seat, Cabin; in the air and landed Terminal, Gate, Belt, Seat (the arrival side). Each is marked as from live status (a filled blue dot) or from the booking (a hollow grey ring). An unknown value shows a dash; the row is never left out.
- Eight states: scheduled, boarding, delayed, in the air, landed, cancelled, diverted, and scheduled with no live data. With no live data the card says live status starts 1 day before departure (decided by the owner on 2026-11-16, down from the 3 the frames first showed) and shows the times on the booking.
- The live status view: a big route, the headline "Landing in 38 minutes", a progress bar, a departed / in the air / lands timeline, big arrival facts (Terminal, Gate, Belt), seats per traveller from the booking, and Refresh with when the data was last updated.
- Where else a flight appears: a Home next-flight card, flight rows in the trip list (kind tile, "DEN to GJT · EA 214", time, status chip) and the booking on the trip page with a one-line progress bar. Each opens the live status view.
- Seat and cabin come from the booking. Terminal, gate, belt, delay, and the actual times come from live status.
- Times are where they happen: every time is a wall-clock time at its airport, with the zone shown where it matters, never converted to the viewer's or the server's zone.

## Open questions for the owner

1. Which gate, terminal and belt data exists (see [flight-gates.md](../flight-gates.md), #635 and #638)? Until the data source lands, some facts stay dashes, and the dash is a designed state, not a bug.
2. Live status starts "1 day before departure" in the no-live-data card. Decided by the owner on 2026-11-16: the window is one day (`LIVE_STATUS_STARTS_DAYS` in `frontend/src/lib/flightcard.ts`).
3. "Econ" on phone versus "Economy": decided by the owner on 2026-11-16: the cabin always reads "Economy" in full. The four fact columns are equal where there is room and otherwise each takes at least the width of its label or value, so "Economy" fits at the frames' own value size on a card about 330 px wide.
4. The arc and plane geometry on very short flights (under an hour, the plane sits close to the codes) and very long ones (the arc is a drawing, not a route): is a straight dotted line better for either?
5. Does a landed flight keep showing the card on the trip page after it lands, or fall back to the plain booking once the trip is over (the completed-trip designs hide gate and live status)?

## Owner decisions on the build (#714, 2026-11-16)

- Boarding, which the status source does not report, is derived: a live status with a gate and departure within 40 minutes.
- The parts the frames don't draw are accepted as built: "+1 day" after an overnight arrival, the date after the Departure or Arrival label when the flight is not today, booked times for a flight with no live status, the booking's terminal (with the ring) when live status has none, and the confirmation code, travellers and Edit, Move and Remove under the facts.
- The trip page's card has no Refresh button; Refresh moves to the live status view (#715). A small quiet line, "Live updates paused until <time>" with the reason, stays on the card while updates are paused (monthly limit, rate limit or a refused key), whether or not a status is stored. The frames don't show it.
- With no live status yet, the card says when live status starts, and the departure date shows after the Departure label ("Departure · Denver · Thu Jun 12").
- The live-status window is one day before departure.
- The card never repeats itself (owner, 2026-11-16): there is no line beside the pill for Boarding, Scheduled or Delayed (the pill, the gate and the times say it). The short lines that stay, each decided by the owner: In the air says "Lands in 38 minutes."; Landed says "3 minutes early.", "N minutes late." or "On time."; Cancelled says "Contact <airline> about rebooking."; Diverted says "Was headed to Grand Junction." (or "Where it lands isn't known yet." when no other airport is known); a flight with no live status says when live status starts. The date goes after the Departure or Arrival label (for example "Departure · Denver · Thu Jun 12") when it isn't today. The accessible name of the article still says the whole state in words.
- Cabin and arc, kept as built (owner, 2026-11-16, after seeing the frames and the build side by side at 330 and 358 px): the cabin reads "Economy" in full at the frames' value size, in columns that are equal where there is room and otherwise as wide as their content; the route is one continuous traveled line ending at the plane, and the frames' two-piece line and small apex dot are not used because the dot and the plane don't coincide in the frames' In the air panel.

## Owner decisions on the build (#715, 2026-11-17)

Made in chat after seeing the frames and the build side by side (phone and desktop, a flight in the air):

- The states the design doesn't draw are accepted as built: the headline "Departs in …" for scheduled and delayed flights, "Cancelled", "Diverted" and "Landed … early", "on time" or "late"; the departure Terminal and Gate before takeoff in place of the arrival facts; and "Seat not known yet" for a traveller with no seat.
- The card opens the live status view through an invisible link over the whole card, with no visible control; its footer controls stay above the link.
- The headline stays a polite live region with the countdown, as drawn.
- The wording "Updated less than a minute ago" and "Couldn’t refresh. Last updated <time>." is accepted.

## Owner decisions on the build (#716, 2026-11-17)

- The compact booking (a one-line "Flight progress" bar, "Departed 9:46 am", "Lands 10:52 am") goes in the Upcoming booking sheet, where a flight opened from the day-by-day list used to show the full booking card and the `FlightStatus` block, and not on the trip page, which keeps the full flight card from #714 untouched. This is a different screen from the one `c-elsewhere.html` names.
- "Flights today" is a separate, flights-only list on Upcoming, above the existing day-by-day lists, which stay as they are.
- The Home card keeps "Next up" (or "In the air"), the confirmation codes, Open trip and the gate-code control as before, and a flight with no live status shows its booked times like the flight card does.
- The Home flight card no longer shows the check-in countdown, the brand logo, the seat and cabin lines or the "Confirmed" chip (owner, 2026-11-17, after seeing the frames and the build side by side). Check in or Open in app, Directions and Call, the travellers and the cost stay on the card, as before (nothing records a decision to drop them). The full card, with the dropped lines, stays outside the window and after the flight lands, and the trip page keeps its full flight card.

## Fonts

The pages load Geist and Geist Mono from Google Fonts when you are online and fall back to system fonts otherwise. This is for viewing these design files only; the app bundles its own fonts and loads nothing from outside.
