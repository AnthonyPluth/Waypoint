# Apple's maps in the public demo: the options (#834)

The analysis for [#834](https://github.com/AnthonyPluth/Waypoint/issues/834). **Not signed off.** The owner signs off the recommendation on the pull request that adds this page before any build starts (the issue's second acceptance criterion). The procedure that goes with it is on the docs page [Apple's maps in the demo](../../src/content/docs/contributing/demo-maps.md).

## Where things stand

- The MapKit-only design ([`docs/design/mapkit-only/README.md`](../mapkit-only/README.md), signed off on #833) removes the bundled SVG renderer. Until #834 is settled, the static demo shows no maps and no replay, and the docs screenshots show the grid stand-in.
- The static demo is `frontend/demo/`, built by `npm run build:demo` into `frontend/demo-dist/` and checked by `demo/verify.mjs`. `make docs-site` copies it to `docs/dist/demo/`, and `.github/workflows/docs.yml` publishes it to GitHub Pages at `https://anthonypluth.github.io/Waypoint/demo/` from `main`. The workflow calls fleet's reusable docs workflow (`AnthonyPluth/fleet/.github/workflows/docs.yml`, v4.0.0). Its build job has no environment and takes no secrets. Only its deploy job runs in an environment (`github-pages`).
- The demo page's Content-Security-Policy (`frontend/demo/index.html`) is `connect-src 'none'` and `worker-src 'none'`. `demo/verify.mjs` fails on any request that leaves the page. `frontend/demo/api.ts` answers `/api/state` with no MapKit.
- The app signs a 30-minute MapKit JS token for `WAYPOINT_PUBLIC_URL`'s origin with the household's private key (`waypoint/domain/maps.py`, `waypoint/providers/mapkit.py`: `scope` `mapkit_js`, `origin`, `iss` the Team ID, `kid` the Key ID). The same key also signs the Maps Server API tokens the nightly route warming uses (`sign_server`, `scope` `server_api` on retry).
- `make verify` makes a throwaway EC key per run (`mapkit_env` in `waypoint/verify.py`), and `frontend/verify/verify.mjs` answers every request to `*.apple-mapkit.com` with `fake-mapkit.js`, a grid. Nothing in the repository holds a real key or token. `tests/test_app_push.py` has a made-up `BEGIN PRIVATE KEY` block, the only key-shaped text tracked (checked with `git grep` on `origin/main` at `076a4f1`).

## What Apple says, and what we couldn't confirm

Checked on 2026-11-18. Apple's HTML pages render only a title for a fetcher, so these are the Markdown versions of the documentation pages (the `.md` URLs) and the developer forums.

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

All of them keep the household's key out of the demo. The question is where the demo's token comes from.

### A. A small token endpoint

A function on some host (a Cloudflare Worker or similar; never the household's own Waypoint, which would then answer the public) holds a demo-only private key and signs a 30-minute MapKit JS token for `https://anthonypluth.github.io`. It checks the `Origin` header and rate-limits by IP.

- **Abuse:** the `Origin` check stops another website's pages, but not a script, which sets any `Origin` it likes, and a rate limit per IP doesn't hold against many IPs. So anyone can still get a fresh token whenever they want. The blast radius is the same as option B's: the membership's daily allowance.
- **Cost:** new infrastructure outside GitHub, a new account, a private key on an internet-facing host (a key can sign any scope, including `server_api`, for any origin and any lifetime, so leaking it is worse than leaking a token), its own monitoring, and a request that leaves the demo on every map. The demo stops being "static files only".
- **Gain:** short-lived tokens, logs of who asks, and a switch you can turn off without Apple's portal (revoking in the portal is as quick).

### B. A static, domain-restricted token made in Apple's portal (recommended)

You make a MapKit JS token in the developer account, restricted to `anthonypluth.github.io`, valid for 180 days. It is stored as a secret in a `demo-maps` GitHub environment restricted to `main`. Only main's Docs build reads it and writes it into the demo bundle. This is the [docs page](../../src/content/docs/contributing/demo-maps.md)'s procedure.

- **No private key exists for the demo.** The token can't reach the Maps Server API (type MapKit JS) and can't sign anything.
- **Abuse:** anyone can copy it from the page. Assuming the domain check can be faked, it works for anyone until it expires or is revoked. The most they can do is spend the membership's daily allowance (250,000 map views, 25,000 service calls). Then the household's own maps and the nightly route warming fail until the next day (`route_warming.run` stops a night's work on a `ServerError`, which a 429 is, and tries again the next night). As far as Apple says, it is not billed (unconfirmed, above).
- **Capped by:** the 180-day end date, revocation in the portal, the domain restriction against other websites, and Apple's own daily cap. The only full cap on the household's side is a separate membership (open question 2).
- **Expiry:** when the token runs out, MapKit fails to start, and the demo behaves as the app does without a key under the MapKit-only design: maps hidden, the replay's "The map couldn't load". The owner makes the next token. A scheduled workflow reads `DEMO_MAPKIT_TOKEN_EXPIRES` (a variable, not secret) and opens an issue 21 days before the date. Rotation is in the docs page.
- **Cost:** a fleet change, because fleet's reusable docs workflow has no way to give its build job an environment or a secret (below), plus a small demo build change.

### B2. A token signed at build time

Like B, but main's Docs build signs a JWT with a demo-only private key stored in the environment, with the longest `exp` Apple accepts, which is not documented. This is worse than B: a private key sits in CI instead of a token, and it buys nothing, since the signed token is just as public on the page. Only worth it if portal tokens turn out to be unavailable for this membership.

### C. No maps in the static demo

What the MapKit-only design does until #834 lands: no token, no risk, nothing sent to Apple. The demo shows the kinds tiles, no Stats map and no replay. The docs screenshots still show the stand-in. A visitor sees less of what Waypoint does.

### The Past trips cards

The cards use Apple's Web Snapshots in the app (#837). A pre-signed snapshot URL per card, made at build time, needs the private key in CI (B2's problem). A static Web Snapshots token can make any snapshot and spends the separate 25,000-a-day snapshot allowance. The recommendation keeps the demo's cards on the kinds tile, so there is one token of one type (open question 4).

## Recommendation

**Option B**, MapKit JS only: one static, domain-restricted MapKit JS token, valid for 180 days, made in Apple's portal and never derived from a key. Store it as `DEMO_MAPKIT_JS_TOKEN` in a `demo-maps` environment restricted to `main`. Only main's Docs build reads it. Pull request builds and local builds stay map-free. The replay and the Stats map use Apple's map in the demo. The cards keep the kinds tile. `make verify` and the docs screenshots keep the stand-in.

Why: a static page can't hide anything it uses, so every option ends with a usable token in a visitor's hands. B is the one that adds no private key and no server, uses Apple's own revocable, expiring, domain-bound token for exactly this case, and leaves a blast radius (one day's allowance, no bill as far as Apple says, nothing of the household's readable) that the end date and revocation cap. Option A costs a server and a key and caps nothing more. If the owner isn't willing to risk the household's maps failing for a day because of the shared allowance, the answer is C, or B on a separate membership.

## Privacy statement (proposed)

The demo holds only made-up data: invented people, bookings, emails and places, from the synthetic seed (`frontend/demo/data.json`, see `demo/README.md`). With maps on, a demo visitor's browser loads Apple's MapKit JS from `cdn.apple-mapkit.com` and asks Apple for tiles and, during a replay, directions between the made-up stops. Apple learns the visitor's IP address and browser, that the page's origin was `anthonypluth.github.io`, the token (which names the owner's Team ID), and the made-up trips' map areas and drive ends. Apple's unpinned script runs in the demo page, which has no session, no account, no API and no real data for it to reach. The demo doesn't preload MapKit: it loads when a page with a map is opened (today's rule, "the offline copy and the static demo don't preload"). `demo/README.md`'s "No network" section changes to say this, in the build.

## Docs screenshots

Keep the stand-in. `make verify` must stay deterministic (`libfaketime`, a frozen clock, images that change only when the UI does) and offline (`NO_OUTSIDE`, the browser's outside requests answered or aborted). Real tiles would change whenever Apple's maps change, would need the token on every contributor's machine and in CI's pull request jobs (where it must never be), and Apple's terms may not allow committing tile images (not checked). The docs show the app's layout. The live demo shows Apple's maps.

## Checks that keep values out

The issue asks for "a check or test where feasible". Proposed in the build issue:

- A check in `tools/app_checks.py` (run by `make fleet-checks`) that fails on a tracked file holding a PEM private-key block or a JWT-shaped string (`eyJ….eyJ….…`). The one existing made-up `BEGIN PRIVATE KEY` block in `tests/test_app_push.py` is named in an allow list with its reason. Trivy's secret scan in `security.yml` already runs over the files. Whether its built-in rules catch a MapKit JWT isn't confirmed.
- `demo/verify.mjs`: a build without `DEMO_MAPKIT_JS_TOKEN` must not contain the token stub, Apple's hosts in the policy or a MapKit start. A build with a made-up token (the test uses `eyJmYWtl…`-style made-up text, never a real one) must contain it in the one expected file only, and the run still never reaches Apple.
- The workflow never prints the variable. GitHub masks it, but not a value changed on the way (base64, split), so the build passes it unchanged and only Vite reads it.
- `make verify` and `tools/control` never read `DEMO_MAPKIT_JS_TOKEN`: a test in `tests/test_verify.py` (or the existing verify tests) that runs `mapkit_env` with the variable set and checks it isn't passed through.

## Draft build issues

Two issues, because one is in fleet. Waypoint's `CLAUDE.md` routes build work, the security-sensitive work included, to Sonnet. #834 itself named Opus, per an older routing. Open question 6.

### {{FLEET-DOCS-SECRET}} (in AnthonyPluth/fleet): let the reusable docs workflow's build job use an environment and one secret

**Context**
Waypoint's demo needs a MapKit JS token at build time on `main` only (Waypoint #834, `docs/design/demo-maps/README.md`). Fleet's `.github/workflows/docs.yml` (reusable) has inputs `make-target`, `npm-lockfiles`, `browser` and others. Its `build` job (`contents: read`) has no `environment` and no `secrets`. Only `deploy` runs in `github-pages`.

**Scope**
- Add an optional input `build-environment` (default empty). When it is set and the run is a push or `workflow_dispatch` on the default branch, the `build` job runs in that environment. On a pull request it never does.
- Add an optional `secrets:` entry `build-secret` and an input `build-secret-env` naming the environment variable it is passed to for the `make` step only. Never `secrets: inherit`.
- The step never echoes it. Document both inputs in the workflow's header and fleet's docs.
- zizmor clean.

**Out of scope**
Waypoint's own changes ({{WAYPOINT-DEMO-MAPS}}).

**Acceptance criteria**
- [ ] A caller without the new inputs behaves exactly as at v4.0.0 (fleet's workflow tests).
- [ ] On a pull request the build job has no environment and no secret, whatever the caller passes.
- [ ] zizmor passes on the changed workflow.

**Tests**
fleet's workflow checks and tests for `docs.yml`, zizmor.

**Depends on**
Nothing.

**Model**
Opus (fleet's `CLAUDE.md`: secrets and workflows).

### {{WAYPOINT-DEMO-MAPS}}: Apple's maps in the static demo with a demo-only token

**Context**
#834 settled, signed off on its design PR: the static demo shows Apple's maps using one static, domain-restricted MapKit JS token made in Apple's portal, stored as `DEMO_MAPKIT_JS_TOKEN` in the `demo-maps` environment (restricted to `main`), with its end date in the variable `DEMO_MAPKIT_TOKEN_EXPIRES` (`docs/src/content/docs/contributing/demo-maps.md`, `docs/design/demo-maps/README.md`). The demo is built by `npm run build:demo` (`frontend/vite.demo.config.ts`, `frontend/demo/`), checked by `demo/verify.mjs`, and published by `.github/workflows/docs.yml` through fleet's reusable workflow. Its page policy (`frontend/demo/index.html`) is `connect-src 'none'`. `frontend/demo/api.ts` answers `/api/state` with no MapKit. The app's MapKit code is `frontend/src/lib/mapkit.ts` and the MapKit-only renderer from #836.

**Scope**
- `.github/workflows/docs.yml`: pass `build-environment: demo-maps`, the secret `DEMO_MAPKIT_JS_TOKEN` and `build-secret-env: DEMO_MAPKIT_JS_TOKEN` to fleet's workflow at the release that has them; bump the pin.
- `frontend/vite.demo.config.ts` reads `DEMO_MAPKIT_JS_TOKEN` at build time. When it is set and non-empty, `frontend/demo/api.ts` answers `GET /api/mapkit/token` with it (and the script address `https://cdn.apple-mapkit.com/mk/x/mapkit.js`) and `/api/state` reports MapKit as configured. The demo's policy adds exactly what `domain/maps.py`'s `POLICY` adds, plus `https://cdn.apple-mapkit.com` in `script-src` (a static page has no nonce). When it is unset or empty, the bundle is byte for byte what it is without this change (no stub, no Apple host).
- The demo never preloads MapKit. The replay and the Stats map use Apple's map. The Past cards keep the kinds tile (no snapshot token).
- `demo/verify.mjs`: run it twice in CI on pull requests, once without and once with a made-up token value, as in the design's "Checks" section. Both runs still answer Apple's hosts with the stand-in and fail on any outside request.
- `tools/app_checks.py`: the check for tracked PEM private-key blocks and JWT-shaped strings, with the allow list for `tests/test_app_push.py`'s made-up key; register it with `tools/fleet checks`.
- A test that `make verify`'s and `tools/control`'s servers and browsers never receive `DEMO_MAPKIT_JS_TOKEN`.
- `.github/workflows/demo-maps-expiry.yml`: weekly, reads `vars.DEMO_MAPKIT_TOKEN_EXPIRES` (no environment, no secret) and opens or updates one issue titled "Demo map token expires soon" 21 days before the date (and "Demo map token has expired" after it). It does nothing when the variable is unset. Follows the workflow conventions (`fleet checks`, zizmor).
- `demo/README.md` ("No network", "GitHub Pages"), `docs/src/content/docs/contributing/demo-maps.md` (drop "proposed"), SECURITY.md and AGENTS.md's "You see the trips you're on" where they say the static demo loads nothing from Apple: the privacy statement from the design, word for word.

**Out of scope**
Making the token (the owner does it in Apple's portal), the household's key, the Maps Server API, the cards' snapshots in the demo, real tiles in `make verify` or the docs screenshots, the MapKit-only renderer itself (#836, #838).

**Acceptance criteria**
- [ ] `npm run build:demo` without the variable produces the same `frontend/demo-dist/` as `main` (a diff of the two, shown in the PR).
- [ ] `demo/verify.mjs` passes on both builds, and the made-up token appears only in the expected file of the second.
- [ ] The new check in `make fleet-checks` fails on a test file holding a made-up JWT-shaped string and passes on `main`'s tree.
- [ ] No real key, token or private value is in the diff, the PR, a log or an image. The PR uses made-up values only.
- [ ] The expiry workflow, run by hand with the variable set to a date 10 days out on a test branch's copy, opens the issue (output shown), and does nothing unset.
- [ ] After merge and the owner's first token, the published demo's replay and Stats map draw Apple's map (checked by the owner. CI can't, since it never reaches Apple).

**Tests**
`demo/verify.mjs` (both builds), `frontend/demo/api.test.ts`, the new check's tests beside `tools/app_checks.py`'s, the verify-env test, `make check`, zizmor on the changed workflows.

**Depends on**
#834's sign-off, {{FLEET-DOCS-SECRET}}, and the MapKit-only renderer (#836) and Stats map (#838).

**Model**
Sonnet (Waypoint's `CLAUDE.md`; every decision is settled here). See open question 6.

## Open questions for the owner

1. **Option B, C or A?** Is a public token that anyone can copy, capped by its end date and revocation, acceptable for the demo, given question 2?
2. **The shared allowance.** Apple counts the allowance per membership, so a copied demo token can spend the household's maps for a day (no bill, as far as Apple says). Accept that, use a separate Apple Developer Program membership for the demo (its own allowance, its own Team ID, a yearly fee), or choose C?
3. **Required reviewers on `demo-maps`?** With them, every Docs deployment from `main`, which runs on most frontend and docs merges, waits for your approval. The token is public once deployed anyway, so the branch restriction (pull request branches can't read it) does most of the work. Keep reviewers like `testflight`, or restrict to `main` without reviewers?
4. **The cards.** Leave the demo's Past cards on the kinds tile, or add a second static token of type Web Snapshots (its own 25,000-a-day allowance, the forum-only `token` parameter)?
5. **The domain.** `anthonypluth.github.io` also covers any other Pages site under the account. Keep it, or serve the demo from a custom domain of its own so the token covers only the demo?
6. **The model for the build issue.** Waypoint's `CLAUDE.md` says Sonnet for this work. #834 named Opus for secrets handling. Which?
7. **Lifetime.** 180 days with a reminder 21 days ahead, or a shorter term (30 or 90 days) at the cost of more rotations?
8. **Should a visitor opt in?** The demo would send a visitor's IP to Apple when they open a page with a map, without asking. Is that fine for a public demo, or should a map show a "Load Apple's map" button first?
