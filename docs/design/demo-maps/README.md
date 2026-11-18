# Apple's maps in the public demo: the options (#834)

**Decided: option C (owner, 2026-11-18): no maps in the public static demo.** The decision is recorded in [this comment on #834](https://github.com/AnthonyPluth/Waypoint/issues/834#issuecomment-6982585262). No Apple token or key is made or stored for the demo, and nothing is copyable from the demo page. The shared-allowance risk (a copied token spending the household's daily Apple allowance) was not accepted, which is why C was chosen over B. The `github.io` domain question is moot. The docs page [Maps in the demo](../../src/content/docs/contributing/demo-maps.md) says what the demo and the docs screenshots show.

What the demo does under C is built by the MapKit-only plan's renderer step, [#836](https://github.com/AnthonyPluth/Waypoint/issues/836), as the signed-off [MapKit-only design](../mapkit-only/README.md) says: no maps and no replay in the static demo, the grid stand-in in the docs screenshots. #834 adds nothing to build.

The rest of this page is the analysis the owner decided on. It stays as the record of why, and of what a future revisit would take. **Options A, B and B2 were not adopted.** Nothing below is an instruction to create a token, a key, a GitHub environment or a secret.

## Where things stand

- The MapKit-only design ([`docs/design/mapkit-only/README.md`](../mapkit-only/README.md), signed off on #833) removes the bundled SVG renderer. The static demo shows no maps and no replay, and the docs screenshots show the grid stand-in ([#836](https://github.com/AnthonyPluth/Waypoint/issues/836)). #834 keeps it that way.
- The static demo is `frontend/demo/`, built by `npm run build:demo` into `frontend/demo-dist/` and checked by `demo/verify.mjs`. `make docs-site` copies it to `docs/dist/demo/`, and `.github/workflows/docs.yml` publishes it to GitHub Pages at `https://anthonypluth.github.io/Waypoint/demo/` from `main`. The workflow calls fleet's reusable docs workflow (`AnthonyPluth/fleet/.github/workflows/docs.yml`, v4.0.0). Its build job has no environment and takes no secrets. Only its deploy job runs in an environment (`github-pages`).
- The demo page's Content-Security-Policy (`frontend/demo/index.html`) is `connect-src 'none'` and `worker-src 'none'`. `demo/verify.mjs` fails on any request that leaves the page. `frontend/demo/api.ts` answers `/api/state` with no MapKit.
- The app signs a 30-minute MapKit JS token for `WAYPOINT_PUBLIC_URL`'s origin with the household's private key (`waypoint/domain/maps.py`, `waypoint/providers/mapkit.py`: `scope` `mapkit_js`, `origin`, `iss` the Team ID, `kid` the Key ID). The same key also signs the Maps Server API tokens the nightly route warming uses (`sign_server`, `scope` `server_api` on retry).
- `make verify` makes a throwaway EC key per run (`mapkit_env` in `waypoint/verify.py`), and `frontend/verify/verify.mjs` answers every request to `*.apple-mapkit.com` with `fake-mapkit.js`, a grid. Nothing in the repository holds a real key or token. `tests/test_app_push.py` has a made-up `BEGIN PRIVATE KEY` block, the only key-shaped text tracked (checked with `git grep` on `origin/main` at `076a4f1`).

## What Apple says, and what we couldn't confirm

Checked on 2026-11-18, for a future revisit. Apple's HTML pages render only a title for a fetcher, so these are the Markdown versions of the documentation pages (the `.md` URLs) and the developer forums.

| Fact | Source | Confirmed? |
| --- | --- | --- |
| Static Maps tokens can be made in the developer account, with no private key: Token Type Embed API, MapKit JS, Server API or Web Snapshots; Restriction Domain or None; for Domain, a duration of No Expiration, 30, 90 or 180 Days, or Other (a date); a comma-separated list of domains; **Revoke** invalidates a token | [Creating a Maps token](https://developer.apple.com/documentation/mapkitjs/creating-a-maps-token.md) | Yes, Apple's documentation |
| A signed token's `origin` takes a domain, a pattern like `*.example.com` or a comma-separated list, and is required when `scope` includes `mapkit_js`, `web_snapshots` or `embed_api`. Apple suggests one token per scope. A static token works for every framework except the Maps Server API | [Creating and using tokens with Maps Server API](https://developer.apple.com/tutorials/data/documentation/applemapsserverapi/creating-and-using-tokens-with-maps-server-api.md) | Yes |
| A private key doesn't expire but can be revoked. Separate Maps IDs and keys per environment are "good practice". The `.p8` downloads once. A key's only Maps checkbox is MapKit JS | [Creating a Maps identifier and a private key](https://developer.apple.com/documentation/applemapsserverapi/creating-a-maps-identifier-and-a-private-key.md) | Yes. So a key can't be limited to MapKit JS without the Server API: the restriction is in the token's `scope`, not the key |
| The longest lifetime of a **signed** MapKit JS token (`exp`) | Not stated in either token page. Third-party tools default to 180 or 364 days (e.g. [mapkitjs-token](https://github.com/kchung/mapkitjs-token)) | **No.** Unknown |
| How far out the portal's "Other" date can be | Not stated. A third-party guide says one year | **No** |
| Free allowance: 250,000 map views and 25,000 service calls a day **per Apple Developer Program membership**, more on request | [MapKit JS](https://developer.apple.com/maps/mapkitjs/) | Yes, Apple's product page |
| 25,000 unique Web Snapshot requests a day per membership | [MapKit JS pricing](https://developer.apple.com/maps/mapkitjs/pricing) | Yes |
| MapKit JS and the Maps Server API share the 25,000 service calls, and past it Apple answers 429 | [WWDC22 "Meet Apple Maps Server APIs" notes](https://wwdcnotes.com/notes/wwdc22/10006) (community notes of Apple's session) | Partly: a secondary source |
| Overage is refused, not billed | Forum threads ask and get no answer ([thread 818109](https://developer.apple.com/forums/thread/818109), [127493](https://developer.apple.com/forums/thread/127493)). Apple's page says "contact us" | **No** |
| Web Snapshots accept a `token` parameter (a static token) instead of a signature, with the token's expiry and origin restriction applying | [Forum thread 756958](https://developer.apple.com/forums/thread/756958), an Apple Frameworks Engineer, 2024. The [snapshot signing page](https://developer.apple.com/documentation/snapshots/generating-a-url-and-signature-to-create-a-maps-web-snapshot.md) still says every URL needs a signature | Partly: forum only |
| How Apple enforces the domain restriction (the browser's `Origin` or `Referer`, which a script outside a browser can set to anything) | Not documented | **No.** This page assumes a copied token works from anywhere until it expires or is revoked |
| How quickly a revocation takes effect | Not documented | **No** |

## The options

Only C was adopted. All of them keep the household's key out of the demo. The question is where the demo's token comes from.

### A. A small token endpoint (not adopted)

A function on some host (a Cloudflare Worker or similar; never the household's own Waypoint, which would then answer the public) holds a demo-only private key and signs a 30-minute MapKit JS token for `https://anthonypluth.github.io`. It checks the `Origin` header and rate-limits by IP.

- **Abuse:** the `Origin` check stops another website's pages, but not a script, which sets any `Origin` it likes, and a rate limit per IP doesn't hold against many IPs. So anyone can still get a fresh token whenever they want. The blast radius is the same as option B's: the membership's daily allowance.
- **Cost:** new infrastructure outside GitHub, a new account, a private key on an internet-facing host (a key can sign any scope, including `server_api`, for any origin and any lifetime, so leaking it is worse than leaking a token), its own monitoring, and a request that leaves the demo on every map. The demo stops being "static files only".
- **Gain:** short-lived tokens, logs of who asks, and a switch you can turn off without Apple's portal (revoking in the portal is as quick).

### B. A static, domain-restricted token made in Apple's portal (proposed, not adopted)

The owner would have made a MapKit JS token in the developer account, restricted to `anthonypluth.github.io`, valid for 180 days. It would have been stored as a secret in a GitHub environment restricted to `main`, and only main's Docs build would have read it and written it into the demo bundle. The step-by-step setup was removed when C was chosen, so nobody creates one by following it. A revisit would write it again from Apple's [Creating a Maps token](https://developer.apple.com/documentation/mapkitjs/creating-a-maps-token.md) and the `testflight` environment in `ios/README.md`.

- **No private key exists for the demo.** The token can't reach the Maps Server API (type MapKit JS) and can't sign anything.
- **Abuse:** anyone can copy it from the page. Assuming the domain check can be faked, it works for anyone until it expires or is revoked. The most they can do is spend the membership's daily allowance (250,000 map views, 25,000 service calls). Then the household's own maps and the nightly route warming fail until the next day (`route_warming.run` stops a night's work on a `ServerError`, which a 429 is, and tries again the next night). As far as Apple says, it is not billed (unconfirmed, above).
- **Capped by:** the 180-day end date, revocation in the portal, the domain restriction against other websites, and Apple's own daily cap. The only full cap on the household's side is a separate membership (the owner's answer 2).
- **Expiry:** when the token runs out, MapKit fails to start, and the demo behaves as the app does without a key under the MapKit-only design: maps hidden, the replay's "The map couldn't load". The owner would make the next token, with a scheduled reminder ahead of the end date (its date kept as a repository variable, or read by a job that names the environment: a job sees an environment's variables only when it declares `environment:`) and an overlap so the demo never goes dark.
- **Cost:** a fleet change, because fleet's reusable docs workflow has no way to give its build job an environment or a secret plus a small demo build change.

### B2. A token signed at build time (not adopted)

Like B, but main's Docs build signs a JWT with a demo-only private key stored in the environment, with the longest `exp` Apple accepts, which is not documented. This is worse than B: a private key sits in CI instead of a token, and it buys nothing, since the signed token is just as public on the page. Only worth it if portal tokens turn out to be unavailable for this membership.

### C. No maps in the static demo (adopted)

What the MapKit-only design builds in #836: no token, no risk, nothing sent to Apple. The demo shows the kinds tiles, no Stats map and no replay. The docs screenshots still show the stand-in. A visitor sees less of what Waypoint does.

### The Past trips cards

The cards use Apple's Web Snapshots in the app (#837). A pre-signed snapshot URL per card, made at build time, needs the private key in CI (B2's problem). A static Web Snapshots token can make any snapshot and spends the separate 25,000-a-day snapshot allowance. Under C the demo's cards show the kinds tile.

## Recommendation and decision

The proposal recommended **B**: one static MapKit JS token, restricted to one domain, valid for 180 days, made in Apple's portal. It added no private key and no server, and its worst case was one day of the membership's allowance. The owner chose **C** (2026-11-18): the allowance is shared with the household's own Waypoint and its route warming, and that risk wasn't accepted. A revisit that wants B without that risk needs a separate Apple Developer Program membership for the demo (its own allowance and Team ID, a yearly fee), and a new owner decision.

## Privacy statement

**Under C (adopted):** the demo holds only made-up data: invented people, bookings, emails and places, from the synthetic seed (`frontend/demo/data.json`, see `demo/README.md`). With no maps, Apple sees nothing from the demo: no script, tile or directions request is made, and no token is in the page.

**What B would have meant (not adopted):** a demo visitor's browser loads Apple's MapKit JS from `cdn.apple-mapkit.com` and asks Apple for tiles and, during a replay, directions between the made-up stops. Apple learns the visitor's IP address and browser, that the page's origin was `anthonypluth.github.io`, the token (which names the owner's Team ID), and the made-up trips' map areas and drive ends. Apple's unpinned script runs in the demo page, which has no session, no account, no API and no real data for it to reach. The demo doesn't preload MapKit: it loads when a page with a map is opened (today's rule, "the offline copy and the static demo don't preload"). 

## Docs screenshots

They keep the stand-in (decided, and built in #836). `make verify` must stay deterministic (`libfaketime`, a frozen clock, images that change only when the UI does) and offline (`NO_OUTSIDE`, the browser's outside requests answered or aborted). Real tiles would change whenever Apple's maps change, would need the token on every contributor's machine and in CI's pull request jobs (where it must never be), and Apple's terms may not allow committing tile images (not checked). The docs show the app's layout. The live demo shows Apple's maps.

## Checks that keep values out (for a revisit)

Under C nothing secret exists for the demo, so no new check is needed: the demo's page policy and `demo/verify.mjs` already fail on any outside request, and Trivy's secret scan in `security.yml` runs over the files. If B is ever revisited, these were the proposed checks:

- A check in `tools/app_checks.py` (run by `make fleet-checks`) that fails on a tracked file holding a PEM private-key block or a JWT-shaped string (`eyJ….eyJ….…`). The one existing made-up `BEGIN PRIVATE KEY` block in `tests/test_app_push.py` is named in an allow list with its reason. Trivy's secret scan in `security.yml` already runs over the files. Whether its built-in rules catch a MapKit JWT isn't confirmed.
- `demo/verify.mjs`: a build without `DEMO_MAPKIT_JS_TOKEN` must not contain the token stub, Apple's hosts in the policy or a MapKit start. A build with a made-up token (the test uses `eyJmYWtl…`-style made-up text, never a real one) must contain it in the one expected file only, and the run still never reaches Apple.
- The workflow never prints the variable. GitHub masks it, but not a value changed on the way (base64, split), so the build passes it unchanged and only Vite reads it.
- `make verify` and `tools/control` never read `DEMO_MAPKIT_JS_TOKEN`: a test in `tests/test_verify.py` (or the existing verify tests) that runs `mapkit_env` with the variable set and checks it isn't passed through.

## Build issues

None needed. Option B's two drafts (a fleet docs-workflow change and the Waypoint demo wiring) are not created: C has no token to wire, and #836 builds the demo's no-maps behaviour.

## Owner's answers (2026-11-18)

Recorded in [the comment on #834](https://github.com/AnthonyPluth/Waypoint/issues/834#issuecomment-6982585262).

1. **Option:** C, no maps in the static demo.
2. **The shared allowance:** not accepted. That is why C was chosen.
3. **Required reviewers on an environment:** moot, since no environment is created.
4. **The cards:** the kinds tile, with no snapshot token.
5. **The domain:** moot under C. Kept as a note for a revisit: a token restricted to `anthonypluth.github.io` would also work on every other Pages site under the account.
6. **The model for a build issue:** moot, since there is no build issue.
7. **Lifetime:** moot.
8. **Visitor opt-in:** moot, since nothing is sent to Apple.
