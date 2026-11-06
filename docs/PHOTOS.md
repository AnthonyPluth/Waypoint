# Photos on any trip, from Immich

Status: accepted design, being built. On main: the photo tables (#486, migration 0038), the matcher (#488), the trip photos reply and Needs a look (#491) and the trip summary (#493). Not built yet: per-trip consent, exclusion and sharing scope (this revision, from #504; migration 0039), the sources API (#489), the sync job (#490), the proxy (#492) and the web app (#496, #497, #498, #499). The parts already on main change as "Impact on the issues" at the end lists.

## What it does

Every trip, past or future, can get its photos. Waypoint reads each family member's Immich library (Darkroom builds one library per person on Unraid; Darkroom never talks to Waypoint), matches photos to trips by capture time and then by distance to the trip's bookings, and shows them on the trip page: a strip and gallery, pins on the route map, and a line of trip stats. Immich stays the source of truth: Waypoint keeps a reference per photo (asset id, time, location, match) and streams thumbnails and originals from Immich through its own authenticated routes, so Immich is never exposed to the browser.

A person's photos are used on a trip only when that person has shared them on that trip (a **grant**), and each grant says who sees them: **Only me** (the default) or **Trip** (everyone who can see the trip). A person can leave out single photos (an **exclusion**), and can take back what they shared at any time: one photo, a whole trip, or by switching a trip back to Only me. Every removal takes effect at once, for every viewer and every path ("Who sees a photo" below).

Nothing is special-cased for one trip. The motivating case (a two-year road trip of stays and rentals) is just a long trip with many `hotel` and `car` segments; a weekend flight works the same way.

Non-goals for the first version: editing, albums, faces, uploading, sharing links, photos in the offline copy, photos through `/mcp`, and map tiles (Waypoint's maps stay vector, drawn from bundled data).

## Terms

- **The photo's person**: the person in People whose library the photo came from (`photo_sources.person_id`).
- **Acting for a person**: a signed-in member acts for the person their sign-in is linked to. A person with no sign-in of their own (a child) is acted for by the member who connected their library (`photo_sources.owner_sub`); once that person has a sign-in, only they act for themselves. In local mode without sign-in the household acts for every person, as it already does for hiding and moving. Only someone acting for a person can grant, change the scope of, revoke, exclude, move or put back that person's photos, and they see that person's photos as the person does.
- **Grant**: one row of `photo_grants`, for one (person, trip), active while `revoked` is null.
- **Scope**: `only_me` (default) or `trip`.
- **Exclusion**: one row of `photo_exclusions`, for one (person, Immich asset, trip).
- **The trip's owner**: whoever booked or created a trip. They get no special access to photos: the predicate below has no case for them, and neither does the household's admin. Where this file says "the owner" of a photo decision (`decided_by = owner`, "the owner picks"), it means whoever acts for the photo's person, never the trip's owner.

## How it fits Waypoint

| Piece | Where | Notes |
| --- | --- | --- |
| Immich client | `waypoint/providers/immich.py` | The only module that names Immich endpoints; every request through `tls.urlopen` (`allow_http=True` for a LAN address, as the Ollama client does); its own import-linter independence contract `immich-alone` in `pyproject.toml`; a Semgrep rule `waypoint-immich-hosts` keeps the Immich base URL in this module, like `waypoint-flightstatus-hosts`. |
| API key storage | `waypoint/storage/photo_sources.py` | Encrypts and decrypts the per-person Immich key with `secretbox` (decrypting outside the storage layer, `oidc.py`, `domain/loyalty.py` and `providers/gmail.py` fails Semgrep's `waypoint-decrypt`, so the storage module hands the provider a key). Registers the column in `secretbox.SECRET_COLUMNS` and in `encrypt_stored`, so key rotation covers it. |
| Matching | `waypoint/domain/photomatch.py` | A pure, fully typed function of a photo and the candidate trips: no database, so it is tested exhaustively. Its candidates are only the granted trips the photo is not excluded from. |
| Grants and exclusions | `waypoint/domain/photogrants.py` | Grant, change scope, revoke, grant on all of a person's trips, exclude, put back, and the trip-people and merge hooks. Every removal deletes what it removes in the same transaction that records it. |
| Listing, access, clusters | `waypoint/domain/photos.py` | Reads trips only through `waypoint/domain/visibility.py`, and photos only through the one access predicate `photos.visible(viewer)` (below). Also the itinerary-location fallback (`where_was`) and the demo placeholder image. |
| Sync job | `waypoint/domain/photosync.py`, scheduled from `waypoint/server/jobs.py` | Pages Immich per source and granted trip window, writes rows, runs the matcher; takes `today` as an argument (no bare `date.today()` in a job). |
| Trip stats | `waypoint/domain/tripstats.py` | Per-trip figures from the segments the household already has, plus the photos the viewer may see (through `photos.visible`). Reuses `stats.distance_km`, `stats._nights` logic, `tripmap.road_legs` and `roads.Route.miles`. |
| Routes | `waypoint/server/api/photos.py`, listed in `waypoint/server/routes.py`, typed in `waypoint/server/contract.py` | Binary routes join `NOT_JSON` in `tests/test_every_route.py`; photo, photo-source and photo-grant routes join `BLOCKED` in `waypoint/server/mcp_access.py`. `tools/feature_map.py`'s `AREA_DOCS` maps `photos`, `photo-sources` and `photo-grants` to `start/photos`. |
| Web app | `frontend/src/lib/photos.ts`, `components/TripPhotos.svelte`, `components/PhotoGrantPrompt.svelte`, `components/PhotoViewer.svelte`, `components/TripSummary.svelte`, `components/settings/PhotosSection.svelte`, `components/settings/PhotoSharingSection.svelte`; pins in `components/RouteReplayMap.svelte` via `lib/route-replay.ts` | Dark only; tokens from `frontend/src/app.css`; `apiCall<"GET /api/…">` from `lib/contract.ts`. |
| Docs | `docs/src/content/docs/start/photos.md` | The user-facing page; every route must map to a docs page (`tests/test_every_route.py`). |

Promises touched (AGENTS.md, "Waypoint's promises"):

- **You see the trips you're on.** Photo routes answer 404 for a trip the viewer can't see, exactly like `GET /api/trips/{id}/places`. For photos, seeing the trip is necessary but not enough: another person's photo also needs that person's active grant with scope Trip, and no exclusion. Unlike bookings and costs, a trip's photos are not the same for everyone who can see it.
- **Times are where they happen.** A photo's time is shown as the wall-clock time where it was taken, never the viewer's zone.
- **Private data in logs.** Sync and proxy log counts and fixed error texts, never an Immich URL with a key, an asset id with a trip name, a place, or who granted what on which trip.

A new line for the promises list, added to AGENTS.md by the pull request that ships the proxy (#492), with the checks it names: "**Photos are shared by their person.** Photos stay in Immich. Waypoint keeps a photo's asset id, when and where it was taken and which trip it matched, nothing else, and only for trips its person shared their photos on. A photo reaches someone else only while its person's grant for that trip is active with the Trip scope, the viewer can see the trip and the photo is not excluded; everything else (the pixels through `GET /api/photos/{id}/…`, the trip photos reply, pins, clusters, the replay, the summary and its counts, Needs a look) is built from the photos that one predicate lets the viewer see, so nothing says that photos they can't see exist. Taking a photo back (excluding it, revoking the trip, switching to Only me) takes effect on the next request, and no reply lets a browser show a photo again without asking. The Immich address and key never reach the browser. Checked: no `Photo` query outside `photos.visible` (Semgrep's `waypoint-photo-access`), `tests/test_photo_access.py` (every path, for the person, a trip member under each scope, a stranger, the trip's owner and an assistant, before and after each removal), `tests/test_every_route.py`, and `no_leaks` with canary asset ids and places."

## Data model

Migration `0038_photos` (on main, #486) added `photo_sources`, `photos` and `photo_trip_syncs`. Migration `0039_photo_grants` (after 0038, with its `test_0039_…` in `tests/test_migrations.py`) adds `photo_grants`, `photo_exclusions` and `photo_sharing_prefs` and drops `photos.hidden` (below). Tables are declared in `waypoint/storage/schema.py` with `info={'doc': …}` and mapped in `waypoint/storage/models.py`. All six are in a backup (none joins `backup.SKIP`): the key travels encrypted as mailbox tokens do, the photo rows hold the person's decisions (moved to another trip), and the grants, exclusions and sharing defaults hold what each person chose to share, which a re-sync must not undo.

**`photo_sources`**: one Immich library Waypoint reads.

| Column | Type | Meaning |
| --- | --- | --- |
| `id` | int pk | |
| `person_id` | fk `people.id`, CASCADE, not null | Whose library it is: their photos can be used on the trips this person is on and has granted. |
| `owner_sub` | text, not null | The member who connected it (`users.sub`, or `local` without sign-in). Only they (or the household in local mode) can change or remove it; it ends when they can no longer sign in (`oidc.access_lapsed`, swept by `jobs.sweep_lapsed`). For a person with no sign-in, this member also acts for them on grants and exclusions (Terms). |
| `url` | text, not null | The Immich base address, scheme and host (and port), no path, no credentials. Shown in Settings. |
| `immich_user_id` | text, not null | The Immich user the key belonged to when connected (from `GET /api/users/me`). A new key must answer the same id, or the change is refused with a fixed sentence ("that key belongs to a different Immich account; remove this library and connect it again"), so one person's photos can never be re-attributed by swapping keys. |
| `api_key` | text, not null | Encrypted (`secretbox`). Never in a reply, a log or an error. |
| `label` | text | Optional name ("Jane's library"). |
| `status` | text, not null | `ok`, `refused` (401/403 from Immich), `unreachable`, `off` (paused by the owner). |
| `last_sync` | float | Epoch seconds of the last completed sync. |
| `last_error` | text | One of a few fixed sentences, never Immich's text. |
| `created` | float, not null | |

Unique on (`person_id`, `url`).

**`photos`**: one Immich asset Waypoint has looked at inside a granted trip window. Kept small on purpose: a reference and the match, no pixels, no file names, no camera data.

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
| `trip_id` | fk `trips.id`, SET NULL | The matched trip, or null. Only ever a trip the photo's person has an active grant for and the asset is not excluded from. |
| `segment_id` | fk `segments.id`, SET NULL | The nearest segment (by distance, else by time). |
| `match` | text, not null | `place` (GPS within NEAR of a segment of its trip), `time` (one trip's window, no GPS or no close segment), `far` (in a window but more than FAR from every point of that trip; matched, flagged), `ambiguous` (two granted windows, distance couldn't settle it; not shown on a trip until the person picks), `home` (within HOME of Home; ignored), `none` (no window). |
| `distance_km` | float | Distance to `segment_id`'s point, null without GPS. |
| `decided_by` | text | `auto`, or `owner` when someone acting for the photo's person picked its trip (moved it, or chose between ambiguous trips); the sync never overwrites an `owner` row's `trip_id`. |
| `seen` | float, not null | Epoch seconds the sync last saw it in Immich; a full re-list deletes rows not seen. |

Indexes: (`trip_id`), (`segment_id`, so deleting a booking finds its photos without scanning the table), (`source_id`, `taken_utc`), unique (`source_id`, `asset_id`).

`hidden` (added by 0038 for decision 3) is dropped by 0039: hiding a photo from its trip and excluding it from its trip are the same thing, and exclusion is the one mechanism (decision 3 and decision 15). 0039 first copies each `hidden = true` row that has a `trip_id` into `photo_exclusions` (its source's person, its asset id, its trip), then deletes every `photos` and `photo_trip_syncs` row, because no grant exists when 0039 runs and rows without a grant are not kept; the sync fetches the granted windows afresh. Nothing is live (the sync, #490, is not built), so this loses no one's photos. Its downgrade restores the column (all false) and drops the three tables.

**`photo_trip_syncs`**: what each source has fetched for each granted trip window, so a changed trip is re-fetched and an unchanged one is paged incrementally.

| Column | Type | Meaning |
| --- | --- | --- |
| `source_id` | fk CASCADE, pk part | |
| `trip_id` | fk `trips.id` CASCADE, pk part | |
| `window_start`, `window_end` | text, not null | The ISO UTC window last fetched. A trip whose window moved is fetched in full again. |
| `cursor` | text | Immich `updatedAfter` for the next incremental run: the start time of the last traversal that finished; null before the first complete fetch. Advanced only when a traversal completes, never part-way. |
| `resume_page` | int | The `page` to continue from when a run stopped inside a traversal (budget, 429, network); null when no traversal is in progress. The traversal keeps its own `fetch_started` so the next `cursor` is the time it began, not the time it was resumed. |
| `fetch_started` | text | UTC time the traversal in progress began; becomes `cursor` when it completes. |
| `synced` | float | |

A row exists only for a (source, trip) whose person has an active grant for that trip; revoking deletes it.

**`photo_grants`**: whether a person's photos may be used on a trip, and who sees them.

| Column | Type | Meaning |
| --- | --- | --- |
| `person_id` | fk `people.id`, CASCADE, pk part | The photo's person. |
| `trip_id` | fk `trips.id`, CASCADE, pk part | |
| `scope` | text, not null, default `only_me` | `only_me` or `trip` (a check constraint allows only these). |
| `revoked` | float | Null while the grant is active; epoch seconds when it was revoked or the prompt was declined. A revoked row grants nothing: it is kept so the trip is not asked about again and the sync never fetches its window. Granting again clears it. |
| `changed` | float, not null | Epoch seconds of the last grant, scope change or revoke. |
| `changed_by` | text, not null | The `users.sub` (or `local`) who made that change, shown to the person in Settings ("shared by you" or "shared by Sam, who manages this library"). Never logged. |

Primary key (`person_id`, `trip_id`), which also serves "this person's grants"; index (`trip_id`) for a trip's grants (every trip photos read joins on it, and a trip's deletion cascades through it). A grant belongs to the person, not to a sign-in: it does not lapse with `oidc.access_lapsed`, because it hands out nothing by itself (it lets others see photos only while a source of that person is connected, and a source does end with its `owner_sub`'s access).

**`photo_exclusions`**: a photo its person left out of a trip. Keyed by the Immich asset, not by `photos.id`, so it outlives the photo's row and a re-sync, a full re-list, a library removed and connected again, or a revoke and re-grant cannot bring the photo back.

| Column | Type | Meaning |
| --- | --- | --- |
| `person_id` | fk `people.id`, CASCADE, pk part | The photo's person. |
| `asset_id` | text, pk part | The Immich asset id (a UUID; the same asset seen through another source of the same person is the same exclusion). |
| `trip_id` | fk `trips.id`, CASCADE, pk part | The trip it is left out of. |
| `created` | float, not null | |

Primary key (`person_id`, `asset_id`, `trip_id`), whose prefix serves the sync's lookup per asset; index (`trip_id`) for a trip's deletion and for putting back a trip's exclusions. No foreign key to `photos`, on purpose.

**`photo_sharing_prefs`**: a person's default for the grant prompt, kept per person like `reminder_prefs`.

| Column | Type | Meaning |
| --- | --- | --- |
| `person_id` | fk `people.id`, CASCADE, pk | |
| `default_scope` | text, not null, default `only_me` | The scope the prompt and "all my trips" preselect: `only_me` or `trip` (check constraint). It grants nothing by itself. A person with no row has `only_me`. |

Settings keys (`waypoint/storage/settings_keys.py`): `PHOTOS_LAST_RELIST` (epoch of the last full re-list). No new environment variables; sources are set up in Settings so each member can add their own.

## Immich, as verified

Checked against the Immich API docs (v1.140 reference) on 2026-11-01; the spike confirms them on the family server, which may run a different version.

- **API keys are per user**, made under Account Settings, sent as the `x-api-key` header, and can be scoped to permissions (from 1.138; older servers need `all`). Waypoint asks for `asset.read` and `asset.view` (thumbnails and previews) and `user.read` (the Test step calls `GET /api/users/me`, which Immich protects with it); `asset.download`, because originals are served through Waypoint (decision 6).
- **`POST /api/search/metadata`** (searchAssets) takes `takenAfter` and `takenBefore` (date-time), `updatedAfter`, `page` (≥ 1), `size` (1–1000), `withExif`, `order` (`asc`/`desc`), `type` (`IMAGE`, `VIDEO`), `visibility` (`timeline`, `archive`, `hidden`, `locked`), `libraryId`. Reply: `assets.items`, `assets.nextPage`, `assets.total`, `assets.count`. Each asset: `id`, `type`, `localDateTime`, `fileCreatedAt` (UTC), `updatedAt`, `exifInfo.dateTimeOriginal`, `exifInfo.timeZone`, `exifInfo.latitude`, `exifInfo.longitude`, `exifInfo.city`, `exifInfo.state`, `exifInfo.country`.
- **`GET /api/map/markers`** takes `fileCreatedAfter`, `fileCreatedBefore`, `isArchived`, `isFavorite`, `withPartners`, `withSharedAlbums` and returns `{id, lat, lon, city, state, country}` per located asset. It has no time per marker, so the design uses metadata search as the one source and keeps markers as an optional cheap pre-pass the spike may recommend.
- **`GET /api/assets/{id}/thumbnail?size=thumbnail|preview|fullsize`** (viewAsset, `asset.view`) and **`GET /api/assets/{id}/original`** (`asset.download`).
- **`GET /api/server/ping`** / `GET /api/users/me` (`user.read`) to test a connection and learn the key's user: the name is shown once in Settings as "connected as …"; the user id is stored in `photo_sources.immich_user_id` to bind the source to that account.

To confirm in the spike (`PHOTOS-SPIKE`): whether `takenAfter`/`takenBefore` compare against `dateTimeOriginal` or `fileCreatedAt`; how a Darkroom-written XMP offset shows up (`exifInfo.timeZone` as an IANA name or `UTC±hh:mm`, and whether `localDateTime` follows it); whether `updatedAt` moves when Darkroom adds GPS through a sidecar (it must, or the incremental sync misses corrections); the real `size` ceiling and page time for the largest library; the thumbnail content type (WebP or JPEG) and preview dimensions; whether external-library assets answer `thumbnail` before the thumbnail job has run; what `visibility` the Darkroom assets carry; whether `assets.total` is filled for a `size: 1` search (the grant prompt's check, below, needs only "at least one"); and whether the server is reached over `http://` on the LAN or `https://` through Traefik.

## Consent: grants, scope and exclusion

**Asking.** A person is asked the first time they open a trip they are on that has photos in their library and no `photo_grants` row for them. The trip page calls `GET /api/trips/{id}/photo-sharing`, which answers only about the viewer's own person (never anyone else's): `shared` with its scope, `declined` (a revoked row), `ask`, or `none`. `ask` needs no grant row, a source of the viewer's person in `ok` status, and at least one asset in the trip's window, found by one live `search/metadata` with `takenAfter`/`takenBefore` of the window, `size: 1` and `visibility: "timeline"`; nothing from that request is stored, and the reply carries only "you have photos from these dates" with no count, place or time. A failed check answers `none` and asks again next time. The prompt (`PhotoGrantPrompt.svelte`) says what sharing means and offers:

- **Use my photos on this trip**, with the scope preselected from `photo_sharing_prefs.default_scope` (Only me unless changed): "Only me" or "Everyone on this trip".
- **Use them on all my trips**, with the same scope choice: one grant for each trip the person is on at that moment that has no row yet (trips they declined or revoked stay as they are). It is a one-time action, not a standing rule, so a trip the person joins later starts with no grant and is asked about when they first open it (decision 14).
- **No thanks**: a revoked row, so the prompt does not come back; the trip menu and Settings can share later.

Closing the prompt without choosing writes nothing and asks again next time. A person with no sign-in is never prompted; whoever acts for them grants in Settings, where each of that person's trips is listed.

**Granting** writes or clears the row and starts a sync of that person's sources for that trip in a thread, as **Sync now** does, so photos appear within a run rather than at the next schedule.

**Scope.** Switching between Only me and Trip only updates `scope` and `changed`; no photo row moves, because every read applies the predicate below at request time. Switching to Only me is a removal and takes effect on the next request (see "Removal").

**Excluding** a photo from a trip (`POST /api/photos/{id}` with `{"excluded": true}`, only by someone acting for its person) writes the `photo_exclusions` row and deletes the photo's `photos` row in the same transaction. The sync then treats that trip as not a candidate for that asset (Matching), so it stays out across syncs and re-lists. On the trip the photo is gone for everyone, including its person. Its person sees, in the trip's photo menu, "N photos you left out" with **Put them back**, which deletes that trip's exclusions for that person and resets the person's `photo_trip_syncs` rows for the trip so the next run fetches the window in full; the photos come back through the sync, never from a stored copy. A put-back is not per photo, because an excluded photo keeps no row to show a thumbnail from.

**Revoking** a trip (`DELETE /api/trips/{id}/photo-sharing`, or **Stop sharing** in Settings) sets `revoked`, and in the same transaction deletes the person's `photos` rows with that `trip_id` and their sources' `photo_trip_syncs` rows for the trip. Exclusions are kept, so sharing again later does not bring back what was left out.

**Removal**, whichever of the three, is immediate and complete:

- It is committed before the request that asked for it answers, and every path reads through the predicate at request time, so the very next request from anyone (a thumbnail, a preview, an original or a range request of a video already playing, the trip photos reply, the summary) no longer has the photo.
- What Waypoint keeps: for an exclusion, the `photo_exclusions` row (person, asset id, trip); for a revoke, the `photo_grants` row with `revoked` set, and the person's exclusions for that trip; for a switch to Only me, the grant and the person's own rows, which only the person still sees. Nothing else: no pixels were ever stored, and the photo rows that are deleted hold nothing that would bring a photo back.
- What it deletes: the derived match rows (`photos` rows, with their trip, segment, distance, inferred location, state and country) and the trip's `photo_trip_syncs` rows. Clusters, pins, counts, the summary's photo places and Needs a look entries are never stored: each is computed per request from the rows the predicate lets that viewer see, so they change with the rows.
- Browser caches cannot keep showing it: see the cache policy in "Proxy and access rules". Pixels already painted in another person's open tab cannot be recalled by a server; the web app re-reads the trip photos reply when the page becomes visible again and when the viewer opens a photo, and a photo whose preview answers 404 is dropped from the gallery with "This photo is no longer shared".
- A sync running at the moment of a removal cannot undo it: the sync checks the grant and the exclusions in the same transaction as each page's writes, and writes no row for a revoked grant or an excluded asset; a row written just before a revoke committed is deleted by the revoke, and in any case the predicate never shows it.

## Matching

`photomatch.match(photo, candidates, home) -> Match`, pure. Inputs: the photo (instant, GPS or none, person), the candidate trips with their windows and located points, and the household's Home point (`domain/home.py`, may be none).

**Candidate trips** are the trips the photo's person is on (`trip_people`, `trippeople.of`, which by Waypoint's rules already includes everyone named on any booking) **and** has an active grant for, less the trips this asset is excluded from. A trip the person is on but has not granted is never a candidate, so its window is never searched and none of their photos is matched, shown or counted on it. Being the booker or an email recipient does not make a trip a candidate: a parent who booked a child's trip does not get their own photos matched to it.

**A trip's window** is `[first live segment start − PAD, last live segment end + PAD]` as instants from each segment's own zone (`trips.instant`), falling back to `start_date 00:00` and `end_date 23:59` in the first and last segment's zones when a trip has dates and no times (a visit-only past trip). Cancelled segments don't count.

**Steps**

1. Drop the photo when its instant is in no candidate window: `none`. These rows are never written (the sync only asks Immich inside granted windows), so photos from ordinary days, and from trips not shared, never enter Waypoint.
2. With GPS within the Home radius for Home's precision (table below): `home`, ignored even inside a window (a road trip that starts at home gets its first photos at the first stop, not the driveway). A Home known only to the city has no radius: nothing is suppressed automatically, and a photo near it follows the normal steps (its person can exclude or move it).
3. Score each candidate window that contains the instant: the nearest live segment point of that trip (stays, cars, parking, trains and cruises use the point stored with the segment, `segments.latitude/longitude`; a flight uses its two airports; ports via `geocode.locate_port`), preferring segments active at that instant and breaking ties by time distance. Without GPS the score is the time distance to the nearest segment.
4. One candidate: it wins. With GPS: `place` when within NEAR km of a segment point, `far` when farther than FAR km from every point of the trip, else `time`. Without GPS: `time`.
5. Several candidates (an overlapping short trip inside a long one, both granted): with GPS, the trip with the smaller nearest distance wins when it beats the next by at least MARGIN km; otherwise, and always without GPS, the shortest window wins (the more specific trip). When the shortest window isn't unique: `ambiguous`, no trip, the person picks.
6. `segment_id` and `distance_km` are the nearest segment and its distance; a photo without GPS takes `where_was` below.

Because excluded trips are not candidates, a photo excluded from one of two overlapping trips is matched to the other; its person can exclude it there too.

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

A re-sync re-runs the matcher on every `auto` row of a source whose granted trips changed (a trip gained a booking, dates moved, a grant was given or revoked), and leaves `owner` rows' trip alone, except that an `owner` row whose trip is revoked or excluded is deleted with the removal like any other.

## Sync job

`photosync.run(conn, source, provider, today, now)`; `jobs.py` runs `sync_all` every `PHOTO_SYNC_EVERY` (6 hours, first run 10 minutes after start) and a **Sync now** button runs one source in a thread like `scan_now`. One source syncs at a time; a source in `refused` or `off` is skipped until its owner acts. A source whose person has no active grant fetches nothing.

For each source:

1. Load the person's trips that have an active grant, and their windows. Drop `photo_trip_syncs` rows, and delete the person's `photos` rows, for trips that no longer qualify (the person left the trip, or the grant was revoked and the revoke's own deletion was interrupted). Delete `auto` rows whose instant is in no granted window any more (a trip's dates shrank): they are outside what the person shared.
2. For each granted trip window: when the row is missing or the window moved, page `search/metadata` with `takenAfter`, `takenBefore`, `withExif: true`, `visibility: "timeline"`, `size: 1000`, `order: "asc"`, starting at `resume_page` when set (else page 1 with `fetch_started = now`); an incremental run adds `updatedAfter: cursor`. Windows overlap between trips; a photo seen twice is one row. For each asset, skip it when it is excluded from every candidate trip it falls in; otherwise upsert it: time fields, `asset_updated`, GPS, state and country, `seen = now`; run the matcher for `auto` rows with the candidates of Matching. Each page's writes commit in one transaction that first re-reads the person's grants and exclusions, so a revoke or an exclusion made while the page was fetched wins. Each finished page stores the next `resume_page`; when `nextPage` is null the traversal is complete: `cursor = fetch_started`, `resume_page` and `fetch_started` cleared. `updatedAfter` only filters; it never resumes a traversal.
3. Every `FULL_RELIST_DAYS` (7) a source is fetched without cursors and, once that traversal completes, rows not `seen` are deleted (trashed or deleted in Immich); an interrupted full re-list deletes nothing. A thumbnail or preview 404 from the proxy does not delete a row (see the proxy rules). Exclusions are never deleted by a re-list.
4. Record `last_sync`, counts (fetched, new, matched by kind, inferred, ambiguous, skipped as excluded) in the log through `monitoring.log`, counts only, never per trip or per person.

What changes outside the sync, and what happens:

- **A grant is given**: a sync of that person's sources for that trip starts at once (Consent).
- **A grant is revoked**: the deletions happen in the revoke's own transaction (Consent); the sync only cleans up after an interrupted one (step 1).
- **A person leaves a trip** (`trippeople` recomputed after a booking moves or is removed, or the person is taken off): in the same transaction, `photogrants.left(conn, person, trip)` deletes their `photo_grants` row for it (so if they are added again they start with no grant and are asked again, decision 14), their `photos` rows on it and their sources' `photo_trip_syncs` rows for it. Their exclusions for the trip are kept, so a later re-grant still leaves those photos out.
- **A person is added to a trip**: nothing; they have no grant and are asked when they first open it. Other people's grants on the trip are unchanged, and photos with scope Trip become visible to the newcomer because they can now see the trip, as bookings do.
- **A trip's window changes** (a booking added, moved or cancelled, dates edited): grants are per trip, not per window, so they stand; the next run fetches the new window in full for each granted person (the stored window no longer matches), re-matches `auto` rows, and step 1 deletes rows left outside every granted window.
- **A trip is deleted**: its grants, exclusions and `photo_trip_syncs` rows go with it (CASCADE); its photos' `trip_id` becomes null and step 1 deletes them on the next run; until then the predicate shows them to no one, since rule 1 needs a trip and its one other case covers only `ambiguous` rows.
- **Trips are merged**: see decision 12.

Budget: a page of 1000 assets with EXIF is a few megabytes; a two-year window on first fetch is tens of pages. `TIME_BUDGET` (10 minutes per source per run) stops a run cleanly after the current page; the next run continues from `resume_page`, as the mail scan resumes, and the update watermark moves only when the traversal finishes, so a large library is never left with assets skipped. 429 backs off; 401/403 sets `refused`; a network error sets `unreachable` and the status page says so.

Darkroom's rescans and sidecars change assets' `updatedAt`, so GPS added later arrives on the next incremental sync and the matcher re-runs for that row.

## Proxy and access rules

### Who sees a photo

One access predicate, `photos.visible(viewer)` in `waypoint/domain/photos.py`, a SQL condition over `photos` joined to `photo_sources`, `photo_grants` and `photo_exclusions`. Every path that reads `photos` applies it, and nothing else decides: no path has its own filter. A viewer may see a photo when all of these hold:

1. The photo has a trip, and the viewer can see that trip (`visibility.visible_trip`).
2. The grant for (the photo's person, that trip) exists and `revoked` is null.
3. The viewer acts for the photo's person, or the grant's `scope` is `trip`.
4. No `photo_exclusions` row exists for (the photo's person, its asset id, that trip).

The one other case: someone acting for the photo's person may see that person's `ambiguous` rows (no trip yet), in Needs a look and through the three image routes, with only the granted trips they fall in, and are not excluded from, offered as choices. `home` rows are kept (so a re-sync does not match them again) but served to no one; `none` rows are never written. There is no case for the trip's owner, a booker, an email recipient, the household admin (outside local mode without sign-in, where the household acts for everyone), or an assistant.

Every path below is built from the rows this predicate returns for the viewer, and only from them:

- `GET /api/photos/{id}/thumbnail`, `/preview`, `/original`: 404 unless the predicate holds for that photo.
- `GET /api/trips/{id}/photos` (photos, clusters, counts, per-person counts): from the visible rows only. A person whose photos the viewer can't see does not appear in `people`, and no count, cluster size, cover, first or last time includes their photos.
- The map's pins and the route projection's fit, and the replay's lighting of pins: from that reply's clusters, so an invisible photo never widens the map or lights a pin.
- `GET /api/trips/{id}/summary`: the photo count, the inferred count, and the states and countries that photos add, from the visible rows only. A state only an invisible photo was taken in is not listed.
- `GET /api/photos/review` (Needs a look): only rows of persons the viewer acts for.
- `GET /api/photo-sources`: a source's counts and last sync only to those who act for its person or connected it; everyone else sees its person, host and status, so a library's size says nothing about trips they can't see.
- `GET /api/trips/{id}/photo-sharing`: only the viewer's own grant state; no route tells anyone whether another person granted, declined, chose Only me, or has a library with photos from those dates.

So two people on the same trip can see different photos, different counts and a different set of places, and neither reply hints at the difference: the reply has the same shape and wording whether or not photos they can't see exist. A photo id the viewer may not see answers exactly like one that does not exist.

A Semgrep rule, `waypoint-photo-access`, fails a `select(Photo…)` or `Photo.` query in `waypoint/server/` or `waypoint/domain/` outside `photos.py`'s predicate helpers, `photogrants.py`'s removals and `photosync.py`'s writes, like `waypoint-trip-visibility` does for trips; `tripstats.py` asks `photos.visible_rows(conn, viewer, trip_id)` instead of its own query.

### Routes

All need sign-in; `tests/test_every_route.py` holds that.

| Route | Who | What |
| --- | --- | --- |
| `GET /api/photos/{id}/thumbnail` | the predicate (with its `ambiguous` case) | Immich `thumbnail` (grid tile). |
| `GET /api/photos/{id}/preview` | the predicate (with its `ambiguous` case) | Immich `preview` (lightbox). |
| `GET /api/photos/{id}/original` | the predicate (with its `ambiguous` case) | Immich `original`, streamed (`Response.stream`), for the "Open original" action and videos. |
| `POST /api/photos/{id}` | acting for its person, and the predicate (or an `ambiguous` row of theirs) | `{"trip_id": …}` moves it to a trip the person is on and has granted (otherwise "Share your photos on that trip first"); `{"excluded": true}` excludes it from its trip (an `ambiguous` row: `{"excluded": true}` excludes it from every trip it could belong to, "None of these"). Replaces the old `{"hidden": …}`, which is refused. |
| `GET /api/trips/{id}/photo-sharing` | anyone who can see the trip, about their own person | `shared` (scope), `declined`, `ask`, `none`; and the count of their own exclusions on it. |
| `PUT /api/trips/{id}/photo-sharing` | acting for the person (`person_id` in the body, default the viewer's) and on the trip | `{"scope": "only_me" \| "trip"}` grants or changes the scope; `{"declined": true}` records No thanks. |
| `DELETE /api/trips/{id}/photo-sharing` | same | Revokes (`person_id` as a query parameter, default the viewer's). |
| `DELETE /api/trips/{id}/photo-exclusions` | same | Puts back that person's excluded photos on the trip. |
| `GET /api/photo-grants` | signed in | The grants and trips of every person the viewer acts for, for Settings. |
| `POST /api/photo-grants/all` | acting for the person | `{"person_id", "scope"}`: grants on each of their current trips with no row (Consent). |

Each grant route answers 404 for a trip the viewer can't see or a person they don't act for, the same text as a missing trip.

### Rules

- The photo id is Waypoint's; the handler finds the row through the predicate; a missing row, a photo the predicate refuses, a stranger or an assistant all get 404 with the same text (`NO_IMAGE`), and the check costs the same whichever it is (the row lookup and the predicate are one query).
- The upstream request goes through `providers/immich.py` with the decrypted key from `storage/photo_sources.py`; the key never appears in a URL, a log, an exception text or a reply header. Only the body and a sniffed content type come back; Immich's own headers are dropped, except the range headers of an original (below). Thumbnails and previews are `image/webp`, `image/jpeg` or `image/png`. Originals are checked against an allowlist by magic bytes, not by Immich's header: browser-renderable images (JPEG, PNG, WebP, GIF, AVIF) and video (`video/mp4`, `video/quicktime`, `video/webm`) are served inline; HEIC/HEIF, TIFF, RAW and Matroska are served as `Content-Disposition: attachment` with their sniffed type or `application/octet-stream`; anything else, and always SVG and HTML, is 404. Every reply carries `X-Content-Type-Options: nosniff`.
- Caps: thumbnails 2 MB, previews 10 MB, read in chunks under a time budget (`mailimages.py` is the pattern); originals stream without a size cap under a 10-minute budget, and honour byte ranges: a valid single `Range` header is forwarded to Immich, and its `206`, `Content-Range`, `Content-Length` and `Accept-Ranges` come back, so a video seeks and resumes; a malformed or multi-range request is answered as a full body. Each range request runs the predicate again, so a video stops loading once it is taken back. A 404 or 410 on a thumbnail or preview keeps the row (Immich may not have generated an external-library rendition yet) and answers 404 to the viewer, retryable; only when a follow-up `GET /api/assets/{id}` (`asset.read`) also answers 404 or 410 is the row deleted. 401/403 marks the source `refused` and answers 404 to the viewer.
- Cache policy, so that removal is immediate in browsers too: thumbnails and previews answer `Cache-Control: private, no-cache` with an ETag of (photo id, size, `asset_updated`). `no-cache` lets the browser keep the bytes but never show them without asking first; each use sends `If-None-Match`, the server runs the predicate, and answers `304` (no Immich request, so a gallery revisit stays cheap) when it holds and the ETag matches, `200` with the new rendition when the ETag changed, and `404` once the photo is removed. Originals answer `Cache-Control: private, no-store`. No reply carries `max-age`, `immutable` or `Expires`, and nothing is cacheable by a shared proxy. The web app keeps no photo in the Cache API, IndexedDB or a service worker (the offline vault holds none, below), and its in-memory object URLs for the lightbox are revoked when the photo is dropped. Plus `image_response`'s CSP (`default-src 'none'; sandbox`). The server never writes pixels to disk or the database.
- Assistants: `/api/photos`, `/api/photo-sources`, `/api/photo-grants` and the `/api/trips/{id}/photo-…` routes join `BLOCKED` in `mcp_access.py`; `/mcp` returns nothing about photos, grants or exclusions, not even counts.
- The offline copy (`GET /api/offline`) carries no photos, no photo counts, no grants and no exclusions, so a removal never waits on a device's saved copy.
- Sources: `GET /api/photo-sources` lists every source for the household (person, host, status; counts and last sync only as "Who sees a photo" says; `mine` for the viewer's own); `POST /api/photo-sources` creates one for any person in People; `POST /api/photo-sources/{id}` (key, label, paused) and `DELETE` answer only its `owner_sub` (or the household in local mode); `POST …/test` pings Immich with the key and reports the user it belongs to without saving anything; `POST …/sync` starts a run. A new key replaces the old one only when it belongs to the same Immich user as the stored `immich_user_id`; the old one is never shown. Deleting a source deletes its photos (CASCADE); the person's grants and exclusions stay, so connecting the library again shares exactly what was shared before and nothing that was excluded.
- Lapsed access: `photos.end_lapsed` (in `jobs.sweep_lapsed`, next to `gmail.end_lapsed`) deletes a source whose `owner_sub` can no longer sign in.
- Demo and `make verify`: `demo.seed` adds a source per demo person with `url = "demo"` (no key), grants on the demo trips (one with scope Trip, one with Only me, one trip with no grant so the prompt shows, and one exclusion) and photo rows across the granted trips; for a `demo` source the proxy serves a deterministic generated PNG (`photos.placeholder(asset_id, size)`, a gradient tile like `demo._png`) and the prompt's check counts the demo rows, and neither ever opens a connection, so `make verify` runs with its network blocked and the pages still show photos.

## Map and stats

**Map.** The trip page already draws the route from the segments (`RouteReplay.svelte` → `GET /api/trips/{id}/places` → `domain/tripmap.py`: airports, stays, road legs along US highways, state lines). Photos add a layer, not a second map: `GET /api/trips/{id}/photos` returns the photos the viewer may see and their clusters, and `RouteReplayMap.svelte` draws a pin per cluster (size by count, hollow when every photo in it is inferred), projected with the same `routeProjection`, which is extended to fit the stops and the cluster coordinates together (a trip with no stops fits the clusters alone; a single cluster gets a fixed regional zoom), so a `far` cluster hundreds of kilometres away is still inside the map. During a replay a cluster lights up when the replay passes its first photo's time (the replay already tracks `stopDates`). Tapping a pin scrolls the gallery to that cluster. Today the map shows only for a trip that has ended with two placeable stops; with photos it shows for any trip with at least one cluster the viewer may see or two stops, and the replay controls appear only when the route is replayable. Because clusters come from the viewer's visible rows, whether the map appears at all, its extent and its pins never reveal photos the viewer can't see; when a removal empties the clusters, the next read of the reply drops the pins and, for a trip with fewer than two stops, the map.

**Clusters** are built server-side in `photos.clusters(rows)`, per request, from the predicate's rows for the viewer: greedy by time order, a photo joins the first cluster whose centroid is within CLUSTER km, else starts one; each cluster carries centroid, count, first and last local time, cover photo id and whether it is all-inferred. The reply caps clusters at 400 (merging the smallest neighbours past that), so a two-year trip stays drawable on a phone. Nothing about clusters is stored.

**Stats** (`domain/tripstats.py`, `GET /api/trips/{id}/summary`): days (trip dates), nights away (union of stay and cruise nights, as `stats._nights`), distance (flights: great-circle between airports via `stats.distance_km`; road: `tripmap.road_legs` miles where a highway route exists, else straight-line between consecutive placed stays, labelled "about"), states and countries (from segment addresses and visit details via `geocode`/`regions`, plus the `state`/`country` of the trip's photos that the viewer may see, from Immich, leaving out `far` photos until their person accepts or moves them, so one wrong-clock or unrelated photo cannot add a place to the trip; US states listed by name, other countries by name), photo count with how many are inferred (the viewer's visible photos), and bookings by kind. The web app shows distance in the household's `distance_unit` as Stats does. The segment-based figures are the same for everyone who can see the trip; the photo-based ones are per viewer.

## Settings screen

Settings gains a **Photos** section (`PhotosSection.svelte`, after Gmail): one card per source with person, host, status chip, last sync, photo count (for those "Who sees a photo" allows), **Sync now**, **Change key**, **Pause**, **Remove**; and **Connect an Immich library**: person (from People; defaults to the signed-in member's), Immich address, API key (with the permissions to tick listed), **Test** before **Save**. Permissions to tick: `asset.read`, `asset.view`, `user.read` and `asset.download` (originals are served through Waypoint). Copy says plainly what Waypoint reads ("photos taken during the trips you share them on and the 12 hours around them; Waypoint keeps when and where for each, including photos that turn out not to belong to a trip, never the pictures").

Below it, **Photo sharing** (`PhotoSharingSection.svelte`), for each person the viewer acts for:

- **Default for new trips**: Only me (default) or Everyone on the trip, the scope the prompt preselects (`photo_sharing_prefs`). It grants nothing by itself.
- **Use my photos on all my trips**: the one-time action of the prompt, with a scope choice.
- One row per trip the person is on: not asked, shared (with an Only me / Everyone on this trip switch and **Stop sharing**), or declined (**Share**); with "N left out" and **Put back** where there are exclusions. Copy under the list: "Stopping or switching to Only me takes effect at once, for everyone. Photos you leave out stay out."

The same per-trip controls (share, scope, stop sharing, put back) are in the trip page's photo menu for the viewer's own person.

## Decisions

Settled by the owner in #484 (1–12; 3, 4 and 12 revised by #504) and in #504 (13–20).

1. **Thresholds**: the table above.
2. **A photo that fits two overlapping trips**: GPS decides when it can (MARGIN); otherwise the shorter trip; a tie waits for its person under "Needs a look". Only granted trips the photo is not excluded from compete.
3. **Hiding**: superseded by exclusion (decision 15). A person hides a photo from a trip by excluding it; there is no separate hidden state, and 0039 drops `photos.hidden`. Nobody else can exclude another person's photo, and the trip's owner cannot hide anyone's photos.
4. ~~**Who sees whose photos**: everyone who can see a trip sees all its photos, from every library.~~ Superseded by #504: a person's photos are used on a trip only with their grant, and seen by others only under the Trip scope (decisions 13–17).
5. **Sync**: every 6 hours, a full re-list weekly, Sync now per source; first run 10 minutes after start; a grant starts a sync of that trip at once.
6. **Originals through Waypoint**: yes, streamed, needing `asset.download` on the key, under the same predicate and with `no-store`.
7. **Videos**: included (thumbnail from Immich, original streamed on tap).
8. **Archived photos**: skipped (`visibility: timeline` only).
9. **Who may connect a library for whom**: any signed-in member for any person in People (children without a login). Connecting a library shares nothing: its person's grants decide, and for a person without a login the member who connected it acts for them.
10. **`far` photos**: shown on the trip with a flag (to those the predicate allows), and listed under "Needs a look" for their person.
11. **States crossed**: Immich's reverse-geocoded state per photo plus the booking addresses is enough. State lines crossed by the route are not counted from photos in v1, a scope choice; counting them would be a later issue.
12. **Merging trips**: the merged-away trip's photos become unassigned and its grants go with it, because its people become people on the surviving trip, and a person added to a trip starts with no grant (decision 14); each is asked on the surviving trip. Its exclusions move to the surviving trip (the same person and asset, deduplicated), so a photo left out stays out. The sync matches the automatic photos (`decided_by` auto) again for each person who grants the surviving trip, when it next fetches them: at once on the grant. The ones placed by hand (`decided_by` owner) stay unassigned, because the sync never overwrites an owner row's trip, and step 1 of the sync deletes them if they are in no granted window. The merge itself carries no photos over.
13. **Per-trip grant**: each person must grant access, per trip, for their photos to be used on it. Without an active grant their photos on that trip are not fetched, matched, shown, counted, pinned or in the trip summary, for anyone, including them.
14. **When it is asked**: the first time a person opens a trip that has photos in their library, with a one-tap "use them on all my trips" (a one-time grant on their current trips, not a standing rule). A person added to a trip later starts with no grant, whatever they chose elsewhere, and so does anyone whose grant was deleted when they left a trip.
15. **Exclusion**: a person can exclude single photos from a trip they granted; excluded photos are never shown, counted or pinned, and stay excluded across syncs, re-lists, a revoke and re-grant, and a library reconnected. This is also how a photo is hidden (decision 3); Needs a look's **Hide** becomes **Leave out of this trip** for a `far` photo and **None of these** for an `ambiguous` one.
16. **Scope**: each grant is Trip (other people who can see the trip see the photos) or Only me; the default is Only me. The trip's owner cannot see Only me photos; nobody but those acting for the photo's person can.
17. **No hint of photos you can't see**: other people on a trip cannot tell that someone has photos they cannot see: counts, per-person counts, pins, clusters, the map's extent, the replay and the summary never reveal them, and no route reports another person's grant state.
18. **Removal is always possible and immediate**: whoever shared a photo can take it back, a single photo (exclude), a whole trip (revoke) or by switching to Only me, at any time, and it takes effect at once for everyone and every path: thumbnails, previews, originals and ranges, the trip photos reply, clusters and pins, the replay, the summary and its counts, Needs a look, the offline copy and `/mcp` (which never carry photos). Waypoint keeps only the exclusion or the revoked grant, so a re-sync cannot bring the photo back, and deletes the derived rows.
19. **Cache policy**: thumbnails and previews `private, no-cache` with the ETag revalidated through the predicate on every use (404 once removed); originals `private, no-store`; no photo in any browser storage.
20. **The trip's owner gets no special access**: there is no owner case in the predicate; Needs a look and every photo action are for those acting for the photo's person.

## Open questions

- Should `get_trip` over `/mcp` say how many photos a trip has? Left out of v1; if it is added, the count must come from `photos.visible` for the connection's member, never a trip-wide total.
- Should the household Stats page (`domain/stats.py`) count photos per year? Left out of v1; the same rule would apply (the viewer's visible photos only).
- A trip with photos but no placeable segment (a trip typed in by hand with no addresses) gets a map of pins alone; is that wanted, or should the map need at least one stop?
- Live Photos and burst stacks: Immich stacks them; `withStacked` is off, so each asset is a photo. Fine for v1?
- Restoring a backup puts grants and exclusions back as they were when it was made, like every other table, so a photo taken back after that backup would be shared again. Should a restore keep the current revocations and exclusions (and Only me switches) where they are newer, or is a warning on the restore screen enough?
- Should a person with no sign-in be acted for by every member who connected one of their libraries, or only the first? This design says each source's `owner_sub`, so two members who each connected a child's library both act for the child.

## Impact on the issues

What each existing issue must change for this revision; the follow-up issues are written from it.

- **#486 (photo tables, closed): follow-up migration.** A new issue for `0039_photo_grants`: `photo_grants`, `photo_exclusions` and `photo_sharing_prefs` as in Data model (keys, CASCADE rules, `scope` check, `trip_id` indexes), the copy of `hidden` rows into exclusions, the deletion of `photos` and `photo_trip_syncs` rows, dropping `photos.hidden`, a downgrade, `test_0039_…`, models and `info` docs, and a backup round-trip test with the three tables (none in `backup.SKIP`).
- **#488 (matcher, closed)**: candidates come in already filtered; a follow-up passes only granted, not-excluded trips from `photos.candidate_windows` (which lives in `photos.py`) and tests that an ungranted or excluded trip is never matched and that exclusion from one of two overlapping trips gives the other. `photomatch.py` itself stays pure and unchanged.
- **#489 (sources API)**: counts and last sync in `GET /api/photo-sources` only for those acting for the person or who connected it; Settings copy names the sharing; deleting a source keeps grants and exclusions; tests for each.
- **#490 (sync job)**: only granted (person, trip) windows; the per-page transaction re-reads grants and exclusions; skip excluded assets; step 1's clean-up; the start-at-once on a grant; `photogrants.left` called where `trippeople` changes; the merge carrying exclusions; demo grants and exclusion in `demo.seed`.
- **#491 (trip photos reply and Needs a look, closed)**: a follow-up replaces the `hidden` filter with `photos.visible`, drops `counts.hidden` and `TripPhoto.hidden`, limits `people` to visible rows, replaces `{"hidden"}` in `POST /api/photos/{id}` with `{"excluded"}`, refuses a move to an ungranted trip, offers only granted trips as Needs a look candidates, and adds the grant routes (`/api/trips/{id}/photo-sharing`, `/photo-exclusions`, `/api/photo-grants`, `/api/photo-grants/all`) with `domain/photogrants.py`, their `BLOCKED` entries, contract types and `tests/test_photo_access.py`; the Semgrep rule `waypoint-photo-access`.
- **#492 (streaming)**: the predicate for every request including each range request; `private, no-cache` with ETag revalidation through the predicate for thumbnails and previews (304 / 200 / 404), `private, no-store` for originals; the "Photos are shared by their person" promise added to AGENTS.md; tests that a removal answers 404 on the next request and that a revalidation after removal is a 404, not a 304.
- **#493 (trip summary, closed)**: a follow-up makes `tripstats._photos` use `photos.visible_rows` (dropping its own `hidden` filter), with tests that an Only me or excluded photo adds no state, country or count for another viewer.
- **#496 (photo strip, gallery and viewer)**: the grant prompt (`PhotoGrantPrompt.svelte`), the trip's photo menu (share, scope, stop sharing, leave out, put back), re-reading the reply on visibility and on opening a photo, dropping a photo whose preview answers 404 with "This photo is no longer shared", revoking object URLs, and no photo in any browser storage.
- **#497 (map pins)**: pins, the map's fit and its appearance from the reply's clusters only (already so), re-drawn when the reply is re-read after a removal; a test that a viewer with no visible photos sees the map exactly as a trip with no photos.
- **#498 (summary line)**: shows the per-viewer photo figures as they come; no copy that implies others' photos ("your photos", not "all photos").
- **#499 (Needs a look)**: **Hide** becomes **Leave out of this trip** (`far`) and **None of these** (`ambiguous`), both through `{"excluded": true}`; candidates only granted trips; only for persons the viewer acts for.
- **#485 (designs)**: add the grant prompt, the trip's photo menu, the Settings **Photo sharing** section and the "no longer shared" state of the viewer to the designs for sign-off; the gallery and summary designs show one viewer's photos, with no count of others'.
- **`docs/src/content/docs/start/photos.md`**: its "Who sees what" describes the behaviour on main ("everyone who can see a trip sees all of its photos", hiding); the #491 follow-up rewrites it for grants, scope and exclusion when that behaviour ships.
