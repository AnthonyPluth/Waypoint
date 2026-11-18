# MapKit only: the design (#828)

This is phase 1 of [#828](https://github.com/AnthonyPluth/Waypoint/issues/828): the design for showing every map in Waypoint on Apple's MapKit, removing the bundled SVG renderer and the server's road and state-line code and data. **Signed off by the owner on 2026-11-18** (the frames and the privacy statement; the sign-off is recorded in [this comment on #833](https://github.com/AnthonyPluth/Waypoint/pull/833#issuecomment-6980482363)). The build follows the plan below, one issue per pull request. The owner has already decided three things (2026-11-18, in chat, recorded on #828):

1. The Trips list cards and the Stats world map load Apple's maps too, instead of the bundled SVG.
2. With no MapKit key, or when Apple's map fails to load, the map and the replay are hidden. There is no fallback renderer.
3. The server's bundled road routing, highway and state-line data, and the code that serves them, are removed. #826 is no longer needed.

The owner answered more questions on this design's pull request (#833) on 2026-11-18; they are under [Owner decisions on #833](#owner-decisions-on-833-2026-11-18), and the sections below follow them.

## Owner decisions on #833 (2026-11-18)

Given in chat on 2026-11-18 while reviewing #833. These answered the questions this design asked; the sign-off of the frames and the privacy statement followed (items 5 to 8).

1. **Cards: Apple's static snapshot, with Waypoint's route drawn on top** (option A). The rest as proposed: only cards near the screen load (lazy), photo cards and one-stop cards never ask Apple, and with no key a card shows today's kinds tile. The new server route that signs snapshot addresses, and Apple's options (the parameters, `expires`, and whether Waypoint may draw on top of a snapshot), stay marked **to confirm with Apple first** in the cards' build issue.
2. **A drive with no road from Apple yet is a straight line. A trip's road distance** is the length of Apple's stored road where there is one, otherwise the straight-line distance, marked "about".
3. **Stats keeps the visited countries and states shading.** The bundled outline data (`world-atlas`, `us-atlas`) stays, and the Stats map is one MapKit map with the visited regions drawn from it as polygon overlays, plus the arcs, dots and pins as before (reworked in [Stats world map](#stats-world-map-frame-b) and frame b).
4. **The demo and docs screenshots: a real MapKit key, stored securely, for the demo** is tracked in [#834](https://github.com/AnthonyPluth/Waypoint/issues/834). Until #834 decides otherwise, the static demo shows no maps and the docs screenshots show the grid stand-in.

Later the same day the owner signed off the design and answered the last questions (recorded in [the sign-off comment on #833](https://github.com/AnthonyPluth/Waypoint/pull/833#issuecomment-6980482363)):

5. **The frames are signed off**: a (Trips cards), b (the Stats map with the visited shading) and c (the replay with no key).
6. **The privacy statement is signed off as written**, including that Apple sees each no-photo trip's city-level area as the list scrolls (so a card's map is never closer than city level, zoom 12) and that Apple's script is handed the visited countries' and states' outlines, which are bundled and never fetched from Apple.
7. **Settings → Travel gets the read-only "Maps" row** (frame c4).
8. **A map failing during a replay shows a short "The map couldn't load" message**: a quiet line where the replay was, also announced politely (frame c3).

The frames are self-contained HTML pages in the style of the other `docs/design/` pages: vector only, Waypoint's tokens from `frontend/src/app.css`, dark only, made-up names and places, and a toggle for phone (390 px) and desktop (1280 px) widths. Apple's map is drawn as a stylised stand-in, because a real tile can't be committed.

| Screen | File | What it shows |
| --- | --- | --- |
| a | [a-trip-cards.html](a-trip-cards.html) | Past trips list cards on Apple's snapshot (decided on #833): a card's map loaded, loading, failed and with no key; the photo card that never asks Apple; how many maps load on a long list; the options that were weighed |
| b | [b-stats-map.html](b-stats-map.html) | The Stats world map on one live MapKit map with the visited countries and states shaded from the bundled outlines (decided on #833): loaded, zoomed into the states, a tapped airport and a tapped state, loading, and the section with no key or a failed map |
| c | [c-replay-no-key.html](c-replay-no-key.html) | A completed trip's page with and without a key (phone and desktop), the replay failing after it started ("The map couldn't load"), and the Settings → Travel "Maps" row that says maps need a key |

Images of each page at phone and desktop width were rendered with Playwright for the owner's review in chat; they are not committed, as the other design pages' images aren't (the pages are vector only).

The inventory, privacy statement, wording changes and build plan below are written against `main` at `ec2271e` plus the open pull request #823 (`feat/warm-driving-routes`), which lands first.

## Accepted departures from frame a (#837, owner decisions on #866, 2026-11-18)

- The card title overlaps Apple's attribution, as drawn in frame a.
- Airport stops use `--map-airport`, other stops `--map-stay`.
- Apple's snapshot zoom is at least 3. A trip that doesn't fit the card at zoom 3 is drawn from a larger image (up to 640 px a side) at zoom 3 shown scaled down; a trip wider still gets a 640 px zoom-3 image centred on the route (across the date line when that is shorter) with its ends clipped at the image's edge. Only fewer than two placeable stops, no key or a failure show the kinds tile.
- A road trip's card area always includes Home, as the replay's does.

## Contents

1. [Owner decisions on #833](#owner-decisions-on-833-2026-11-18) and [what #823 adds](#what-823-adds)
2. [Inventory](#inventory): keep (MapKit), remove, change
3. [How the maps look and load](#how-the-maps-look-and-load)
4. [Privacy: what Apple learns](#privacy-what-apple-learns)
5. [Wording that must change, and the checks that hold it](#wording-that-must-change-and-the-checks-that-hold-it)
6. [make verify and the demo without a real Apple key](#make-verify-and-the-demo-without-a-real-apple-key)
7. [Build plan](#build-plan): five pull requests, each a draft agent-task issue
8. [Open questions for the owner](#open-questions-for-the-owner)

## What #823 adds

PR #823 (nightly route warming) is still open and is treated here as part of the code base. It adds:

- `waypoint/domain/route_warming.py`: the nightly job (midnight server time by default, `WAYPOINT_ROUTE_WARMING_HOUR`) that asks Apple for the driving road of each drive of an ended trip that has no stored road, at most 200 a night, one at a time, stopping for good on a 401 or 403. It finds a trip's stops with `tripmap.stop_places`, not the bundled roads.
- `waypoint/providers/mapkit.py`: a Maps Server API client (`maps-api.apple.com`): a server token signed by the MapKit key (`sign_server`), the access-token exchange, `Directions.route(start, end)` and `parse_path`.
- `waypoint/domain/tripmap.py`: `stop_places`, the trip's airports, cities, stays and Home with empty `roads` and `boundaries`, which skips the bundled road routing (`_locate` is factored out of `places` for it, and `stop_points` uses it too).
- `waypoint/server/jobs.py`: the job's schedule. `tests/test_route_warming.py`, `tests/fixtures/route_stops.json` (the stop rules shared with the web app), Semgrep's `waypoint-apple-maps-server-host` and `waypoint-apple-directions-caller`, and wording in AGENTS.md, SECURITY.md, `invariants.md` 4 and 9, `.env.example` and the configuration, data-sources, trips and email-scanning docs pages.

Because the job already has the server ask Apple for every drive of every ended trip, removing the bundled roads loses less than it would have: most drives will have Apple's road stored before anyone opens them.

## Inventory

**Keep** means the file stays and still does the MapKit job. **Remove** means the file is deleted. **Change** means it stays with the bundled parts taken out or with a new MapKit path. The build step that does each is in the last column (see the [build plan](#build-plan)).

### Server: `waypoint/`

| File | What it does today | Verdict | Step |
| --- | --- | --- | --- |
| `storage/roads.py`, `storage/roads.tsv.gz` (2.2 MB) | The National Highway System network, loaded once; shortest-path routing (`highways().route`), `near`, `locate`, `miles_between`, `MAX_LINK_MILES` | Remove | 1 |
| `storage/states.py`, `storage/states.tsv.gz` (9 KB) | US state lines for the replay's dashed borders (`state_lines().within(extent)`) | Remove | 1 |
| `storage/places.tsv.gz`, `storage/geocode.py`, `storage/reference.py` | ZIP, postal-code and city centres: turn a booking's address into a point when it is saved, the Stats places, Home | **Keep**: MapKit still needs a point for every stop, and the points never come from Apple | none |
| `storage/regions.tsv.gz`, `airports.tsv.gz`, `airlines.tsv.gz` | Reference lists | Keep | none |
| `domain/tripmap.py` | `places` (stops plus `road_legs` and `state_lines`), `_drive`, `_section`, `_retrace`, `_pairs`, `_routes`, `drives`, `road_legs`, `_arc`, `_reach`, `map_extent`, `state_lines`, `PHONE_MAP`/`WIDE_MAP`/`MAP_PADDING`/`MIN_MAP_SPAN`, `MIN_ROAD_TRIP_MILES`, `MAX_DETOUR`, `MIN_RETRACE_SHARE`; and (#823) `_locate`, `stop_points`, `stop_places` | **Change**: keep `_locate`, `stop_points`, `stop_places` (renamed `places`), the TypedDicts without `RoadLeg`, `RoadLine`, `Roads`, `StateLine`; remove the rest | 1 |
| `domain/tripstats.py` | `_road_km` sums `tripmap.drives` (bundled road miles) into a trip's distance, `road_estimated` | **Change**: road distance from the trip's stored Apple roads (`driving_routes`), otherwise the straight line, flagged estimated ("about"; decided on #833) | 1 |
| `domain/driving_routes.py`, `server/api/driving_routes.py`, `storage/migrations/versions/0048_driving_routes.py`, `storage/models.py` (`DrivingRoute`) | The stored Apple roads, per trip and drive | Keep | none |
| `domain/route_warming.py` (#823) | The nightly warming job | Keep | none |
| `domain/maps.py`, `providers/mapkit.py`, `server/api/mapkit.py`, `server/api/state.py` (`mapkit`) | The key, the flag, the browser token, the CSP widening, the Maps Server API client | Keep; **change** `providers/mapkit.py` and `domain/maps.py` to also sign snapshot addresses for the cards (decided on #833; Apple's options to confirm first) | 3 |
| `server/api/trips.py` (`api_trip_places`) | `GET /api/trips/{id}/places` | **Change**: replies with the stops only (`roads` and `boundaries` gone) | 1 |
| `server/contract.py` (`TripPlaces`, `Roads`, `RoadLeg`, `StateLine`), `docs/openapi.json`, `frontend/src/lib/api-types.ts` | The places reply type | **Change**, then `make api-contract` | 1 |
| `server/jobs.py` | Preloads `roads.highways()` and `states.state_lines()` at start-up; (#823) schedules warming | **Change**: drop the preload | 1 |
| `domain/demo.py` (`_keep_a_road`) | Stores one demo drive's road from `tripmap.places(...)["roads"]` | **Change**: store a made-up path between the two stays (a few fixed points), no bundled roads | 1 |
| `server/routes.py` | Route table | Change only if a snapshot route is added (step 3) | 3 |
| `verify.py` (`mapkit_env`, `MAPKIT_*`) | The run's throwaway key for MapKit flows | **Change**: every demo server `make verify` starts gets a MapKit key, except the one for the no-key flows | 2 |

### Tools and data builders

| File | Verdict | Step |
| --- | --- | --- |
| `tools/roads.py`, `tools/states.py` (build the two `.tsv.gz` files) | Remove | 1 |
| `tools/places.py` | Keep | none |
| `NOTICE` (the Highways and State lines paragraphs) | **Change**: drop those two paragraphs; the attribution of the web app's country and state outlines (Natural Earth, Census, through `world-atlas` and `us-atlas`) stays, since Stats keeps them | 1 |
| `pyproject.toml` (`mapkit-alone` import contract) | Keep | none |

### Web app: `frontend/src/`

| File | What it does today | Verdict | Step |
| --- | --- | --- | --- |
| `lib/components/RouteReplayMap.svelte` | The replay: SVG land, roads, state lines, the moving vehicle, labels, camera, controls; hosts `RouteReplayMapKit` when MapKit is up | **Change**: keep the controls, labels, slider and timing; the map area is MapKit only; the SVG `<path>` land, roads and boundary layers go | 2 |
| `lib/components/RouteReplayMapKit.svelte`, `lib/replay-mapkit.ts`, `lib/mapkit.ts`, `lib/driving-routes.ts` | The MapKit replay, the loader and preload, Apple directions and the stored roads | Keep; **change** `replay-mapkit.ts` so a drive with no Apple road yet is a straight line (decided on #833), and `driving-routes.ts`'s `savedRoads` to return the new shape | 2 |
| `lib/components/RouteReplay.svelte` | Fetches places, loads MapKit, picks SVG or MapKit | **Change**: renders nothing unless MapKit loaded (`app.state.mapkit === true` and `loadMapkit()` resolved); `NO_ROADS`/`NO_BOUNDARIES` gone | 2 |
| `lib/route-replay.ts` | Stops, timing, labels and camera (keep); `roadFor`, `retraceFor`, `RETRACE_*`, `ROAD_MATCH_KM`, `boundaryShapes`, `boundariesShown`, `BOUNDARY_MIN_SCALE`, `NO_ROADS`, `NO_BOUNDARIES`, `Boundaries`, `BoundaryShape`, the road `Track`s in `legsOf`, `routeProjection`'s road extent | **Change**: keep what the MapKit replay and the cards use (`stopsOf`, `worthLocating`, `canReplay`, `replayMs`, `legsOf` without roads, `cameraAt`, `positions`, `mercatorFor`'s inputs); remove the road and boundary helpers | 2 |
| `lib/components/RouteTile.svelte`, `lib/components/RouteTileMap.svelte` | The Past card's map: SVG land plus the stops and the stored roads | **Remove** `RouteTileMap`; **change** `RouteTile` to Apple's snapshot with Waypoint's route on top (decided on #833), the kinds tile otherwise | 3 |
| `lib/components/PastTripCard.svelte` | Photo mosaic, else `RouteTile` | Keep (no change but the tile it hosts) | 3 |
| `lib/components/TravelMap.svelte` | The Stats world map: SVG countries and US states shaded when visited, flight arcs, airport dots, stay pins, pan and zoom, tap for trips | **Remove** the SVG renderer; replaced by `StatsMapKit.svelte` (new), which draws the same visited shading as MapKit polygon overlays from the same outlines | 4 |
| `lib/map.ts` | World projection, dots, arcs, pins, zoom and pan, country and state outline loading, visited shading, detail levels | **Change**. **Keep** the data side and the outlines Stats shades from (decided on #833): `loadCountries`, `loadDetailedCountries`, `loadStates`, `US_ID`, `visitedFeatureIds`, `visitedPoints`, `stateSources`, `stateAt`, `visitedStateTrips`, `pins`, `dots` and `arcs` (as latitude and longitude points, not projected), `flownBounds` (as a latitude and longitude box), and a new `toOverlays` that turns a visited feature into MapKit polygon rings. **Remove** the SVG side: `worldProjection`, `MAP_WIDTH`/`MAP_HEIGHT`, `arcPath`, `mapData`, `pieces`, `zoomAt`, `clampPan`, `fitBox`, `IDENTITY`/`MAX_ZOOM`/`Transform`, `outlinePaths`, `kmPerPixel`, `windowOf`, `clipToWindow`, and `loadFineCountries`, `detailFor` and the detail constants unless the build finds the 1:50m outlines too coarse at state zoom | 4 |
| `lib/land.svelte.ts` | Picks coarse, medium or fine land outlines for the SVG view | Remove: Apple draws the land; the shading needs only the visited features, loaded once | 2 (cards and replay stop using it), 4 (last user goes) |
| `pages/Stats.svelte` | Lazy-loads `TravelMap` into `#stats-map-slot` | **Change**: lazy-loads `StatsMapKit` only when `app.state.mapkit === true`; no slot otherwise | 4 |
| `pages/Trips.svelte`, `pages/Trip.svelte`, `lib/components/PastTrip.svelte` | Host the cards and the replay; `PastTrip` lays out the map hero and Replay trip | **Change**: `PastTrip` hides the map hero and the Replay trip button when the replay can't be shown (frames c) | 2 |
| `lib/side-column.ts` | Checks a places reply's shape, including `roads` and `boundaries` | Change | 1 |
| `lib/components/TripSummary.svelte` | "about" before an estimated distance | Keep | none |
| `App.svelte` | Preloads MapKit when idle | Keep | none |
| `lib/offline.svelte.ts`, `pages/Settings.svelte` | `clearRouteCache` on sign-out | Keep | none |
| `lib/components/RouteLine.svelte` | The pass card's flight progress glyph, not a map | Keep | none |
| `test/fake-mapkit.ts` | The Vitest stand-in for `mapkit` | **Change**: add what the cards and Stats need (selection events on annotations and overlays, `PolygonOverlay` with `Style`, `showsZoomControl`, `isScrollEnabled`) | 2, 3, 4 |
| `package.json` | `d3-geo`, `topojson-client`, `world-atlas`, `us-atlas`, `@types/d3-geo`, `@types/topojson-client`, `@types/geojson` | **Keep** `world-atlas`, `us-atlas`, `topojson-client`, `d3-geo` (for `geoContains`, `geoDistance`, `geoInterpolate`) and their types: Stats shades visited regions from them (decided on #833). Nothing else changes here | none |
| `demo/data.json`, `demo/api.ts` | The static demo's canned replies, 11 of them with `roads` and `boundaries` | **Change**: regenerate | 1 |

### Web app tests

| File | Verdict | Step |
| --- | --- | --- |
| `lib/route-roads.test.ts`, `lib/route-boundaries.test.ts`, `components/RouteReplayRoads.svelte.test.ts`, `components/RouteReplayBoundaries.svelte.test.ts`, `lib/land.svelte.test.ts` | Remove (with a `Removes-Test:` trailer naming the removed code) | 2, 4 |
| `components/TravelMap.svelte.test.ts` | Remove with `TravelMap.svelte`; its visited-shading cases (which countries and states are shaded, a tap on one lists its trips) move to the new `StatsMapKit.svelte.test.ts` | 4 |
| `components/RouteReplayMap.svelte.test.ts`, `RouteReplay.svelte.test.ts`, `RouteReplayCompact.svelte.test.ts`, `RouteReplayHome.svelte.test.ts`, `RouteReplayHidden.svelte.test.ts`, `lib/route-replay.test.ts`, `lib/route-replay-home.test.ts` | Change: drive them through the fake MapKit; the SVG-map cases become "hidden with no key" and "hidden when MapKit fails" | 2 |
| `components/RouteReplayMapKit.svelte.test.ts`, `lib/replay-mapkit.test.ts`, `lib/mapkit.test.ts`, `lib/driving-routes.test.ts`, `App.svelte.test.ts` ("preloading MapKit") | Keep; change the "keeps the bundled line" cases to "draws a straight line" | 2 |
| `components/RouteTile.svelte.test.ts`, `PastTripCard.svelte.test.ts`, `PastTrip.svelte.test.ts`, `pages/Trips.svelte.test.ts`, `pages/Trip.svelte.test.ts`, `pages/Upcoming.svelte.test.ts`, `lib/side-column.test.ts`, `components/TripSummary.svelte.test.ts` | Change (places fixtures lose `roads`/`boundaries`; cards on MapKit) | 1, 2, 3 |
| `lib/map.test.ts` | Change: keep the outline, visited and state-source cases; drop the projection, zoom and pan cases | 4 |
| `pages/Settings.svelte.test.ts` | Change: the "Maps" row (decided on #833) | 5 |

### Python tests

| File | Verdict | Step |
| --- | --- | --- |
| `tests/test_roads.py`, `tests/test_trip_roads.py`, `tests/test_states.py`, `tests/test_trip_states.py` | Remove (`Removes-Test:` trailer) | 1 |
| `tests/test_geocode.py` | Keep (the stranger's 404 on the places route moves here or stays in `test_trips.py`) | none |
| `tests/test_trips.py`, `tests/test_tripstats.py`, `tests/test_trip_summary.py`, `tests/test_route_cache.py`, `tests/test_route_warming.py`, `tests/test_demo.py`, `tests/test_api_contract.py`, `tests/test_mail_cars.py`, `tests/test_mail_generic_kinds_scan.py` | Change (no `roads`/`boundaries`; the road distance from stored roads) | 1 |
| `tests/test_mapkit.py`, `tests/test_api_state.py`, `tests/test_mcp_routes.py`, `tests/test_migrations.py`, `tests/test_every_route.py` | Keep; extend `test_mapkit.py` for snapshot signing if chosen | 3 |
| `tests/test_verify.py` | Change (every server has a key; the no-key server) | 2 |

### Checks and promises

| Item | Verdict | Step |
| --- | --- | --- |
| AGENTS.md, "You see the trips you're on" (the bundled-data sentence, "one case only: the route replay's map", "the replay is the bundled SVG map", "a failed call silently leaves the bundled line", "The Stats map is never drawn by MapKit", the checks list naming `test_roads.py`, `test_trip_roads.py`, `test_states.py`, `test_trip_states.py`, `RouteTile.svelte.test.ts`) | Change ([wording](#wording-that-must-change-and-the-checks-that-hold-it)) | 5 |
| AGENTS.md, "Private data in logs" (the MapKit parenthesis) | Keep | none |
| SECURITY.md, "MapKit (optional)" | Change | 5 |
| `.github/agent-review/invariants.md` 4 (the bundled-data checks; "the route replay's map"; "the SVG map, which any MapKit failure also falls back to") and 9 | Change | 5 |
| Semgrep `waypoint-mapkit-hosts`, `waypoint-apple-maps-server-host`, `waypoint-apple-directions-caller` | Keep | none |
| New check: no bundled map data or renderer comes back | Add ([checks](#the-checks-that-hold-the-new-promises)) | 2, 4 |
| `docs/PHOTOS.md` ("Waypoint's maps stay vector, drawn from bundled data"; the Map and Stats paragraphs naming `tripmap.road_legs`) | Change | 5 |
| `docs/design/mapkit-spike.md` | Keep as history; add a status line pointing here | 5 |
| `docs/design/trips/README.md` (the Past card's fallback: "a route map in place of the photo mosaic") and `docs/design/photos/*` map frames | Keep; add a line that this design supersedes the bundled map in them | 5 |

### User docs (`docs/src/content/docs/`)

| Page | What changes | Step |
| --- | --- | --- |
| `start/trips.md` ("Replaying a past trip's route", "Apple's map for the route replay", the Past card's route map, "Where a booking is on the map") | Maps need a MapKit key; no key, no map or replay; the cards and Stats load Apple's map; what Apple learns from each | 5 |
| `start/stats.md` ("The map is drawn on your device from outlines bundled with the app ... calls no map service") | Rewritten for MapKit | 5 |
| `start/docker.md` ("the trip map are bundled and need no connection") | Rewritten | 5 |
| `reference/data-sources.md` (Highways, State lines; "five reference lists") | The two sections go; three lists | 1 |
| `reference/configuration.md` (`WAYPOINT_MAPKIT_*`: "the route replay's map") | Every map | 5 |
| `privacy/email-scanning.md` ("so the Stats map can show where you stayed"; what leaves the server) | Stats map is Apple's when a key is set | 5 |
| `README.md` ("Brand logos and the map are bundled"; "no logo or map service (unless you add a MapKit key...)") | Rewritten | 5 |
| `contributing/feature-map.md`, `docs/feature-map.json`, `.claude/skills/verify-waypoint/references/feature-map.md` | Regenerated (`make feature-map`, `make user-feature-map`) | each step |
| Screenshots in `docs/src/assets/screenshots/` that show a map (`stats-*`, `trips-*`, `trip-*`) | Regenerated by `make verify` with the grid stand-in, unless #834 (a real MapKit key, stored securely) decides otherwise | 2, 3, 4 |

### `make verify` flows and the demo

| Item | Verdict | Step |
| --- | --- | --- |
| `frontend/verify/fake-mapkit.js`, `fake-mapkit-error.js`, `verify.mjs` (`standInForApple`, `MAPKIT_MODES`), `control-daemon.mjs` (the `needs_mapkit` refusal) | **Change**: the stand-in is used by every flow by default; add a snapshot stand-in if snapshots are chosen; `tools/control` starts its server with a run key so it can run them | 2, 3 |
| `trip-route-replay.json`, `trip-route-replay-backtrack.json`, `home-route-replay.json` (SVG replay) | Change: run on the stand-in | 2 |
| `trip-route-replay-mapkit.json` | Keep | none |
| `trip-route-replay-mapkit-fallback.json`, `trip-route-replay-mapkit-blocked.json` (show the fall-back to the flat map) | Change: show the replay hidden | 2 |
| New `trip-route-replay-no-key.json` | Add: a completed trip on the no-key server, no map, no Replay trip | 2 |
| `past-trips-list.json`, `past-trip-saved-route.json` (`svg g[fill=...]` selectors), `past-trip-page.json`, `past-trip-page-desktop.json`, `trips-widths.json` | Change: the stand-in map | 3 |
| New `past-trips-list-no-key.json`, `past-trips-list-map-failed.json` | Add | 3 |
| `open-stats.json`, `stats-map-details.json`, `stats-map-zoom.json`, `stats-long-names.json`, `hotel-stats.json`, `parking-stats.json` | Change: the stand-in map, MapKit's own zoom control | 4 |
| New `stats-no-key.json`, `stats-map-failed.json` | Add | 4 |
| `frontend/verify/flows/README.md` (the `mapkit` key) | Change: `mapkit` becomes `"none"`, `"error"` or `"blocked"`, the stand-in being the default | 2 |
| `demo/README.md`, `demo/verify.mjs`, `frontend/demo/` | Change: the static demo has no key, so no maps and no replay, until #834 gives it a real key stored securely | 2 |

## How the maps look and load

### The rule for every map

A map is shown only when all of these hold; otherwise its place on the page is not there at all (not an empty box, not a message):

1. The server reports MapKit (`GET /api/state` → `mapkit: true`: a key, `WAYPOINT_PUBLIC_URL`, the flag not off).
2. The viewer is online and signed in (the offline copy and the static demo never load Apple's script).
3. The map has something to show: a card or a replay needs at least two stops Waypoint can place; Stats needs at least one airport, stay or place in the chosen period.
4. Apple's map loaded within `LOAD_MS` (6 s) and hasn't failed since.

Because 1 to 3 are known before anything is asked of Apple, a page with no key never reserves space and never shifts. Only 4 can take a map away after its slot appeared: the slot then collapses. The frames show each case.

### Trips list cards (frame a)

**Which cards get a map.** Only a Past card with no photos the viewer may see, and a route of two or more stops. A card with photos keeps its mosaic and never asks Apple for anything. A card with no placeable route keeps today's plain tile with the trip's kind icons. With no key, or when the card's map fails, the card shows that same kinds tile, so "map hidden" on a card means "the tile it shows today for a trip it can't place".

**Options weighed.**

| | A. Apple static snapshot (decided on #833) | B. Live MapKit map per card | C. Live map, one at a time |
| --- | --- | --- | --- |
| What it is | An image from Apple's Maps Web Snapshots service, for the trip's area, at the card's size; Waypoint draws the route and stops on top in SVG | A `mapkit.Map` in each card, non-interactive, with the stops as annotations and the route as a polyline | Snapshots as in A, and the one card under the pointer or in the middle of the screen swaps to a live map |
| Scrolling | Smooth: an `<img>` with `loading="lazy"`, decoded off the main thread | Each map is a WebGL renderer, a worker and a few MB of memory; more than four or five on a phone janks and can lose the WebGL context | As A, plus a swap that can flash |
| How many load | The cards near the screen: the browser's lazy loading (about one screen ahead) and the year-at-a-time list; one image request each, cached by the browser | Must be limited by hand (create at most 4 live maps, destroy off-screen ones), so a fast scroll shows blank tiles | As A |
| Apple's allowance per day | 25,000 unique snapshots | 250,000 map views | both |
| What Apple is sent | The area (centre and zoom) and the image size, from the viewer's browser; no stop and no path (Waypoint draws them) | The tiles of the area, from the viewer's browser; Apple's script is handed the stops and the path to draw | both |
| Server work | Signs each snapshot address with the MapKit key (a new route, sign-in, visibility, blocked for assistants) | None new | As A |
| Needs Apple's script | No (a card's map shows even before MapKit JS is preloaded) | Yes | Yes |
| Looks | A real Apple map, in the dark style, without Apple's live labels changing as you scroll | The real thing | A |

**Decided on #833 (2026-11-18): A**, with Waypoint drawing the route line and stops on Apple's image in its own map tokens (`--map-route`, `--map-stay`, `--map-airport`), using the stored Apple road for a drive when there is one and a straight line otherwise. It scrolls like today's cards, sends Apple less than a live map would and doesn't depend on Apple's script being loaded. Apple's snapshot terms and parameters (marked **confirm** below) are to be confirmed with Apple before step 3 builds it.

**Snapshot details, each to confirm with Apple before step 3** (including whether Waypoint may draw on top of a snapshot).

- Address: `https://snapshot.apple-mapkit.com/api/v1/snapshot?center=<lat>,<lon>&z=<zoom>&size=<w>x<h>&scale=2&colorScheme=dark&poi=0&lang=<viewer's>&teamId=…&keyId=…&signature=…` (**confirm** the parameter names, and that `annotations` and `overlays` can be left out). No `annotations` and no `overlays`: the stops and the path never go in the address.
- Signed on the server with the MapKit key over the path and query (ES256), by a new `providers/mapkit.py` function and a batched route for the cards on screen, `GET /api/map-snapshots?trip=…` (at most 12, like `GET /api/driving-routes`): sign-in required, blocked for assistants, the trips you can't see left out exactly as a trip with no route is, never logging the key, Key ID or Team ID. **Confirm** whether Apple accepts an `expires` parameter; if so, addresses last a day.
- Centre and zoom come from the trip's stops fitted to the card (the same fit the card uses today), with the zoom capped at 12 so a card never shows street level around a stay or Home. The area is the only thing derived from the trip that leaves the browser.
- The server keeps the signed address per trip and size for a day in memory, so the browser's cache gets the same address twice and Apple counts one unique snapshot.
- The image is loaded with `referrerpolicy="no-referrer"`. The CSP's `img-src` already allows `https://*.apple-mapkit.com` while MapKit is active.

**Loading and failure (frame a, cards 2 and 3).** While the image loads the card shows the kinds tile with the icons at half strength; the image fades in over 200 ms (no fade for reduced motion), and the route draws with it. If the address can't be had or the image errors (Apple refuses, the network drops, the allowance is spent), the card stays on the kinds tile at full strength, without a message, and is not retried until the page is reloaded.

**How many maps on a long list.** On phone the list shows the newest year and loads the next year near the bottom; on desktop every year. Either way only cards within about a screen of the viewport request an image (`loading="lazy"`), and the batch route asks for the cards on screen, 12 at a time. A household with 150 past trips, half with photos, that scrolls the whole list loads at most 75 images, once each per day.

### Stats world map (frame b)

One live MapKit map: the map is the point of the section, it is one per page, and pan and zoom are expected. It replaces `TravelMap.svelte` in `#stats-map-slot`, lazy-loaded as today. The visited shading stays (decided on #833), drawn by MapKit from Waypoint's bundled outlines.

- **What it draws.** Apple's dark style with points of interest off; then, as overlays, from the bottom up: the visited countries filled in `--map-visited` at about 35% with a 1 px edge at 70%; the visited US states, once the map is zoomed in far enough for states to read (a span under about 40° of longitude), filled the same way and the United States' own fill dropped so states don't double up; the flights as great-circle polylines whose width follows the number of flights (`--map-route`); the airports as dots sized by visits (`--map-airport`); the stays as small pins (`--map-stay`).
- **How the shading is drawn.** MapKit JS draws polygons itself: `mapkit.PolygonOverlay` takes rings of coordinates (several rings for islands and holes) and a `mapkit.Style` (`fillColor`, `fillOpacity`, `strokeColor`, `strokeOpacity`, `lineWidth`); `mapkit.importGeoJSON` can build the same overlays from GeoJSON. The countries come from `world-atlas`'s 1:50m file (`loadDetailedCountries`), the states from `us-atlas` (`loadStates`), both converted with `topojson-client` in the browser, from the app's own lazily loaded files (same origin, never from Apple). Only the visited features become overlays (a household's few countries and states, not the world), which keeps MapKit's work small. Which are visited is worked out as today (`visitedFeatureIds`, `visitedStateTrips` with `geoContains`). **Confirm** while building: that MapKit JS keeps overlays with a few thousand vertices smooth on a phone (if not, use the 1:110m countries at world zoom), that overlay selection (`select` events on overlays) works as for annotations, and how overlays sit under annotations.
- **Fit.** Fitted to the period's airports, stays and places, as `flownBounds` does today, capped so a single city doesn't zoom past city level.
- **Interaction.** MapKit's own zoom control (+ and −) replaces Waypoint's buttons. One-finger drag pans only after zooming in on a phone (`isScrollEnabled` turned on at the first zoom), so the page still scrolls past the map, as today. A tap on a dot, arc, pin, shaded country or shaded state selects it and shows the same caption under the map as today (the place, then each trip with its dates).
- **Loading.** The skeleton the slot has today ("Loading the map", `h-56`, pulsing unless reduced motion) until MapKit, the outlines and the first tiles are up; then the map. If the outlines fail to load, the map shows without shading (as today's map shows without states when they fail), since the tiles and the countries list still say where you've been.
- **No key or failure.** The section keeps its heading "Where you've been", the Countries and States tiles and the countries and states lists; the map slot is not there, and the outlines are not loaded. A failure after the map showed collapses the slot.

### The replay (frame c)

With a key nothing changes from today's MapKit replay, except that a drive with no stored Apple road and no answer from Apple's directions is a straight line instead of the bundled highway line (decided on #833).

With no key, or when MapKit fails before the replay starts:

- **Phone, fewer than three photos** (the map hero, owner decision of 2026-11-16): the title and dates, then the quiet line "No photos yet", then the facts line. No map and no Replay trip.
- **Phone, three or more photos**: the mosaic hero and the facts line, without Replay trip.
- **Desktop**: the left column is the facts and the bookings list; the map block and Replay trip are not there.
- **MapKit fails during a replay**: the replay's block closes (its controls go with it), focus moves to the facts line's heading if it was inside the replay, and a short quiet line, "The map couldn't load", takes its place, in a polite live region (decided on #833). Nothing else is announced, and nothing is shown for a failure before the map appeared.

### Where it says maps need a key (frame c, c4)

- **Docs**: "Trips" and "Stats" each open their map section with "Maps need a MapKit key on the server. Without one Waypoint shows no maps or route replays", linking to "Apple's map" in the Trips page.
- **Settings (decided on #833)**: a read-only row in Settings → Travel, "Maps", reading "Apple Maps" with a "What Apple learns" link when MapKit is active, and "Off: this server has no MapKit key" with a "How to turn on maps" link otherwise. The app has no switch for it: the key and the flag stay server settings.

## Privacy: what Apple learns

This replaces "a trip's coordinates go to an outside service in one case only: the route replay's map". It is written for the owner to sign off; the wording changes below carry it.

**Without a key** (or the flag off, or no `WAYPOINT_PUBLIC_URL`): nothing is loaded from or sent to Apple, the CSP names no Apple host, and Waypoint shows no maps and no replay. Everything else works.

**With a key**, as today: Apple's script loads on every signed-in app open (idle preload, #759), unpinned, running in the page with the app's own access, and Apple learns the viewer's IP address and browser and this Waypoint's address on every open; the replay sends the area on screen and each drive's start and end to Apple's directions service; the server asks Apple for the roads of ended trips once a night (#823). In addition:

- **A Trips list.** For each Past card that has no photos the viewer may see and a route of two or more stops, and that scrolls within about a screen of view, the viewer's browser asks Apple for a map image of the trip's area: its centre and zoom (no closer than city level) and the image's size, signed for this Waypoint. Apple can tie the requests of one page load together, so it learns, from the viewer's IP address, the rough areas of the household's past trips that have no photos, a few at a time, as the list scrolls. It is not sent the stops, the stays, Home, the path, a name, a date or which trip is which. A card with photos asks nothing. 
- **Stats.** Opening Stats draws one live map, fitted to the chosen period's airports, stays and places. Apple learns the area on screen and every area the viewer pans or zooms to, down to street level if they zoom that far, from the tiles. Apple's script is handed every airport, flight arc and stay pin of the period to draw, and the outlines of the visited countries and US states to shade, and, as everywhere with MapKit, could read them, so it could learn which countries and states the household visited in the period. The outlines themselves are bundled with the app and loaded from this Waypoint, never fetched from Apple or anyone else; Waypoint doesn't send any of this anywhere itself.
- **The replay with no road yet.** Unchanged: the browser asks Apple's directions service once per drive and stores the answer; a drive with no answer is a straight line.

What stays true: the server sends Apple trip data only through the nightly warming job's drive ends (#823) and, with snapshots, the signed address it hands the browser (the area only; the server itself never fetches the image). A trip or card you can't see is never drawn, signed or asked about. No map is drawn for a trip with fewer than two stops. Photo places never widen or join a map.

Compared with today: Apple newly learns the rough area of every past trip without photos when the list is scrolled (today only a replayed trip's area), and the whole period's travel area, airports, flights, stays and visited countries and states when Stats is opened (today nothing from Stats).

## Wording that must change, and the checks that hold it

The exact text is settled in step 5 against `main` as it is then; what each passage must say is fixed here. Every passage keeps the owner's decisions it cites today (#530, #630, #754, #759, #829).

### AGENTS.md, "You see the trips you're on"

- Replace "The map's places, highways and state lines are bundled data read from disk (`waypoint/storage/places.tsv.gz`, `waypoint/storage/roads.tsv.gz`, `waypoint/storage/states.tsv.gz`); a trip's coordinates, road legs and the state lines near them reach the browser only in the visibility-checked `GET /api/trips/{id}/places` reply, and go to an outside service in one case only: the route replay's map, when a MapKit key is configured…" with: "A booking's point is found from bundled data read from disk (`waypoint/storage/places.tsv.gz`), never from Apple; a trip's stops reach the browser only in the visibility-checked `GET /api/trips/{id}/places` reply, and go to an outside service only through Apple's MapKit, when a MapKit key is configured…, for three maps: the route replay, a Past trips card with no photos the viewer may see, and the Stats map (the owner's decisions on #828, 2026-11-18)."
- Add the list and Stats paragraphs of the [privacy statement](#privacy-what-apple-learns), after the replay's.
- Replace "With no key, a key that doesn't load, no `WAYPOINT_PUBLIC_URL` or the flag turned off, all map data stays on the server and in the browser, the Content-Security-Policy names no Apple host and the replay is the bundled SVG map; a MapKit script that doesn't load, a token that can't be had or any later MapKit error puts the replay back on the SVG map. The Stats map is never drawn by MapKit." with: "With no key, no `WAYPOINT_PUBLIC_URL` or the flag turned off, nothing is loaded from or sent to Apple, the Content-Security-Policy names no Apple host, and no map and no replay is shown (the owner's decision on #828: no fallback renderer); a MapKit script that doesn't load, a token or snapshot address that can't be had, or a later MapKit error hides that map, and a card shows its kinds tile."
- Replace "a call that fails, times out or returns nothing silently leaves the bundled line for that drive" with "…leaves a straight line for that drive" (decided on #833).
- In "Checked:", replace "the map's data is read from disk and the server sends nothing out for it, and a stranger gets a 404 (`tests/test_geocode.py`, `tests/test_roads.py`, `tests/test_trip_roads.py`, `tests/test_states.py`, `tests/test_trip_states.py`)" with "a booking's point is read from disk and a stranger gets a 404 for a trip's places (`tests/test_geocode.py`, `tests/test_trips.py`)"; and add the new checks below. Replace `RouteTile.svelte.test.ts`'s parenthesis ("a saved road drawn on a Past trips card only for its exact drive") with what the new card test holds.

### SECURITY.md, "MapKit (optional)"

- "the route replay's map is Apple's" → "every map in Waypoint is Apple's (the route replay, the Past trips cards without photos, the Stats map), and without a key there are no maps".
- Add after the replay's sentence: "A Past trips list asks Apple for an image of each card's area (its centre and zoom, no closer than city level; never its stops or path) as the cards scroll into view, so Apple learns the rough areas of past trips without photos; Stats draws a live map of the period's travel, so Apple learns the areas shown and Apple's script is handed the period's airports, flights and stays, and the outlines of the visited countries and states (bundled with the app, never fetched from Apple), to draw."
- "a failed call keeps the bundled line" → "a failed call leaves a straight line".
- "Without a key, or with `WAYPOINT_MAPKIT_ENABLED=off`, nothing is loaded from or sent to Apple and the content security policy names no Apple host." → add "and Waypoint shows no maps".

### `.github/agent-review/invariants.md`

- 4: "the map's data read from disk with a stranger's 404 (`tests/test_geocode.py`, `tests/test_roads.py`, `tests/test_trip_roads.py`, `tests/test_states.py`, `tests/test_trip_states.py`)" → "a booking's point read from disk and a stranger's 404 for a trip's places (`tests/test_geocode.py`, `tests/test_trips.py`)". "A trip's coordinates go to an outside service in one case only: the route replay's map" → "…only through Apple's MapKit, for the replay, the Past trips cards without photos (the area only) and the Stats map". "With no key or the flag off nothing goes to Apple, the Content-Security-Policy names no Apple host and the replay is the SVG map, which any MapKit failure also falls back to." → "With no key or the flag off nothing goes to Apple, the Content-Security-Policy names no Apple host and no map is shown; any MapKit failure hides that map." Held by: add the new checks.
- 9: add the snapshot address to the server's MapKit work ("signs a snapshot address for a card's area, and never fetches it").

### User docs

Listed in the [inventory](#user-docs-docssrccontentdocs). The new sentence each map section opens with: "Maps need a MapKit key on the server. Without one Waypoint shows no maps or route replays."

### The checks that hold the new promises

| Promise | Check (new unless marked) |
| --- | --- |
| No bundled map renderer or road data comes back; the outlines stay data for Apple's map | Semgrep `waypoint-no-bundled-map`: no `geoPath(`, `geoEqualEarth(` or `geoMercator(` in `frontend/src/` (Waypoint no longer projects or draws land), `world-atlas`, `us-atlas` and `topojson-client` imported only in `frontend/src/lib/map.ts`; no `roads.tsv`, `states.tsv`, `highways(` or `state_lines(` in `waypoint/` and `tools/`. With examples under `.semgrep/examples/` |
| No key: no map, nothing asked of Apple | `RouteReplay.svelte.test.ts`, `RouteTile.svelte.test.ts`, `StatsMapKit.svelte.test.ts`: with `mapkit: false` no map element, no `loadMapkit()`, no snapshot request, and the slot isn't in the DOM; `tests/test_mapkit.py` (kept): the CSP names no Apple host |
| A failed map hides itself | The same suites with the fake failing to load, refusing a token and raising later; the verify flows `*-map-failed` and `trip-route-replay-mapkit-blocked` |
| A card with photos or fewer than two stops never asks Apple | `RouteTile.svelte.test.ts` and `PastTripCard.svelte.test.ts`: no snapshot request, no `mapkit.Map` |
| A snapshot address carries the area only | `tests/test_map_snapshots.py`: the signed query has exactly `center`, `z` (at most 12), `size`, `scale`, `colorScheme`, `poi`, `lang`, `teamId`, `keyId`, `signature` (and `expires` if Apple has it), no stop coordinate of the trip (canaries); sign-in, blocked for assistants, a trip you can't see left out, `no_leaks` with the key, Key ID and Team ID as canaries; the route held by `tests/test_every_route.py` |
| Only the MapKit provider names Apple's hosts or signs for Apple | Semgrep `waypoint-mapkit-hosts`, `waypoint-apple-maps-server-host` (kept; the snapshot host matches the first) |
| The replay's drive without a road is a straight line | `replay-mapkit.test.ts` (changed case) |
| Stats hands Apple no more than it draws | `StatsMapKit.svelte.test.ts`: the fake records what it is handed; only the period's airports, arcs and stays and the visited countries' and states' outlines (never an unvisited one), and no names but the labels the caption already shows; the outlines are requested from the app's own origin only |
| Nothing reaches Apple in `make verify` | `verify.mjs`: every `*.apple-mapkit.com` and `maps-api.apple.com` request is answered by the run or aborted, and any request to another outside host fails the run (kept, extended to the snapshot host) |

## make verify and the demo without a real Apple key

**`make verify`** already runs MapKit flows without Apple: `waypoint/verify.py` makes a throwaway EC key for the run (`mapkit_env`), the demo server signs real tokens with it, and `frontend/verify/verify.mjs` answers every request to `*.apple-mapkit.com` itself (`standInForApple`): `fake-mapkit.js` is a stand-in `mapkit` that draws a plain grid with the app's annotations and polylines. The change:

- The stand-in becomes the default for every flow. Each demo server `make verify` starts (local, signed-in) gets a run key, so every page with a map shows the stand-in; a flow sets `"mapkit": "none"` to run on a server with no key, or `"error"`/`"blocked"` for the failures.
- A snapshot stand-in: `verify.mjs` answers `snapshot.apple-mapkit.com/api/v1/snapshot` with a PNG it draws at the requested size (the stand-in's grid in the map tokens and a small "Map stand-in" label), and fails the flow if the address carries anything but the allowed parameters.
- The stand-in gains what the cards and Stats use: annotation and overlay selection, `PolygonOverlay` (drawn as filled shapes on the grid, so the shading shows in the images), the zoom control, `isScrollEnabled`.
- `tools/control start` starts its demo server with a run key and the stand-in too, so a session can drive these pages (today it refuses MapKit flows with `needs_mapkit`).
- The network stays closed: the demo server has `HTTPS_PROXY` pointed at nowhere (`NO_OUTSIDE`), the warming job never runs during a verify (it is at midnight and needs Apple), and the browser's outside requests are answered or aborted.
- Vitest uses `frontend/src/test/fake-mapkit.ts`, extended the same way; Python tests sign with a key made in the test.

**The static demo** (`frontend/demo/`, GitHub Pages) has no server and no key, and must make no request. With MapKit only it shows no maps and no replay: the Past cards without photos show their kinds tile, Stats has no map, and a completed trip has no Replay trip. `demo/README.md` stops listing "Stats and travel maps" and "animated route replays", and `demo/verify.mjs` checks that no map is drawn and no Apple host is asked. Shipping the stand-in in the public demo would show a grid where a map should be, so it is not proposed. The owner wants the demo to use real MapKit maps with a real key stored securely: that is [#834](https://github.com/AnthonyPluth/Waypoint/issues/834) (decided on #833). Until #834 lands, the demo shows no maps; when it does, the demo's maps follow whatever #834 settles, and step 2's demo changes are revisited there.

**Docs screenshots** that show a map are regenerated by `make verify`, so they keep showing the grid stand-in unless #834 decides otherwise (decided on #833).

## Build plan

Five pull requests, in this order, each leaving `main` green (`make check`, CI, `make verify`). Steps 3 and 4 can be built in parallel once 2 has merged. The issues were created on 2026-11-18 from the drafts below: #835, #836, #837, #838 and #839; the issues are the source of truth from now on. The demo's real MapKit key is #834, outside this plan.

Waypoint's `CLAUDE.md` routes build work to Sonnet, including the security- and privacy-sensitive work, held by the checks and Codex's review; Opus only after Sonnet misses or for a design decision left open. Every decision a step needs is settled here or in the owner's answers, so each issue names Sonnet. The vendored `fleet-agent-task` skill says Opus by default; Waypoint's `CLAUDE.md` overrides it.

### Step 1 (#835): Remove the server's road routing and state lines

**Context**
The owner decided on #828 (2026-11-18) to remove the bundled road routing and highway and state-line data and the code that serves them (design: `docs/design/mapkit-only/README.md`, signed off on #833). Today `waypoint/domain/tripmap.py`'s `places` adds `road_legs` (routing over `waypoint/storage/roads.tsv.gz` via `storage/roads.py`) and `state_lines` (`storage/states.tsv.gz` via `storage/states.py`) to `GET /api/trips/{id}/places`, about 24 s for a 112-stay trip (#826). `domain/tripstats.py`'s `_road_km` sums `tripmap.drives` for a trip's distance. `server/jobs.py` preloads both files. #823 added `tripmap.stop_places`, the stops without roads, which the warming job uses.

**Scope**
- Delete `waypoint/storage/roads.py`, `storage/roads.tsv.gz`, `storage/states.py`, `storage/states.tsv.gz`, `tools/roads.py`, `tools/states.py`.
- `domain/tripmap.py`: remove `_drive`, `_section`, `_retrace`, `_pairs`, `_routes`, `drives`, `road_legs`, `_arc`, `_reach`, `map_extent`, `state_lines`, the layout and road constants, and the `RoadLeg`, `RoadLine`, `Roads`, `StateLine` types; `places` becomes what `stop_places` returns without `roads` and `boundaries`; keep `stop_places` as an alias only if #823's code still calls it, otherwise rename the callers.
- `domain/tripstats.py`: road distance is the length of the trip's stored Apple road for each drive (`domain/driving_routes.py`, the rows whose ends are still the trip's stops) and the great-circle distance otherwise, with `road_estimated` true when any drive used the great circle. Drives are the car legs the replay draws (the rule in `tests/fixtures/route_stops.json`).
- `server/contract.py` `TripPlaces` without `roads` and `boundaries`; run `make api-contract` (updates `docs/openapi.json`, `frontend/src/lib/api-types.ts`); update the web app's readers of those two fields to compile (`lib/route-replay.ts`, `lib/side-column.ts`, `lib/driving-routes.ts`, `RouteReplay.svelte`, `RouteTile.svelte`, `RouteTileMap.svelte`, `replay-mapkit.ts`), feeding them an empty road list so the bundled map draws straight lines until step 2.
- `server/jobs.py`: drop the preload. `domain/demo.py` `_keep_a_road`: store a fixed made-up path of a few points between the two stays.
- Regenerate `frontend/demo/data.json` as `demo/README.md` says.
- `NOTICE`: remove the Highways and State lines paragraphs. `reference/data-sources.md`: remove the Highways and State lines sections, "three reference lists".
- AGENTS.md and `invariants.md` 4: replace the bundled-data sentence and the removed tests in the checks lists as `docs/design/mapkit-only/README.md` ("AGENTS.md, You see the trips you're on", first and last items) says; nothing else in the promise changes in this step.

**Out of scope**
The web app's renderer (#836), the cards (#837), Stats (#838), the rest of the wording (#839), the warming job (#823).

**Acceptance criteria**
- [ ] `git ls-files waypoint/storage tools | grep -E 'roads|states'` prints nothing.
- [ ] `GET /api/trips/{id}/places` for a 112-stay demo trip answers in under 1 s in a test (`tests/test_trips.py`), and a stranger gets a 404.
- [ ] A trip's distance uses a stored road's length when one is stored and is marked estimated otherwise (`tests/test_tripstats.py`, `tests/test_trip_summary.py`).
- [ ] `make check` and `make verify` pass; the verify images of the replay show straight drive lines on the bundled map (expected until step 2).
- [ ] The commit removing the four test files carries a `Removes-Test:` trailer naming the removed code.

**Tests**
Remove `tests/test_roads.py`, `tests/test_trip_roads.py`, `tests/test_states.py`, `tests/test_trip_states.py`. Change `tests/test_trips.py`, `tests/test_tripstats.py`, `tests/test_trip_summary.py`, `tests/test_route_cache.py`, `tests/test_route_warming.py`, `tests/test_demo.py`, `tests/test_api_contract.py`, `tests/test_mail_cars.py`, `tests/test_mail_generic_kinds_scan.py` and the web app tests whose places fixtures carry `roads` or `boundaries`. Run `make check`, `make verify`.

**Depends on**
#823; the owner's sign-off on #833 (2026-11-18), which also decided the distance rule.

**Model**
Sonnet: removal and a settled distance rule (Waypoint `CLAUDE.md`).

### Step 2 (#836): Remove the bundled renderer from the replay; hide it with no key

**Context**
After #835, the replay (`frontend/src/lib/components/RouteReplayMap.svelte`) still draws bundled land outlines (`lib/land.svelte.ts`, `world-atlas`) and falls back to them whenever MapKit is off or fails. The owner decided on #828 that with no key or a failing MapKit the replay is hidden. Design: `docs/design/mapkit-only/README.md` and frame c (`c-replay-no-key.html`), signed off on #833.

**Scope**
- `RouteReplay.svelte` renders nothing unless `app.state.mapkit === true`, the viewer is online and `loadMapkit()` resolved with a working map; a later failure replaces the block with a short quiet line, "The map couldn't load" (`text-sm text-muted-foreground` in a rounded, dashed `border-border` box, as frame c3 draws it; in a polite live region; decided on #833), moves focus to the facts heading if it was inside, and the line goes when the page is left.
- `RouteReplayMap.svelte`: the map area is `RouteReplayMapKit` only; remove the SVG land, road, interstate and boundary layers; keep controls, labels, slider, timing and the vehicle.
- `lib/route-replay.ts`: remove `roadFor`, `retraceFor`, `RETRACE_*`, `ROAD_MATCH_KM`, `boundaryShapes`, `boundariesShown`, `BOUNDARY_MIN_SCALE`, `NO_ROADS`, `NO_BOUNDARIES`, `Boundaries`, `BoundaryShape` and road tracks; `replay-mapkit.ts` draws a drive with no Apple road as a straight line (decided on #833).
- `PastTrip.svelte`: with no replay possible, the phone map hero becomes the title, dates, "No photos yet" and the facts; Replay trip is not offered; the desktop left column has no map block (frames c1 to c3).
- `RouteTileMap.svelte` and `land.svelte.ts` stay until #837 and #838 (the cards and Stats still use them).
- `make verify`: every demo server gets a run key (`waypoint/verify.py`), the stand-in (`frontend/verify/fake-mapkit.js`) answers by default, `mapkit` in a flow becomes `"none"`, `"error"` or `"blocked"` (`frontend/verify/verify.mjs`, `flows/README.md`); `tools/control start` gets a run key and the stand-in, dropping the `needs_mapkit` refusal (`frontend/verify/control-daemon.mjs`; `make verify-skill` after changing its help).
- Flows: change `trip-route-replay.json`, `trip-route-replay-backtrack.json`, `home-route-replay.json`, `trip-route-replay-mapkit-fallback.json` and `-blocked.json` (the replay hidden); add `trip-route-replay-no-key.json`.
- Static demo: `demo/README.md` and `demo/verify.mjs` as the design says: no maps and no replay until #834 gives the demo a real key.

**Out of scope**
The cards (#837), Stats (#838), promise wording (#839).

**Acceptance criteria**
- [ ] With `mapkit: false` the trip page has no `section[aria-label='Route replay']`, no Replay trip and makes no request to an Apple host (Vitest and `trip-route-replay-no-key`).
- [ ] With the stand-in failing to load, refusing a token or raising later, the replay is hidden (`RouteReplayMapKit.svelte.test.ts`, the two flows).
- [ ] No `land.svelte` or `world-atlas` import is left in the replay's files.
- [ ] The UI matches frame c of `docs/design/mapkit-only/` (signed off on #833); any change to layout, flow or visual style needs the owner's sign-off before merge, and the pull request shows `make verify` images at phone and desktop width beside the frames.

**Tests**
Remove `lib/route-roads.test.ts`, `lib/route-boundaries.test.ts`, `RouteReplayRoads.svelte.test.ts`, `RouteReplayBoundaries.svelte.test.ts` (`Removes-Test:`). Change `RouteReplayMap`, `RouteReplay`, `RouteReplayCompact`, `RouteReplayHome`, `RouteReplayHidden`, `RouteReplayMapKit` suites, `replay-mapkit.test.ts`, `route-replay.test.ts`, `PastTrip.svelte.test.ts`, `tests/test_verify.py`, `frontend/verify/verify.test.mjs`. Run `make check`, `make verify`, `make control-smoke`.

**Depends on**
#835.

**Model**
Sonnet: a settled UI change held by the frames and the checks.

### Step 3 (#837): Past trips cards on Apple's map

**Context**
`frontend/src/lib/components/RouteTile.svelte` draws a Past card's route on bundled outlines (`RouteTileMap.svelte`). The owner decided on #828 that the cards load Apple's map and, with no key, hide it. Design: `docs/design/mapkit-only/README.md` ("Trips list cards") and frame a, signed off on #833, with the owner's decision on #833 (2026-11-18): Apple's static snapshot with Waypoint's route on top.

**Scope**
- **To confirm with Apple first, before any code:** the snapshot service's parameters (`center`, `z`, `size`, `scale`, `colorScheme`, `poi`, `lang`, `teamId`, `keyId`, `signature`), whether it accepts `expires`, and whether its terms let Waypoint draw its own route on top of a snapshot. Record what Apple's documentation or support says in the pull request; if any of it doesn't hold, stop and raise it on #828 before building.
- `waypoint/providers/mapkit.py`: `snapshot_url(creds, center, zoom, size, scale, scheme, lang, now)` signing the path and query; `SNAPSHOT_URL` beside the other hosts.
- `waypoint/domain/maps.py` and a new `waypoint/domain/map_snapshots.py`: the centre and zoom from a trip's stops (`tripmap.places`) fitted to the card, zoom capped at 12, signed addresses kept per trip and size for a day in memory.
- `GET /api/map-snapshots?trip=…&w=…&h=…` (at most 12 trips): sign-in, blocked for assistants, a trip you can't see or with fewer than two stops left out, typed in `server/contract.py`, a docs page section; `make api-contract`, `make feature-map`.
- `RouteTile.svelte`: an `<img loading="lazy" referrerpolicy="no-referrer">` of the address, with the route and stops drawn on top in SVG from the same centre and zoom (Web Mercator), the stored Apple roads when present; the kinds tile at half strength while loading, at full strength on no key, no address or an image error; no retry until reload. Delete `RouteTileMap.svelte`.
- Batching: one request for the cards on screen, like `savedRoutes`.
- Flows: change `past-trips-list.json`, `past-trip-saved-route.json`, `trips-widths.json`; add `past-trips-list-no-key.json` and `past-trips-list-map-failed.json`; the snapshot stand-in in `verify.mjs`.

**Out of scope**
Stats (#838), the replay (#836), promise wording (#839, though this pull request adds the snapshot's sentence to AGENTS.md's MapKit passage, since it adds what Apple learns).

**Acceptance criteria**
- [ ] A card with photos, or with fewer than two stops, makes no snapshot request (Vitest).
- [ ] With `mapkit: false` no card asks for an address or an image, and the kinds tile shows.
- [ ] `tests/test_map_snapshots.py` proves the signed query holds only the allowed parameters and no stop coordinate, a stranger's trip is left out, assistants are blocked, and `no_leaks` holds with the key, Key ID and Team ID as canaries.
- [ ] A 60-card list scrolled end to end in `make verify` requests no more images than cards without photos.
- [ ] The UI matches frame a (signed off on #833); any change to layout, flow or visual style needs the owner's sign-off before merge; `make verify` images at phone and desktop width beside the frames.

**Tests**
New `tests/test_map_snapshots.py`; extend `tests/test_mapkit.py`; change `RouteTile.svelte.test.ts`, `PastTripCard.svelte.test.ts`, `pages/Trips.svelte.test.ts`, `lib/driving-routes.test.ts`. Run `make check`, `make verify`.

**Depends on**
#836; Apple's snapshot parameters, `expires` and drawing on top confirmed (first item of the scope).

**Model**
Sonnet: a decided design; the new route is held by `tests/test_every_route.py`, `no_leaks` and review.

### Step 4 (#838): The Stats map on MapKit

**Context**
`frontend/src/lib/components/TravelMap.svelte` draws the Stats world map from bundled outlines (`lib/map.ts`, `lib/land.svelte.ts`, `world-atlas`, `us-atlas`). The owner decided on #828 that Stats uses MapKit and hides the map with no key, and on #833 (2026-11-18) that the visited countries and states stay shaded, from the bundled outlines. Design: `docs/design/mapkit-only/README.md` ("Stats world map") and frame b, signed off on #833.

**Scope**
- New `frontend/src/lib/components/StatsMapKit.svelte`: one `mapkit.Map` (dark, no points of interest, MapKit's zoom control); the visited countries as `mapkit.PolygonOverlay`s from `world-atlas`'s 1:50m outlines and, once zoomed in to a span under about 40° of longitude, the visited US states from `us-atlas` (the United States' fill dropped then), styled with `--map-visited` (fill about 35%, edge about 70%); airports as sized dots, flights as great-circle polylines, stays as pins, above the shading; fitted as `flownBounds` is today; scroll enabled on phone only after zooming in; a tap on any of them selects it and shows today's caption under the map. Only visited features become overlays. If the outlines fail to load, the map shows without shading.
- `pages/Stats.svelte`: lazy-load it only when `app.state.mapkit === true` and online; keep the skeleton while it loads; no slot with no key; collapse on failure.
- Delete `TravelMap.svelte`, `lib/land.svelte.ts`; strip `lib/map.ts` to the data and outline helpers the README's inventory keeps; keep `world-atlas`, `us-atlas`, `topojson-client` and `d3-geo` in `frontend/package.json`.
- Add the `waypoint-no-bundled-map` check (Semgrep or ESLint) with examples: no projection or `geoPath(` in `frontend/src/`, the outline packages imported only in `lib/map.ts`.
- Flows: change `open-stats.json`, `stats-map-details.json`, `stats-map-zoom.json`, `stats-long-names.json`, `hotel-stats.json`, `parking-stats.json`; add `stats-no-key.json`, `stats-map-failed.json`.

**Out of scope**
Cards, replay, wording beyond the Stats sentence in AGENTS.md's MapKit passage (#839).

**Acceptance criteria**
- [ ] With `mapkit: false` Stats has no `#stats-map-slot` map and makes no request to an Apple host; the Countries tile and lists show.
- [ ] The stand-in records only the period's airports, arcs and stays and the visited countries' and states' outlines, never an unvisited one (`StatsMapKit.svelte.test.ts`); the visited-shading and tap cases of the removed `TravelMap.svelte.test.ts` pass against it.
- [ ] With no key the outline files are not requested.
- [ ] The check fails on a `geoPath(` in a component or an outline import outside `lib/map.ts` (its examples).
- [ ] The UI matches frame b (signed off on #833); any change to layout, flow or visual style needs the owner's sign-off before merge; `make verify` images at phone and desktop width beside the frames.

**Tests**
New `StatsMapKit.svelte.test.ts`; remove `TravelMap.svelte.test.ts`, `lib/land.svelte.test.ts` (`Removes-Test:`); change `lib/map.test.ts`, `frontend/src/test/fake-mapkit.ts`. Run `make check`, `make verify`.

**Depends on**
#836.

**Model**
Sonnet: a decided UI change.

### Step 5 (#839): Promises and docs for MapKit only

**Context**
Steps #835 to #838 make every map Apple's and remove the bundled one. AGENTS.md ("You see the trips you're on"), SECURITY.md ("MapKit (optional)"), `.github/agent-review/invariants.md` 4 and 9 and the user docs still describe the bundled map. The wording to write is in `docs/design/mapkit-only/README.md` ("Wording that must change"), signed off on #833.

**Scope**
- Rewrite the passages listed there in AGENTS.md, SECURITY.md and `invariants.md`, citing the owner's decisions on #828 and #833 and keeping every earlier decision cited.
- User docs: `start/trips.md`, `start/stats.md`, `start/docker.md`, `reference/configuration.md`, `privacy/email-scanning.md`, `README.md`, `docs/PHOTOS.md`; a status line in `docs/design/mapkit-only/README.md` and `docs/design/mapkit-spike.md`.
- The Settings → Travel "Maps" row (frame c4, decided on #833): read-only, "Apple Maps" with an "On" chip and a "What Apple learns" link to the trips docs' Apple's map section when `app.state.mapkit` is true; "Off: this server has no MapKit key, so Waypoint shows no maps or route replays." with an "Off" chip and a "How to turn on maps" link to the configuration docs otherwise. No switch.
- `make feature-map`, `make user-feature-map`.

**Out of scope**
Code changes other than the Settings row.

**Acceptance criteria**
- [ ] `grep -rniE 'bundled (svg )?map|state lines|roads\.tsv|states\.tsv|never drawn by MapKit' AGENTS.md SECURITY.md .github docs/src README.md docs/PHOTOS.md` finds nothing but history.
- [ ] Every check named in the new wording exists (the second review checks it).
- [ ] The Settings row matches frame c4 (signed off on #833), with `make verify` images at phone and desktop width for both states (a `mapkit: "none"` flow and a default one).

**Tests**
`make docs-build`, `make check`; `pages/Settings.svelte.test.ts` (both states, the links' targets).

**Depends on**
#837, #838.

**Model**
Sonnet: the wording is fixed here; Codex and the second review check it against the code.

## Open questions for the owner

None. Every question this design asked was answered on #833 on 2026-11-18 (see [Owner decisions on #833](#owner-decisions-on-833-2026-11-18) and [the sign-off comment](https://github.com/AnthonyPluth/Waypoint/pull/833#issuecomment-6980482363)). What is left outside this design is the demo's real MapKit key, [#834](https://github.com/AnthonyPluth/Waypoint/issues/834).

## Fonts

The pages load Geist and Geist Mono from Google Fonts when you are online and fall back to system fonts otherwise. This is for viewing these design files only.
