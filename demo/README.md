# Standalone read-only demo

The demo builds the same Svelte screens and components as the main application, with its dark theme and bundled Geist font: Upcoming, Trips, booking details, Review, People and loyalty numbers, Stats and travel maps, year-in-review cards, Settings, and animated route replays with pause, speed and scrubbing controls.

- **Data.** All records are invented. `frontend/demo/data.json` was generated from the repository’s synthetic demo seed in a new, temporary database with network access denied, and that database was discarded.
  - It includes an explicit Colorado road trip with a rental car. Every booking has fictional details, a price and a simulated source email.
  - Three incomplete Review examples cover a flight, a road-trip rental and a cruise, each missing its end time. Booking-match and unmatched-traveller examples are included too.
  - Shared hotel reservations appear once, with everyone on the booking and one price. The two reservations that demonstrate Review matching have distinct rooms and travellers at the same property.
  - The bundle contains no database, mailbox token, credentials, uploaded images or user data. Live flight updates are unavailable.
- **No network.** The build replaces the network transport with `frontend/demo/api.ts`, which returns copies of bundled synthetic responses.
  - Changes are rejected, and controls for editing, importing, authentication, mailbox connections, notifications, offline setup and external integrations are disabled. Revealing a fictional loyalty number is a read of bundled data.
  - The app’s service-worker entry point is replaced.
  - There are no runtime API calls, storage writes, external fonts or tiles, analytics or backend services. Map geography is bundled and drawn in SVG by the application’s vector replay and map components; OpenStreetMap is not used.
- **Source emails.** They can be inspected on past bookings as well as upcoming ones. They are synthetic text, without remote images or message links. The production app’s past trips show no offline-saving notices or setup prompts.
- **Clock.** It stays at noon UTC on the snapshot’s `asOf` date and is installed before the shared frontend loads, so upcoming itineraries, active travel and past-trip replay stay available whatever the visitor’s date. Explicit booking dates and animation timers behave as normal. Production time handling is unchanged.

## Build and verify

Run `npm ci` and `npm run build:demo` from `frontend/`. The standalone output is `frontend/demo-dist/` and can be served by any static HTTP server.

Run `node demo/verify.mjs` from the repository root to check the compiled payload at phone, tablet and desktop widths, including requests, blocked controls, source emails, filters and animated replay. Screenshots are written to `artifacts/static-demo/`.

The browser verification:

- sets the visitor’s clock to 2040 and checks that the shared Upcoming page still shows its itinerary and pass card;
- accepts only requests for bundled files under the demo directory, and fails on any API, external-service, fetch/XHR, worker or websocket request;
- runs under a Content Security Policy that also denies all connections.

## GitHub Pages

The main-only `Docs` workflow builds the documentation and the demo, then copies the demo output under `docs/dist/demo/`. One artifact serves the documentation at `/Waypoint/` and the demo at `/Waypoint/demo/`. Frontend and docs changes both trigger the workflow; pull requests build both without publishing.

Pages Source must be **GitHub Actions**, and the `github-pages` environment only needs to allow `main`. Publishing needs a merge and a successful Docs deployment from `main`; preparing or pushing code is not publication.
