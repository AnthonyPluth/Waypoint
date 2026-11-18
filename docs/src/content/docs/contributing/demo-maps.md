---
title: Apple’s maps in the demo
description: The proposed way to give the public static demo Apple’s MapKit maps with a demo-only token, where each secret lives, and how to rotate or revoke it.
sidebar:
  order: 3
---

**Status: proposed, not built, not signed off.** This page is the procedure proposed on [#834](https://github.com/AnthonyPluth/Waypoint/issues/834). The owner has to sign off the recommendation before anything is built, and until then the static demo shows no maps and the docs screenshots show the grid stand-in, as the [MapKit-only design](https://github.com/AnthonyPluth/Waypoint/blob/main/docs/design/mapkit-only/README.md) says. The options, the abuse model and the open questions are in [`docs/design/demo-maps/README.md`](https://github.com/AnthonyPluth/Waypoint/blob/main/docs/design/demo-maps/README.md).

No key, token or other private value goes into the repository, a pull request, an issue, an image or a log. That includes this page: the values below are placeholders.

## What the demo gets

The [static demo](https://anthonypluth.github.io/Waypoint/demo/) is files on GitHub Pages, with no server. MapKit JS needs a token to start, and a static page can’t hold a private key, because anyone can read every file it ships. So the demo never gets a private key. It gets one **MapKit JS token** that you make in Apple’s developer account, with these limits:

- **Type MapKit JS only.** It can start MapKit JS in a browser. It can’t call the Maps Server API (`maps-api.apple.com`), and it can’t sign anything.
- **Restricted to one domain**, `anthonypluth.github.io`. Apple’s domain restriction has no path, so the token also works on any other GitHub Pages site under that account. Only the account’s owner can publish there.
- **A fixed end date**, never “No Expiration”, so a copied token stops working by itself.
- **Separate from the household’s key.** Revoking it changes nothing for anyone’s own Waypoint, and the household’s key never goes near the demo.

The token is public once the demo is published: anyone can open the page and copy it. That is how Apple’s static tokens are meant to be used. The protections are the type, the domain, the end date and revocation, not secrecy. Keeping it out of the repository still matters: a pull request build never gets it, a rotation needs no commit, and it never ends up in git history.

## Make the token

You need the Account Holder or an Admin role in the Apple Developer Program membership that the household’s MapKit key belongs to. The steps follow Apple’s [Creating a Maps token](https://developer.apple.com/documentation/mapkitjs/creating-a-maps-token).

1. Sign in at [developer.apple.com/account](https://developer.apple.com/account) and open Certificates, Identifiers & Profiles, then **Services**.
2. Under **Maps**, click **Configure**, then **Tokens** at the top of the Usage Dashboard, then **+**.
3. Token Type: **MapKit JS**. Don’t choose Server API, Embed API or Web Snapshots for this token.
4. Restriction Type: **Domain**. Websites: `anthonypluth.github.io`, and nothing else. Don’t use a wildcard.
5. Domain Token Validation Duration: **180 Days**. That is the longest fixed term Apple lists. “Other” takes a date of your choosing, and Apple doesn’t say how far out it can be. Never choose **No Expiration**.
6. Token Description: `Waypoint public demo (GitHub Pages)`.
7. Click **Create**, then copy the token with the copy icon. Paste it straight into the GitHub secret in the next section. Don’t save it in a file, a note, a chat or an issue.
8. Write down the end date Apple shows for the token. It goes in a variable, not a secret.

You don’t need a Maps ID or a private key for this token. You only need those if the owner picks one of the other options in the design (a token endpoint, or signing at build time). In that case, make a Maps ID just for the demo (for example `maps.io.github.anthonypluth.waypoint-demo`) and a key for it with only **MapKit JS** checked, as Apple’s [Creating a Maps identifier and a private key](https://developer.apple.com/documentation/applemapsserverapi/creating-a-maps-identifier-and-a-private-key) describes. Apple lets you download the `.p8` only once. Sign its tokens with `scope` `mapkit_js` and `origin` `anthonypluth.github.io`, never `server_api`. Never reuse the household’s key.

## Where each value lives

All the values live in one GitHub environment, set up the way the `testflight` environment is in [ios/README.md](https://github.com/AnthonyPluth/Waypoint/blob/main/ios/README.md#testflight):

1. In the repository’s Settings, **Environments**, create an environment named `demo-maps`.
2. Under **Deployment branches and tags**, choose **Selected branches and tags** and add `main` only.
3. Add **Required reviewers** (the owner). See the open question on this in the design: every Docs deployment from `main` would then wait for approval.
4. Add the secret and the variable:

| Name | Kind | Holds | Who can read it |
| --- | --- | --- | --- |
| `DEMO_MAPKIT_JS_TOKEN` | environment secret | the MapKit JS token from the last section | only a job that names `environment: demo-maps`, runs on `main` and, with required reviewers, has been approved. Nobody can read it back in GitHub’s settings, admins included; they can only replace or delete it. GitHub masks its value in the job’s log. |
| `DEMO_MAPKIT_TOKEN_EXPIRES` | environment variable | the token’s end date, `YYYY-MM-DD` | anyone who can see the repository’s settings. It is not secret. |

The repository holds no `.env.example` entry, test fixture or default for either name. A repository-level secret would be wrong: in this repository agents push branches, and a repository secret is readable by a workflow running on any branch, while an environment restricted to `main` is not.

Nothing else is stored anywhere. No private key exists for the demo under this plan.

## How the token reaches the page

This is the wiring the build issue proposes (draft in the design). None of it exists yet.

- Only the Docs workflow’s build on `main` runs in the `demo-maps` environment. It passes `DEMO_MAPKIT_JS_TOKEN` to `npm run build:demo` as an environment variable. It never echoes the value or writes it to a file in the workspace other than the built bundle.
- The demo build puts the token in the bundle’s stand-in for `GET /api/mapkit/token` and reports MapKit as configured in its `/api/state` reply. It widens the demo page’s Content-Security-Policy for Apple’s hosts only in a build that has a token.
- A build without the token (every pull request, a fork, a local `npm run build:demo`) is exactly today’s demo with no maps.
- `demo/verify.mjs` still answers every request to Apple’s hosts with the stand-in and still fails on any request that leaves the page. CI never sends the token to Apple.
- The only place the token exists outside GitHub’s secret store is the published demo and its Pages artifact, which hold the same files.

## Rotate it

Rotate before the end date (the reminder in the build issue opens an issue three weeks ahead), or whenever you like:

1. Make a new token as above.
2. Replace `DEMO_MAPKIT_JS_TOKEN` in the `demo-maps` environment with it, and set `DEMO_MAPKIT_TOKEN_EXPIRES` to its end date.
3. Run the **Docs** workflow on `main` (Actions, Docs, Run workflow), and approve it if the environment asks.
4. Open the published demo and check that a trip’s replay and the Stats map draw Apple’s map.
5. Revoke the old token in Apple’s Tokens list.

Overlapping the two tokens means the demo never goes dark. If a token runs out before you rotate it, the demo’s maps fail the way they do in the app without a key: the map is hidden and a replay says “The map couldn’t load”. Nothing else in the demo changes.

## Revoke it

Revoke at once if the token is used where it shouldn’t be (the Usage Dashboard shows the account’s use), if the household’s maps start failing for quota reasons, or if the token was ever pasted anywhere but the GitHub secret.

1. In Apple’s Tokens list, click the token and **Revoke**. Apple says it then stops working with MapKit JS. Apple doesn’t say how fast that reaches every browser.
2. Delete `DEMO_MAPKIT_JS_TOKEN` from the `demo-maps` environment, or replace it with a new token.
3. Run the Docs workflow on `main`. Without a secret it publishes the demo with no maps. With a new one it publishes the maps again.

If a token value ever lands in a commit, a pull request, an issue or a log, revoke it first and clean up afterwards. Removing it from git history doesn’t make it unknown.

## Apple’s allowance and what abuse costs

Apple’s [MapKit JS page](https://developer.apple.com/maps/mapkitjs/) gives a free daily allowance of **250,000 map views and 25,000 service calls per Apple Developer Program membership**. Its [pricing page](https://developer.apple.com/maps/mapkitjs/pricing) adds 25,000 unique Web Snapshot requests a day. The allowance belongs to the **membership, not the token**. The demo’s token, the household’s own Waypoint and the nightly route-warming job all draw on the same allowance. Apple’s WWDC22 session on the Maps Server API says that past the service-call limit Apple answers HTTP 429. We found no Apple statement that overage is billed, and the limits page says to contact Apple for more.

So the worst case from someone copying the demo’s token is that they spend the membership’s allowance for that day. The household’s replay maps then fail for the rest of the day, and that night’s route warming stops early (it treats an error from Apple as a reason to stop until the next night). It is not a bill. The token can’t reach the Maps Server API, sign anything or read anything of the household’s. The design weighs this and the ways to cap it.

## Docs screenshots stay offline

`make verify` and `tools/control` keep using a throwaway key made for the run and the stand-in for Apple’s script (`frontend/verify/fake-mapkit.js`, which draws a plain grid). They never read `DEMO_MAPKIT_JS_TOKEN` and never reach Apple. So the images in `docs/src/assets/screenshots/` stay the same from run to run, can be made without a network, and can never show a real tile or carry a token. Real Apple tiles in committed images would also change whenever Apple’s maps did, and Apple’s terms may not allow it.

## Privacy

The demo holds only made-up data: invented people, bookings, emails and places (`frontend/demo/data.json`, see [demo/README.md](https://github.com/AnthonyPluth/Waypoint/blob/main/demo/README.md)). With the maps on, a demo visitor’s browser loads Apple’s MapKit JS from Apple and asks Apple for tiles and, during a replay, directions. Apple learns the visitor’s IP address and browser, that the page was on `anthonypluth.github.io`, and the made-up trips’ areas and drive ends. No visitor data, account or real trip is in the page for Apple’s script to reach. The demo doesn’t preload MapKit: it loads only when a page with a map is opened.
