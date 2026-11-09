# Spike: MapKit JS for the route replay and trip detail maps (#530)

Status: the owner has decided (section 9) and the route replay on MapKit JS is built behind a flag, with the SVG map kept as the fallback. Sections 1 to 8 are the findings as first written; where the owner's decisions changed an answer, section 9 says so. Nothing could be tried against Apple: there is no key yet, so everything was tested against a fake `mapkit` (section 9, "Not verified").

Facts about Apple's service come from Apple's MapKit JS page (the daily allowances) or from memory of Apple's documentation. Each memory item is marked **confirm**; none could be tested without a key.

## 1. Privacy

What AGENTS.md's "Waypoint's promises" say that applies:

- **You see the trips you're on** says the map's places, highways and state lines are bundled data read from disk, that a trip's coordinates, road legs and state lines reach the browser only in the visibility-checked `GET /api/trips/{id}/places` reply, "and never go to an outside service". The checks are `tests/test_geocode.py`, `test_roads.py`, `test_trip_roads.py`, `test_states.py` and `test_trip_states.py`.
- **Photos are shared by their person**: the replay and trip map also show photo pins. A map that sends the viewport to Apple would also send where a shared photo was taken, to anyone looking at the map, whatever the photo grant says.
- **Email stays on the server**: not affected; nothing from a message goes to the map.
- **IDs are for the household** and **Times are where they happen**: not affected.

Does sending the viewport to Apple break the promise? **Yes, as written.** MapKit JS fetches tiles from Apple for the area on screen. That is the trip's coordinates (at the zoom level of the replay's camera, down to street level around a hotel or home) going to an outside service, every time a person opens the replay. Apple also sees the viewer's IP address and browser. The token carries no trip data and no user identity, but Apple learns that someone on this Waypoint's origin looked at that place at that time. Home is a stop kind (`home`), so the replay can centre on a household's address.

Two further effects of the same fact:

- The Content-Security-Policy in `waypoint/server/handler.py` is `default-src 'self'`, `img-src 'self' data:`, `connect-src 'self'`, `worker-src 'self'`. MapKit needs Apple's script host, tile and API hosts, and probably `blob:` workers and images (**confirm** the exact list, and whether the script can be self-hosted; I believe Apple requires loading it from its CDN). Widening the CSP for the whole app weakens it. It could be limited to the route that serves the replay page only if the CSP is chosen per route, which the handler would need to learn.
- Offline: the offline vault (`frontend/src/lib/offline*.ts`) saves trips, not map tiles. MapKit has no offline tiles, so offline the replay is the SVG map regardless.

So adopting MapKit is not a code change that the existing checks allow. It is a change to the promise itself, which only the owner can make (decision 1).

If the owner accepts that, the minimum honest form is: off by default, a household-level setting that says in plain words "Maps are drawn by Apple; the area you look at is sent to Apple", a per-trip exclusion for trips with a Home stop, and the promise, the docs privacy page and `tests/test_geocode.py`'s wording updated together.

## 2. Setup and cost

- **Cost**: the Apple Developer Program is $99 a year (the issue states it; **confirm** current price). The household already needs it for the iPhone app's APNs key, so the marginal cost is zero if the same account is used.
- **What the owner creates** (**confirm** menu names): a Maps ID (`maps.<reverse-DNS>`) under Identifiers, then a Key with MapKit JS enabled and tied to that Maps ID. Apple shows the `.p8` once. The key gets a 10-character Key ID. The Team ID is the same one as for APNs.
- **Where it lives**: follow the APNs precedent, which is already reviewed. `WAYPOINT_APNS_KEY_FILE`, `_KEY_ID`, `_TEAM_ID` and `_TOPIC` (docs `reference/configuration.md`) point at a file on the server; `waypoint/providers/apns.py` builds an ES256 JWT from the `cryptography` package and caches it. A MapKit signer would be a new `providers/mapkit.py` with `WAYPOINT_MAPKIT_KEY_FILE`, `_KEY_ID`, `_TEAM_ID` (and the origin from `WAYPOINT_PUBLIC_URL`). The `.p8` never goes in the database, the repo or a reply. A new provider needs its own import-linter contract (AGENTS.md "Layout"). Sharing the ES256 signing code with `apns.py` needs a shared module, since providers don't import each other.
- **Validation**: at start-up and in the endpoint, load the PEM, require an elliptic-curve key (as `apns.py` does), and require the Key ID and Team ID to be 10 alphanumerics. A bad or missing key makes the endpoint answer "off" (below), never a 500 that includes key text. Whether Apple accepts the key can't be checked offline, only by a real request.
- **Token**: JWT, header `alg=ES256`, `kid`=Key ID; claims `iss`=Team ID, `iat`, `exp`, and `origin` (the site's origin, so a stolen token works on no other site) (**confirm** claim names and the maximum lifetime; I recall up to a year). A short lifetime of 30 minutes is right for Waypoint: the browser asks again through `mapkit.init({authorizationCallback})` when it needs one, so a leaked token expires fast. The endpoint would be `GET /api/mapkit/token`, sign-in required (`tests/test_every_route.py`), answering `{token, expires}` or `{enabled:false}`, never the key, Key ID or Team ID, and logging none of them (a `no_leaks` test with a canary PEM). Whether it is also a route a read-only assistant (the MCP) must be blocked from is a small check in `tests/test_every_route.py` conventions.
- Not a Waypoint cost: the owner's Apple account is the identity Apple bills (nothing, within the allowance below) and rate-limits.

## 3. Limits

Apple's MapKit JS page lists, per Apple Developer Program membership, per day: **250,000 map views, 25,000 service calls, 25,000 unique snapshot requests**, with a contact form for more. A household replays a trip a few times a day at most; this is several orders of magnitude of headroom, so the limits are not a concern. (Search and geocoding service calls aren't needed: Waypoint already has coordinates.) The one risk isn't the allowance but Apple changing or ending free access, which the fallback below covers.

## 4. Failure

Apple unreachable, token endpoint off, key invalid, CSP blocks, or the script fails to load: the replay must show the existing SVG map, with no error banner when MapKit simply isn't configured, and a short note ("Showing the simple map") when it was configured and failed. Design:

- A `mapReady` promise loads MapKit lazily, only on the replay view and only if the token endpoint says enabled, with a timeout (a few seconds). Reject or timeout renders `RouteReplayMap.svelte` unchanged.
- MapKit fires `error` events with a status such as `Unauthorized` or `Too Many Requests` after load; the same fallback applies, mid-replay, without losing the playback position (`progress` is already held in the component).
- Tests: the Vitest component test stubs `window.mapkit` to be absent / failing and asserts `data-testid="replay-map"` renders the SVG; a token-endpoint test for missing, malformed, non-EC and unreadable key files; a `no_leaks` test.

This failure story is what makes a flagged rollout safe, and it is cheap, but it can't be demonstrated end to end without a key.

## 5. Parity

Source: `RouteReplayMap.svelte` (229 lines) with `route-replay.ts` and `map.ts`. Replay features and what MapKit offers:

| Replay feature | MapKit JS | Verdict |
| --- | --- | --- |
| Base land, sea, outlines | Real standard/hybrid/satellite tiles | Better, and the point of the spike |
| Interstates, state lines, shields | Already on the base map | Not needed; `roads`/`boundaries` data goes unused with MapKit, which also removes the largest part of the places reply |
| Stops (airport, stay, home, place) | `Annotation` with a `factory` returning a DOM element | Reproducible; reuse the existing icons as inline SVG |
| Route legs, drawn in as time passes (`stroke-dashoffset`) | `PolylineOverlay` | No dash-offset animation. Redraw by updating the overlay's `points` each frame, or use a style with `lineDash`. Reproducible with more code; per-frame overlay updates must be measured |
| Curved flight arcs (the bowed bezier) | Straight geodesic lines or sampled points | Sample the bezier into points, as the SVG does mathematically |
| Moving plane/car/boat with heading | An `Annotation` whose `coordinate` and element rotation are updated each frame | Reproducible |
| Camera that follows progress (`cameraAt`) | `setRegionAnimated` / `setCameraBoundaryAnimated` | Reproducible, but the animation is Apple's own easing, so timings differ from `SCRUB_STEPS`-driven playback; scrubbing back and forth needs un-animated updates |
| Stop labels card (`lit`) | The existing absolutely-positioned HTML above the map | Unchanged |
| Reduced motion (`calm`) | Same | Unchanged |
| Dark-only app | `mapkit.Map.colorScheme = Dark` | Available |

Everything in the replay can be reproduced; none of it is free. About half of the component (the projection, the road and boundary shaping, the shields) wouldn't be used, but would stay for the fallback, so adoption adds code rather than replacing it. I did not build it, so frame rate during scrub and the look at phone width are untested.

Trip detail: the other trip-page map surfaces (the photo pins map and clusters, `docs/design/photos/c-trip-map.html`, `d-map-pins-only.html`) are designed on the SVG map and would benefit most from street-level context, but they are the places a photo's location is most sensitive. They should not be moved to MapKit before the photo promise's wording is settled (decision 2). `TravelMap` (the world stats map) stays, as the issue says.

## 6. Tests

What is SVG-bound today:

- Vitest: `RouteReplayMap.svelte.test.ts` (392 lines), `RouteReplay.svelte.test.ts`, `RouteReplayBoundaries`, `RouteReplayHome`, `RouteReplayRoads` (about 820 lines in total) query `data-leg`, `data-mover`, `data-stop`, `data-testid="legs"` and similar SVG nodes. They stay valid, because the SVG map stays as the fallback; they run with MapKit absent.
- Verify flows: `trip-route-replay`, `trip-route-replay-backtrack`, `home-route-replay`, `trip-state-lines`, `trip-state-lines-flight` wait on `[data-testid='replay-map']` and assert SVG pieces. With MapKit on they would need a fake `window.mapkit` (a test double the page loads when the flag is on in the demo server), because `make verify` must not call Apple, runs under a frozen clock, and tiles would change between runs and break screenshot diffs. So MapKit-on screenshots can only show the overlay layer over a stub background; a real-tile screenshot is a manual check, not a `make verify` one.
- New tests for MapKit mode: a fake-`mapkit` unit suite (annotations at the stops, polyline progress, camera calls, fallback on failure) and the token endpoint tests above.

## 7. Recommendation

**Drop for now; revisit only if the owner changes the privacy promise (decision 1).** Reasons:

1. It breaks a stated promise ("never go to an outside service") at the product's core, and also weakens the CSP. Those are the two things the app's checks are built to hold.
2. The benefit is cosmetic for a household replay that already works and already works offline.
3. It would add a second map implementation next to the SVG one (kept as the fallback), not replace it.

If the owner decides the trade is worth it, the order is: adopt for the route replay only, behind a household setting that is off by default, with the SVG fallback, and keep the photo pins, Home and `TravelMap` on the SVG map. That is a feature issue of its own (token endpoint and CSP per route, signer, settings, fallback, fake-mapkit tests), which should be written after the Apple key exists, because Section 4's failure behaviour and Section 5's frame-rate claims need a real run.

## 8. Decisions for the owner

1. **Is Apple seeing the replay's viewport acceptable?** If yes, the "never go to an outside service" sentence in AGENTS.md, the docs privacy page and its tests change with it. If no, drop the spike. This decides everything below.
2. **Photo pins and Home**: if yes to 1, are they allowed on Apple's map, or only on the SVG map?
3. **Default**: off for the household until someone turns it on (recommended), or on when a key is configured?
4. **CSP**: allow Apple's hosts for the whole app or only for the replay page (needs per-route CSP in `handler.py`)?
5. **Account**: create the Maps ID and MapKit JS key in the account used for the APNs key, and say where the `.p8` should be stored on the server. Nothing can be tried until this exists, and no key goes in the repo.
6. **Scope if adopted**: replay only, as the issue says, or the trip detail maps as well.

## 9. Owner's decisions and what was built

Decisions (made after the findings above):

1. **Privacy promise changed.** The replay's map viewport and coordinates may go to Apple, but only when a MapKit key is configured on the server. With no key, a key that doesn't load, no `WAYPOINT_PUBLIC_URL`, or the flag turned off, nothing changes: all map data stays on the server and the replay is the SVG map. The promise text (AGENTS.md "You see the trips you're on", `.github/agent-review/invariants.md`, SECURITY.md, the docs pages on trips, stats, data sources, privacy and configuration) says so in those words.
2. **Flag.** `WAYPOINT_MAPKIT_ENABLED`, on by default and inactive without a key, so a Waypoint with no key behaves exactly as before; `off` (or `0`, `false`, `no`) keeps the SVG map even with a key.
3. **Fallback.** A missing token, a script that doesn't load in 6 seconds, a refused token, or any later MapKit error returns the replay to the unchanged SVG map at the same progress.
4. **Scope.** The route replay, the only map on the trip page. `TravelMap` (Stats) is untouched. The photo pins are not on the replay, so decision 2 of section 8 doesn't arise here.
5. **CSP.** Apple's hosts are added to the page's policy only when MapKit is active (flag on, key valid, address set), globally for the app, not per route: the app is one page, so a per-route policy would not narrow anything. `script-src` gains the script host (with a nonce and `'strict-dynamic'` the host list is redundant in current browsers, kept for older ones), `connect-src` and `img-src` the service hosts, `img-src` and `worker-src` also `blob:`.
6. **Setup.** Key file path, Key ID and Team ID in env, as for APNs; `providers/mapkit.py` with its own import-linter contract (`mapkit-alone`); the shared ES256 signer is `waypoint/es256.py`, used by `apns.py` too.

What was built: `GET /api/mapkit/token` (sign-in required, blocked for assistants, `{enabled: false}` unless active, otherwise a 30-minute ES256 token with `iss`, `iat`, `exp` and `origin`, plus the script address); `frontend/src/lib/mapkit.ts` (load once, time-limited, remember an "off" answer), `replay-mapkit.ts` (the replay on MapKit: the stops as annotations, each leg as a polyline overlay drawn in, the plane, car or boat as an annotation, highways and state lines as overlays and the shields as annotations, the camera as the visible map rect), and `RouteReplayMapKit.svelte`, swapped in for the `<svg>` only. Everything else in the replay (labels, controls, stop list, key, reduced motion) is the existing component. The geometry reuses the SVG map's own functions on a Mercator projection (`routeProjection` takes an optional projection), so the path, timing, heading and camera follow the same rules.

Facts to confirm against Apple once there is a key (none could be checked from here; Apple's pages did not load in the tooling used):

- Token claim names (`iss` Team ID, `iat`, `exp`, `origin`) and header (`alg` ES256, `kid`, `typ` JWT), and the maximum lifetime of `exp` (recalled as up to a year; 30 minutes is used regardless).
- The script address (`https://cdn.apple-mapkit.com/mk/5.x.x/mapkit.js`) and the full list of hosts the policy must allow (`https://*.apple-mapkit.com`, `blob:` for images and workers are recalled, not confirmed; a host missing from the policy shows up as a CSP error and the SVG fallback).
- That `Referrer-Policy: no-referrer` and `Cross-Origin-Resource-Policy: same-origin` on Waypoint's own responses don't stop Apple accepting the token's `origin`.
- `Annotation` with a `factory`, `visible`, a settable `coordinate`, `PolylineOverlay.points`, `Style` (`lineDash`, `strokeOpacity`) and `Map.setVisibleMapRectAnimated` behaving as used; frame rate while scrubbing; the look at phone width on real tiles.
- Whether Apple's attribution and legal links, which MapKit draws itself, fit the replay's card at phone width.

Recommendation, revised: adopt for the route replay only, as built, behind the default-on-but-keyless flag. Revisit the rest (photo pins, Stats) separately.
