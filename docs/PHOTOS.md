# Photos on any trip, from Immich

Status: draft for the owner's review. Nothing here is built. When accepted this file becomes `docs/PHOTOS.md` in Waypoint and the issues in the backlog link to its sections.

## What it does

Every trip, past or future, gets its photos. Waypoint reads each family member's Immich library (Darkroom builds one library per person on Unraid; Darkroom never talks to Waypoint), matches photos to trips by capture time and then by distance to the trip's bookings, and shows them on the trip page: a strip and gallery, pins on the route map, and a line of trip stats. Immich stays the source of truth: Waypoint keeps a reference per photo (asset id, time, location, match) and streams thumbnails and originals from Immich through its own authenticated routes, so Immich is never exposed to the browser.

Nothing is special-cased for one trip. The motivating case (a two-year road trip of stays and rentals) is just a long trip with many `hotel` and `car` segments; a weekend flight works the same way.

Non-goals for the first version: editing, albums, faces, uploading, sharing links, photos in the offline copy, photos through `/mcp`, and map tiles (Waypoint's maps stay vector, drawn from bundled data).

## How it fits Waypoint

| Piece | Where | Notes |
| --- | --- | --- |
| Immich client | `waypoint/providers/immich.py` | The only module that names Immich endpoints; every request through `tls.urlopen` (`allow_http=True` for a LAN address, as the Ollama client does); its own import-linter independence contract `immich-alone` in `pyproject.toml`; a Semgrep rule `waypoint-immich-hosts` keeps the Immich base URL in this module, like `waypoint-flightstatus-hosts`. |
| API key storage | `waypoint/storage/photo_sources.py` | Encrypts and decrypts the per-person Immich key with `secretbox` (decrypting outside the storage layer, `oidc.py`, `domain/loyalty.py` and `providers/gmail.py` fails Semgrep's `waypoint-decrypt`, so the storage module hands the provider a key). Registers the column in `secretbox.SECRET_COLUMNS` and in `encrypt_stored`, so key rotation covers it. |
| Matching | `waypoint/domain/photomatch.py` | A pure, fully typed function of a photo and the candidate trips: no database, so it is tested exhaustively. |
| Listing, visibility, clusters | `waypoint/domain/photos.py` | Reads trips only through `waypoint/domain/visibility.py`. Also the itinerary-location fallback (`where_was`) and the demo placeholder image. |
| Sync job | `waypoint/domain/photosync.py`, scheduled from `waypoint/server/jobs.py` | Pages Immich per source and trip window, writes rows, runs the matcher; takes `today` as an argument (no bare `date.today()` in a job). |
| Trip stats | `waypoint/domain/tripstats.py` | Per-trip figures from the segments the household already has, plus photo counts. Reuses `stats.distance_km`, `stats._nights` logic, `tripmap.road_legs` and `roads.Route.miles`. |
| Routes | `waypoint/server/api/photos.py`, listed in `waypoint/server/routes.py`, typed in `waypoint/server/contract.py` | Binary routes join `NOT_JSON` in `tests/test_every_route.py`; photo routes join `BLOCKED` in `waypoint/server/mcp_access.py`. `tools/feature_map.py`'s `AREA_DOCS` maps `photos` and `photo-sources` to `start/photos`. |
| Web app | `frontend/src/lib/photos.ts`, `components/TripPhotos.svelte`, `components/PhotoViewer.svelte`, `components/TripSummary.svelte`, `components/settings/PhotosSection.svelte`; pins in `components/RouteReplayMap.svelte` via `lib/route-replay.ts` | Dark only; tokens from `frontend/src/app.css`; `apiCall<"GET /api/…">` from `lib/contract.ts`. |
| Docs | `docs/src/content/docs/start/photos.md` | The user-facing page; every route must map to a docs page (`tests/test_every_route.py`). |

Promises touched (AGENTS.md, "Waypoint's promises"): **You see the trips you're on** (photo routes answer 404 for a trip the viewer can't see, exactly like `GET /api/trips/{id}/places`), **Times are where they happen** (a photo's time is shown as the wall-clock time where it was taken, never the viewer's zone), **Private data in logs** (sync and proxy log counts and fixed error texts, never an Immich URL with a key, an asset id with a trip name, or a place). A new line for the promises list, proposed: "Photos stay in Immich. Waypoint keeps a photo's asset id, when and where it was taken and which trip it matched, nothing else; pixels pass through `GET /api/photos/{id}/…` only to someone who can see that trip, and the Immich address and key reach the browser never."

## Data model

One Alembic migration (`0038_photos`, after main's newest, with its `test_0038_…` in `tests/test_migrations.py`) adds three tables. Tables are declared in `waypoint/storage/schema.py` with `info={'doc': …}` and mapped in `waypoint/storage/models.py`. All three are in a backup (none joins `backup.SKIP`): the key travels encrypted as mailbox tokens do, and the photo rows hold the owner's decisions (hidden, moved to another trip), which a re-sync must not undo.

**`photo_sources`**: one Immich library Waypoint reads.

| Column | Type | Meaning |
| --- | --- | --- |
| `id` | int pk | |
| `person_id` | fk `people.id`, CASCADE, not null | Whose library it is: their photos belong to the trips this person is on. |
| `owner_sub` | text, not null | The member who connected it (`users.sub`, or `local` without sign-in). Only they (or the household in local mode) can change or remove it; it ends when they can no longer sign in (`oidc.access_lapsed`, swept by `jobs.sweep_lapsed`). |
| `url` | text, not null | The Immich base address, scheme and host (and port), no path, no credentials. Shown in Settings. |
| `immich_user_id` | text, not null | The Immich user the key belonged to when connected (from `GET /api/users/me`). A new key must answer the same id, or the change is refused with a fixed sentence ("that key belongs to a different Immich account; remove this library and connect it again"), so one person's photos can never be re-attributed by swapping keys. |
| `api_key` | text, not null | Encrypted (`secretbox`). Never in a reply, a log or an error. |
| `label` | text | Optional name ("Jane's library"). |
| `status` | text, not null | `ok`, `refused` (401/403 from Immich), `unreachable`, `off` (paused by the owner). |
| `last_sync` | float | Epoch seconds of the last completed sync. |
| `last_error` | text | One of a few fixed sentences, never Immich's text. |
| `created` | float, not null | |

Unique on (`person_id`, `url`).

**`photos`**: one Immich asset Waypoint has looked at inside some trip window. Kept small on purpose: a reference and the match, no pixels, no file names, no camera data.

| Column | Type | Meaning |
| --- | --- | --- |
| `id` | int pk | Waypoint's own id, the one in URLs (never the Immich id in the browser's address bar, so an asset id is not guessable from outside). |
| `source_id` | fk `photo_sources.id`, CASCADE, not null | |
| `asset_updated` | text, not null | Immich's `updatedAt` for the asset when last seen; the revision in the ETag, so a regenerated rendition is fetched again. |
| `asset_id` | text, not null | The Immich asset id. Unique with `source_id`. |
| `kind` | text, not null | `image` or `video` (Immich's `type`). |
| `taken_utc` | text, not null | ISO instant in UTC, from Immich's `fileCreatedAt` (its canonical UTC timestamp). Never built from `exifInfo.dateTimeOriginal` alone: without an offset that is a wall-clock value, not an instant, and would shift boundary photos by hours. The spike confirms `fileCreatedAt` carries the offset Darkroom writes; if it does not, an asset with no usable instant is skipped, not guessed. |
| `taken_local` | text, not null | `YYYY-MM-DDTHH:MM`, the wall clock where it was taken (Immich's `localDateTime`). Shown as is. |
| `taken_offset` | int | Minutes from UTC when Immich gives one (`exifInfo.timeZone` or the offset in `dateTimeOriginal`); null when unknown, in which case display uses the matched segment's zone. Display only: matching always uses `taken_utc`. |
| `latitude`, `longitude` | float | From EXIF when present; from the itinerary when inferred; null when neither. |
| `location_source` | text | `exif`, `inferred`, or null. An inferred point is marked in every reply and on the map. |
| `state`, `country` | text | Immich's reverse-geocoded `exifInfo.state` and `exifInfo.country` (null when Immich has none); feed the trip's states and countries. |
| `trip_id` | fk `trips.id`, SET NULL | The matched trip, or null. |
| `segment_id` | fk `segments.id`, SET NULL | The nearest segment (by distance, else by time). |
| `match` | text, not null | `place` (GPS within NEAR of a segment of its trip), `time` (one trip's window, no GPS or no close segment), `far` (in a window but more than FAR from every point of that trip; matched, flagged), `ambiguous` (two windows, distance couldn't settle it; not shown on a trip until the owner picks), `home` (within HOME of Home; ignored), `none` (no window). |
| `distance_km` | float | Distance to `segment_id`'s point, null without GPS. |
| `decided_by` | text | `auto`, or `owner` when the owner picked its trip (moved it, or chose between ambiguous trips); the sync never overwrites an `owner` row's `trip_id`. Hiding does not set it. |
| `hidden` | bool, not null, default false | Hidden by the library's person (decision 3). Independent of the match: a hidden `auto` row keeps being re-matched, so un-hiding shows the current match, not a stale one. The sync never overwrites it. |
| `seen` | float, not null | Epoch seconds the sync last saw it in Immich; a full re-list deletes rows not seen. |

Indexes: (`trip_id`), (`source_id`, `taken_utc`), unique (`source_id`, `asset_id`).

**`photo_trip_syncs`**: what each source has fetched for each trip window, so a changed trip is re-fetched and an unchanged one is paged incrementally.

| Column | Type | Meaning |
| --- | --- | --- |
| `source_id` | fk CASCADE, pk part | |
| `trip_id` | fk `trips.id` CASCADE, pk part | |
| `window_start`, `window_end` | text, not null | The ISO UTC window last fetched. A trip whose window moved is fetched in full again. |
| `cursor` | text | Immich `updatedAfter` for the next incremental run: the start time of the last traversal that finished; null before the first complete fetch. Advanced only when a traversal completes, never part-way. |
| `resume_page` | int | The `page` to continue from when a run stopped inside a traversal (budget, 429, network); null when no traversal is in progress. The traversal keeps its own `fetch_started` so the next `cursor` is the time it began, not the time it was resumed. |
| `fetch_started` | text | UTC time the traversal in progress began; becomes `cursor` when it completes. |
| `synced` | float | |

Settings keys (`waypoint/storage/settings_keys.py`): `PHOTOS_LAST_RELIST` (epoch of the last full re-list). No new environment variables; sources are set up in Settings so each member can add their own.

## Immich, as verified

Checked against the Immich API docs (v1.140 reference) on 2026-11-01; the spike confirms them on the family server, which may run a different version.

- **API keys are per user**, made under Account Settings, sent as the `x-api-key` header, and can be scoped to permissions (from 1.138; older servers need `all`). Waypoint asks for `asset.read` and `asset.view` (thumbnails and previews) and `user.read` (the Test step calls `GET /api/users/me`, which Immich protects with it); `asset.download`, because originals are served through Waypoint (decision 6).
- **`POST /api/search/metadata`** (searchAssets) takes `takenAfter` and `takenBefore` (date-time), `updatedAfter`, `page` (≥ 1), `size` (1–1000), `withExif`, `order` (`asc`/`desc`), `type` (`IMAGE`, `VIDEO`), `visibility` (`timeline`, `archive`, `hidden`, `locked`), `libraryId`. Reply: `assets.items`, `assets.nextPage`, `assets.total`, `assets.count`. Each asset: `id`, `type`, `localDateTime`, `fileCreatedAt` (UTC), `updatedAt`, `exifInfo.dateTimeOriginal`, `exifInfo.timeZone`, `exifInfo.latitude`, `exifInfo.longitude`, `exifInfo.city`, `exifInfo.state`, `exifInfo.country`.
- **`GET /api/map/markers`** takes `fileCreatedAfter`, `fileCreatedBefore`, `isArchived`, `isFavorite`, `withPartners`, `withSharedAlbums` and returns `{id, lat, lon, city, state, country}` per located asset. It has no time per marker, so the design uses metadata search as the one source and keeps markers as an optional cheap pre-pass the spike may recommend.
- **`GET /api/assets/{id}/thumbnail?size=thumbnail|preview|fullsize`** (viewAsset, `asset.view`) and **`GET /api/assets/{id}/original`** (`asset.download`).
- **`GET /api/server/ping`** / `GET /api/users/me` (`user.read`) to test a connection and learn the key's user: the name is shown once in Settings as "connected as …"; the user id is stored in `photo_sources.immich_user_id` to bind the source to that account.

To confirm in the spike (`PHOTOS-SPIKE`): whether `takenAfter`/`takenBefore` compare against `dateTimeOriginal` or `fileCreatedAt`; how a Darkroom-written XMP offset shows up (`exifInfo.timeZone` as an IANA name or `UTC±hh:mm`, and whether `localDateTime` follows it); whether `updatedAt` moves when Darkroom adds GPS through a sidecar (it must, or the incremental sync misses corrections); the real `size` ceiling and page time for the largest library; the thumbnail content type (WebP or JPEG) and preview dimensions; whether external-library assets answer `thumbnail` before the thumbnail job has run; what `visibility` the Darkroom assets carry; and whether the server is reached over `http://` on the LAN or `https://` through Traefik.

## Matching

`photomatch.match(photo, candidates, home) -> Match`, pure. Inputs: the photo (instant, GPS or none, person), the candidate trips with their windows and located points, and the household's Home point (`domain/home.py`, may be none).

**Candidate trips** are the trips the photo's person is on: `trip_people` (`trippeople.of`), which by Waypoint's rules already includes everyone named on any booking. Being the booker or an email recipient does not make a trip a candidate: a parent who booked a child's trip does not get their own photos matched to it.

**A trip's window** is `[first live segment start − PAD, last live segment end + PAD]` as instants from each segment's own zone (`trips.instant`), falling back to `start_date 00:00` and `end_date 23:59` in the first and last segment's zones when a trip has dates and no times (a visit-only past trip). Cancelled segments don't count.

**Steps**

1. Drop the photo when its instant is in no candidate window: `none`. These rows are never written (the sync only asks Immich inside windows), so photos from ordinary days never enter Waypoint.
2. With GPS within the Home radius for Home's precision (table below): `home`, ignored even inside a window (a road trip that starts at home gets its first photos at the first stop, not the driveway). A Home known only to the city has no radius: nothing is suppressed automatically, and a photo near it follows the normal steps (the owner can hide or move it).
3. Score each candidate window that contains the instant: the nearest live segment point of that trip (stays, cars, parking, trains and cruises use the point stored with the segment, `segments.latitude/longitude`; a flight uses its two airports; ports via `geocode.locate_port`), preferring segments active at that instant and breaking ties by time distance. Without GPS the score is the time distance to the nearest segment.
4. One candidate: it wins. With GPS: `place` when within NEAR km of a segment point, `far` when farther than FAR km from every point of the trip, else `time`. Without GPS: `time`.
5. Several candidates (an overlapping short trip inside a long one): with GPS, the trip with the smaller nearest distance wins when it beats the next by at least MARGIN km; otherwise, and always without GPS, the shortest window wins (the more specific trip). When the shortest window isn't unique: `ambiguous`, no trip, the owner picks.
6. `segment_id` and `distance_km` are the nearest segment and its distance; a photo without GPS takes `where_was` below.

**Itinerary location for a photo without GPS** (`photos.where_was(trip_segments, instant)`): the point of the segment active at that instant (a stay, rental or parking covering it; a train or cruise under way gives its port or city; a flight under way gives nothing); otherwise the destination of the last segment that ended within GAP hours before, else the origin of the next one starting within GAP hours after; else nothing. The result is stored with `location_source = inferred` and drawn as a hollow pin; it is never promoted to `exif`.

**Thresholds** (constants in `photomatch.py`, settled in #484):

| Name | Value | Why |
| --- | --- | --- |
| `PAD` | 12 hours | Airport photos before a late-night flight home; the first morning after a trip's dates. |
| `HOME` | 2 km for an address or coordinates, 8 km for a ZIP or postal code, none for a city | The radius follows how precisely Home is known (`domain/home.py` knows which): a ZIP centroid can sit several kilometres from the house, and a city centroid cannot be trusted at all, so a fixed 2 km would let ordinary home photos through. |
| `NEAR` | 100 km | A day out from a campground or hotel is still "there". |
| `FAR` | 400 km | Beyond a long day's drive from every booking: still shown, but flagged, since the trip may be missing a stay. |
| `MARGIN` | 25 km | Two trips' nearest bookings within this of each other can't be told apart by GPS. |
| `GAP` | 36 hours | How long after checking out the itinerary still says where someone is. |
| `CLUSTER` | 5 km | Pins on the map: photos within this of a cluster's centroid join it. |

A re-sync re-runs the matcher on every `auto` row of a source whose trips changed (a trip gained a booking, dates moved), hidden rows included, and leaves `owner` rows' trip alone.

## Sync job

`photosync.run(conn, source, provider, today, now)`; `jobs.py` runs `sync_all` every `PHOTO_SYNC_EVERY` (6 hours, first run 10 minutes after start) and a **Sync now** button runs one source in a thread like `scan_now`. One source syncs at a time; a source in `refused` or `off` is skipped until its owner acts.

For each source:

1. Load the person's trips and their windows; drop `photo_trip_syncs` rows for trips the person left, and their photos' `trip_id` (rows then re-match or are deleted on the next re-list).
2. For each trip window: when the row is missing or the window moved, page `search/metadata` with `takenAfter`, `takenBefore`, `withExif: true`, `visibility: "timeline"`, `size: 1000`, `order: "asc"`, starting at `resume_page` when set (else page 1 with `fetch_started = now`); an incremental run adds `updatedAfter: cursor`. Windows overlap between trips; a photo seen twice is one row. Upsert each asset: time fields, `asset_updated`, GPS, state and country, `seen = now`; run the matcher for `auto` rows. Each finished page stores the next `resume_page`; when `nextPage` is null the traversal is complete: `cursor = fetch_started`, `resume_page` and `fetch_started` cleared. `updatedAfter` only filters; it never resumes a traversal.
3. Every `FULL_RELIST_DAYS` (7) a source is fetched without cursors and, once that traversal completes, rows not `seen` are deleted (trashed or deleted in Immich); an interrupted full re-list deletes nothing. A thumbnail or preview 404 from the proxy does not delete a row (see the proxy rules).
4. Record `last_sync`, counts (fetched, new, matched by kind, inferred, ambiguous) in the log through `monitoring.log`, counts only.

Budget: a page of 1000 assets with EXIF is a few megabytes; a two-year window on first fetch is tens of pages. `TIME_BUDGET` (10 minutes per source per run) stops a run cleanly after the current page; the next run continues from `resume_page`, as the mail scan resumes, and the update watermark moves only when the traversal finishes, so a large library is never left with assets skipped. 429 backs off; 401/403 sets `refused`; a network error sets `unreachable` and the status page says so.

Darkroom's rescans and sidecars change assets' `updatedAt`, so GPS added later arrives on the next incremental sync and the matcher re-runs for that row.

## Proxy and access rules

Routes (all need sign-in; `tests/test_every_route.py` holds that):

| Route | Who | What |
| --- | --- | --- |
| `GET /api/photos/{id}/thumbnail` | anyone who can see the photo's trip, or the library's person for an unmatched photo of theirs | Immich `thumbnail` (grid tile). |
| `GET /api/photos/{id}/preview` | same | Immich `preview` (lightbox). |
| `GET /api/photos/{id}/original` | same | Immich `original`, streamed (`Response.stream`), for the "Open original" action and videos. |

Rules:

- The photo id is Waypoint's; the handler finds the row, then `visibility.visible_trip(conn, viewer, row.trip_id)`; a missing row, a hidden photo (for anyone but its person), a stranger or an assistant all get 404 with the same text (`NO_IMAGE`). `ambiguous`, `home` and `none` rows are served only to the library's person.
- The upstream request goes through `providers/immich.py` with the decrypted key from `storage/photo_sources.py`; the key never appears in a URL, a log, an exception text or a reply header. Only the body and a sniffed content type come back; Immich's own headers are dropped, except the range headers of an original (below). Thumbnails and previews are `image/webp`, `image/jpeg` or `image/png`. Originals are checked against an allowlist by magic bytes, not by Immich's header: browser-renderable images (JPEG, PNG, WebP, GIF, AVIF) and video (`video/mp4`, `video/quicktime`, `video/webm`) are served inline; HEIC/HEIF, TIFF, RAW and Matroska are served as `Content-Disposition: attachment` with their sniffed type or `application/octet-stream`; anything else, and always SVG and HTML, is 404. Every reply carries `X-Content-Type-Options: nosniff`.
- Caps: thumbnails 2 MB, previews 10 MB, read in chunks under a time budget (`mailimages.py` is the pattern); originals stream without a size cap under a 10-minute budget, and honour byte ranges: a valid single `Range` header is forwarded to Immich, and its `206`, `Content-Range`, `Content-Length` and `Accept-Ranges` come back, so a video seeks and resumes; a malformed or multi-range request is answered as a full body. A 404 or 410 on a thumbnail or preview keeps the row (Immich may not have generated an external-library rendition yet) and answers 404 to the viewer, retryable; only when a follow-up `GET /api/assets/{id}` (`asset.read`) also answers 404 or 410 is the row deleted. 401/403 marks the source `refused` and answers 404 to the viewer.
- Reply: `image_response`'s CSP (`default-src 'none'; sandbox`), `Cache-Control: private, max-age=86400` and an ETag of (photo id, size, `asset_updated`), so a regenerated or edited rendition is fetched again and a gallery revisit is otherwise cheap and nothing is cached by a shared proxy. The server never writes pixels to disk or the database.
- Assistants: `/api/photos` and `/api/photo-sources` join `BLOCKED` in `mcp_access.py`. The offline copy (`GET /api/offline`) carries no photos.
- Sources: `GET /api/photo-sources` lists every source for the household (person, host, status, counts; `mine` for the viewer's own); `POST /api/photo-sources` creates one for any person in People; `POST /api/photo-sources/{id}` (key, label, paused) and `DELETE` answer only its `owner_sub` (or the household in local mode); `POST …/test` pings Immich with the key and reports the user it belongs to without saving anything; `POST …/sync` starts a run. A new key replaces the old one only when it belongs to the same Immich user as the stored `immich_user_id`; the old one is never shown. Deleting a source deletes its photos (CASCADE).
- Lapsed access: `photos.end_lapsed` (in `jobs.sweep_lapsed`, next to `gmail.end_lapsed`) deletes a source whose `owner_sub` can no longer sign in.
- Demo and `make verify`: `demo.seed` adds a source per demo person with `url = "demo"` (no key) and photo rows across the demo trips; for a `demo` source the proxy serves a deterministic generated PNG (`photos.placeholder(asset_id, size)`, a gradient tile like `demo._png`) and never opens a connection, so `make verify` runs with its network blocked and the pages still show photos.

## Map and stats

**Map.** The trip page already draws the route from the segments (`RouteReplay.svelte` → `GET /api/trips/{id}/places` → `domain/tripmap.py`: airports, stays, road legs along US highways, state lines). Photos add a layer, not a second map: `GET /api/trips/{id}/photos` returns the photos and their clusters, and `RouteReplayMap.svelte` draws a pin per cluster (size by count, hollow when every photo in it is inferred), projected with the same `routeProjection`, which is extended to fit the stops and the cluster coordinates together (a trip with no stops fits the clusters alone; a single cluster gets a fixed regional zoom), so a `far` cluster hundreds of kilometres away is still inside the map. During a replay a cluster lights up when the replay passes its first photo's time (the replay already tracks `stopDates`). Tapping a pin scrolls the gallery to that cluster. Today the map shows only for a trip that has ended with two placeable stops; with photos it shows for any trip with at least one cluster or two stops, and the replay controls appear only when the route is replayable.

**Clusters** are built server-side in `photos.clusters(rows)`: greedy by time order, a photo joins the first cluster whose centroid is within CLUSTER km, else starts one; each cluster carries centroid, count, first and last local time, cover photo id and whether it is all-inferred. The reply caps clusters at 400 (merging the smallest neighbours past that), so a two-year trip stays drawable on a phone.

**Stats** (`domain/tripstats.py`, `GET /api/trips/{id}/summary`): days (trip dates), nights away (union of stay and cruise nights, as `stats._nights`), distance (flights: great-circle between airports via `stats.distance_km`; road: `tripmap.road_legs` miles where a highway route exists, else straight-line between consecutive placed stays, labelled "about"), states and countries (from segment addresses and visit details via `geocode`/`regions`, plus the `state`/`country` of the trip's photos from Immich, leaving out `far` photos until the owner accepts or moves them, so one wrong-clock or unrelated photo cannot add a place to the trip; US states listed by name, other countries by name), photo count with how many are inferred, and bookings by kind. The web app shows distance in the household's `distance_unit` as Stats does.

## Settings screen

Settings gains a **Photos** section (`PhotosSection.svelte`, after Gmail): one card per source with person, host, status chip, last sync, photo count, **Sync now**, **Change key**, **Pause**, **Remove**; and **Connect an Immich library**: person (from People; defaults to the signed-in member's), Immich address, API key (with the permissions to tick listed), **Test** before **Save**. Permissions to tick: `asset.read`, `asset.view`, `user.read` (and `asset.download` if originals are served). Copy says plainly what Waypoint reads ("photos taken during your trips and the 12 hours around them; Waypoint keeps when and where for each, including photos that turn out not to belong to a trip, never the pictures").

## Decisions

Settled by the owner in #484: every item took the default below.

1. **Thresholds**: the table above.
2. **A photo that fits two overlapping trips**: GPS decides when it can (MARGIN); otherwise the shorter trip; a tie waits for the owner under "Needs a look".
3. **Hiding**: a library's person can hide a photo from a trip (`hidden`), and only they see it afterwards; nobody else can hide another person's photo. Alternative: no hiding in v1 (then drop `PHOTOS-UI-REVIEW`'s hide action and the column stays unused).
4. **Who sees whose photos**: everyone who can see a trip sees all its photos, from every library (same as bookings and costs). Alternative: each member sees only their own library's photos plus what others un-hide.
5. **Sync**: every 6 hours, a full re-list weekly, Sync now per source; first run 10 minutes after start.
6. **Originals through Waypoint**: yes, streamed, needing `asset.download` on the key. Alternative: previews only, with no "Open original".
7. **Videos**: included (thumbnail from Immich, original streamed on tap). Alternative: images only.
8. **Archived photos**: skipped (`visibility: timeline` only). Alternative: include archive.
9. **Who may connect a library for whom**: any signed-in member for any person in People (children without a login). Alternative: only for yourself.
10. **`far` photos**: shown on the trip with a flag, and listed under "Needs a look". Alternative: held back until the owner confirms.
11. **States crossed**: Immich's reverse-geocoded state per photo plus the booking addresses is enough. State lines crossed by the route are not counted from photos in v1, a scope choice; counting them would be a later issue.
12. **Merging trips**: the merged-away trip's photos become unassigned. The sync matches the automatic ones (`decided_by` auto) again when it next fetches them: at once if the survivor's window moved, otherwise at the weekly full re-list at the latest; the ones the owner placed by hand (`decided_by` owner) stay unassigned, because the sync never overwrites an owner row's trip. The merge itself carries no photos over; an automatic photo may still land on the surviving trip through normal matching.

## Open questions

- Should `get_trip` over `/mcp` say how many photos a trip has (counts only, never pixels)? Left out of v1.
- Should the household Stats page (`domain/stats.py`) count photos per year? Left out of v1.
- A trip with photos but no placeable segment (a trip typed in by hand with no addresses) gets a map of pins alone; is that wanted, or should the map need at least one stop?
- Live Photos and burst stacks: Immich stacks them; `withStacked` is off, so each asset is a photo. Fine for v1?
