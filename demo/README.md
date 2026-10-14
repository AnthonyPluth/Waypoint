# Standalone read-only demo

The demo builds the same Svelte screens and components as the main application: Upcoming, Trips, booking details, Review, People and loyalty numbers, Stats and travel maps, year-in-review cards, Settings, and animated route replays with pause, speed and scrubbing controls. It uses the application's dark theme and bundled Geist font.

All records are invented. `frontend/demo/data.json` was generated from the repository's synthetic demo seed in a new, temporary database, with network access denied. That database was discarded. The snapshot includes an explicit Colorado road trip with a rental car. Every booking was supplemented with fictional details, a price and a simulated source email. The bundle contains no database, mailbox token, credentials, uploaded images or user data. Live flight updates are unavailable. Three incomplete review examples cover a flight, road-trip rental and cruise, each missing its end time; booking-match and unmatched traveler examples are also included.

The build substitutes the network transport with `frontend/demo/api.ts`, which returns copies of bundled synthetic responses. Changes are rejected and controls for editing, importing, authentication, mailbox connections, notifications, offline setup and external integrations are disabled. Revealing a fictional loyalty number is a read operation against bundled data. The app's service-worker entry point is replaced. There are no runtime API calls, storage writes, external fonts or tiles, analytics, or backend services. Map geography is bundled and drawn in SVG, using the application's vector replay/map components; no OpenStreetMap is used.

The demo allows source emails to be inspected on past bookings as well as upcoming ones. These are synthetic text, without remote images or message links. The production app's past trips do not show offline-saving notices or setup prompts.

Shared hotel reservations appear once with everyone on the booking and one price. The two reservations used to demonstrate Review matching have distinct rooms and travelers at the same property.

The demo clock stays at noon UTC on the snapshot's `asOf` date. It is installed before the shared frontend loads, so upcoming itineraries, active travel and past-trip replay stay available regardless of the visitor's current date. Explicit booking dates and animation timers keep their normal behavior. Production time handling is unchanged.

## Build and verify

Run `npm ci` and `npm run build:demo` from `frontend/`. The standalone output is `frontend/demo-dist/` and can be served by any static HTTP server. Run `node demo/verify.mjs` from the repository root to check the compiled payload at phone, tablet and desktop widths, including requests, blocked controls, source emails, filters and animated replay. Screenshots are written to `artifacts/static-demo/`.

The browser verification sets the visitor's clock to 2040 and checks that the shared Upcoming page still shows its itinerary and pass card. It accepts only requests for bundled files under the demo directory and fails on any API, external-service, fetch/XHR, worker or websocket request. A Content Security Policy also denies all connections.

## GitHub Pages

The main-only `Docs` workflow builds documentation and the demo, then copies the demo output under `docs/dist/demo/`. One artifact preserves documentation at `/Waypoint/` and adds the demo at `/Waypoint/demo/`. Both frontend and docs changes trigger this workflow. Pull requests build both without publishing.

Pages Source must be **GitHub Actions**. The `github-pages` environment only needs to allow `main`. Preparing or pushing code is not publication: merging and a successful Docs deployment from main are required.
