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
- A status pill and one plain sentence give the state (Scheduled, Boarding, Delayed 35 min, In the air, Landed, Cancelled, Diverted).
- Four facts in big type with small-caps labels: before departure Terminal, Gate, Seat, Cabin; in the air and landed Terminal, Gate, Belt, Seat (the arrival side). Each is marked as from live status (a filled blue dot) or from the booking (a hollow grey ring). An unknown value shows a dash; the row is never left out.
- Eight states: scheduled, boarding, delayed, in the air, landed, cancelled, diverted, and scheduled with no live data. With no live data the card says live status starts 3 days before departure (the number of days is a placeholder to confirm against the data source) and shows the times on the booking.
- The live status view: a big route, the headline "Landing in 38 minutes", a progress bar, a departed / in the air / lands timeline, big arrival facts (Terminal, Gate, Belt), seats per traveller from the booking, and Refresh with when the data was last updated.
- Where else a flight appears: a Home next-flight card, flight rows in the trip list (kind tile, "DEN to GJT · EA 214", time, status chip) and the booking on the trip page with a one-line progress bar. Each opens the live status view.
- Seat and cabin come from the booking. Terminal, gate, belt, delay, and the actual times come from live status.
- Times are where they happen: every time is a wall-clock time at its airport, with the zone shown where it matters, never converted to the viewer's or the server's zone.

## Open questions for the owner

1. Which gate, terminal and belt data exists (see [flight-gates.md](../flight-gates.md), #635 and #638)? Until the data source lands, some facts stay dashes, and the dash is a designed state, not a bug.
2. Live status starts "3 days before departure" in the no-live-data card: confirm the window against what the status source and its monthly request limit allow.
3. "Econ" on phone versus "Economy": the phone card abbreviates so four facts fit across; confirm, or use a shorter fact for cabin.
4. The arc and plane geometry on very short flights (under an hour, the plane sits close to the codes) and very long ones (the arc is a drawing, not a route): is a straight dotted line better for either?
5. Does a landed flight keep showing the card on the trip page after it lands, or fall back to the plain booking once the trip is over (the completed-trip designs hide gate and live status)?

## Fonts

The pages load Geist and Geist Mono from Google Fonts when you are online and fall back to system fonts otherwise. This is for viewing these design files only; the app bundles its own fonts and loads nothing from outside.
