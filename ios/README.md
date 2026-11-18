# Waypoint for iPhone

A native shell around the Waypoint web app. The person types the address of their own Waypoint; the app signs in to it with the system sign-in sheet and shows the web app in a Capacitor web view. Setup and sign-in are described in the [iPhone app page](https://anthonypluth.github.io/Waypoint/start/ios/).

**Status: built and unit-tested in CI, not run on a device or against a real server as far as this repo shows (in particular, an airplane-mode launch showing the cached page is not confirmed on a device; a cold launch with no connection opening the cached page is covered by `WebLaunchTests` but not run on a device).** The iOS workflow (`.github/workflows/ios.yml`) builds the app and runs its unit tests on every change to `ios/`. The "iOS TestFlight" workflow signs it and ships it to TestFlight (see below); the bundle id and team in `Config.xcconfig` stay placeholders, because that workflow passes the real ones from its environment. The server side it talks to is tested (`tests/test_app_sign_in.py`).

## Build

Needs a Mac with Xcode 26+ (Apple only accepts uploads built with the iOS 26 SDK), Node 22+ and [XcodeGen](https://github.com/yonaskolb/XcodeGen).

```sh
cd ios
npm ci            # Capacitor 8.6.0
xcodegen          # writes Waypoint.xcodeproj from project.yml (not committed)
open Waypoint.xcodeproj
```

Set `WAYPOINT_BUNDLE_ID` and `DEVELOPMENT_TEAM` in `Config.xcconfig` (placeholders: `com.anthonypluth.waypoint`, empty). The bundle identifier must match the one registered in the Apple developer account.

## App icon

The icon is one 1024x1024 PNG with no transparency (`AppIcon` in `Waypoint/Assets.xcassets`, the single-size format; iOS rounds the corners). It is the Waypoint logo (`waypoint/static/logo.svg`) on its dark tile, full bleed. The PNG is committed once as `waypoint/static/ios-icon-1024.png`, one of the places `fleet checks` allows raster images (`image-homes` in `pyproject.toml`; its vector source is `waypoint/static/ios-icon.svg`); `xcodegen` copies it into the asset catalog (`preGenCommand` in `project.yml`, the copy is not committed), and `ASSETCATALOG_COMPILER_APPICON_NAME` / `CFBundleIconName` name it. App Store Connect refuses a build without it.

## TestFlight

The "iOS TestFlight" workflow (`.github/workflows/ios-testflight.yml`) archives a signed release, exports an `.ipa` and uploads it to TestFlight. Both iOS workflows run on `macos-26` and fail early if Xcode is older than 26. It starts for a push to `main` that changes `ios/`, `waypoint/static/ios-icon-1024.png` or the workflow itself, except Markdown files under `ios/` (a README-only change does not build or upload; these are the paths the "iOS" workflow watches, plus its own file), or by hand (Actions, "iOS TestFlight", Run workflow, on `main`); never for a pull request. The icon's SVG (`waypoint/static/ios-icon.svg`) is only the source of the PNG, not a build input: changing it alone does not upload, so regenerate the PNG. A change to the web app alone does not start it: the app loads the person's own server (`webDir` holds only a stub page), so no web files are bundled. Every run, automatic or by hand, waits in the `testflight` environment for a required reviewer to click Approve before it can read the signing secrets; nothing uploads until then. Runs share one concurrency group and never cancel a running one, so two uploads never overlap (the group is per branch ref, so a run started from another branch cannot displace main's). GitHub holds at most one running and one pending run per group, so while a run waits for approval a newer one queues behind it, and a third replaces that queued one; the newer run shows Pending with no Approve button until the older one finishes. If a newer push has queued behind a waiting run, cancel the older waiting run on the Actions page (Cancel workflow; it shows grey, not as a rejected deployment), then approve the newest once it asks. The version people see in TestFlight (`CFBundleShortVersionString`, `MARKETING_VERSION`) is the latest GitHub Release's version without the leading `v`, read when the run starts building, after the approval (a release cut while the run waited counts: normally this commit's release, but approving before docker.yml has cut it gives the previous release, one patch behind, and the build number still rises), and passed to `xcodebuild archive` like the build number; nothing is committed back. TestFlight shows for example `3.49.0 (87)`. The job stops with an error, and never uses the `0.1.0` in `Config.xcconfig`, when the latest release cannot be read or its tag is not `vX.Y.Z` (Apple needs three dot-separated integers, and a version not lower than one already uploaded). `tests/test_ios_testflight_version.py` runs that step against a fake `gh`. The build number is the run number (`CURRENT_PROJECT_VERSION`), unique and increasing across both triggers; a re-run of the same run keeps its number, and App Store Connect refuses a second upload with a number it already has, so after a failed run that got as far as uploading, push or start a new run instead; `MARKETING_VERSION` in `Config.xcconfig` (0.1.0) is only what local and unsigned builds show. It uploads with `xcrun altool --upload-app` and an App Store Connect API key: altool is still Apple's supported command-line upload for an `.ipa` (its notarization mode is gone, and `notarytool` is for macOS apps only). Until the secrets below exist, the workflow stops at its first step and says which are missing.

One-time setup:

1. Join the Apple Developer Program and note the Team ID (Membership details).
2. Register the bundle identifier (Certificates, Identifiers & Profiles, Identifiers) and create the app in App Store Connect with it.
3. Create an Apple Distribution certificate, export it with its private key from Keychain Access as a `.p12` and choose a password.
4. Create an App Store provisioning profile for the bundle identifier and that certificate; download it.
5. In App Store Connect (Users and Access, Integrations), create an API key with the App Manager role and download the `.p8` (Apple gives it once). Note the key ID and issuer ID.
6. In the repository's Settings, Environments, create an environment named `testflight`. Restrict it to the `main` branch and add required reviewers so a run waits for approval.
7. In that environment add these secrets (values are base64 of the file, for example `base64 -i file | pbcopy`):

   | Secret | Holds |
   | --- | --- |
   | `IOS_DIST_CERT_P12_BASE64` | the distribution certificate `.p12`, base64 |
   | `IOS_DIST_CERT_PASSWORD` | the `.p12` password |
   | `IOS_PROVISIONING_PROFILE_BASE64` | the `.mobileprovision`, base64 |
   | `APP_STORE_CONNECT_KEY_ID` | the API key ID |
   | `APP_STORE_CONNECT_ISSUER_ID` | the API issuer ID |
   | `APP_STORE_CONNECT_KEY_P8_BASE64` | the API key `.p8`, base64 |

8. In the same environment add these variables: `DEVELOPMENT_TEAM` (the Team ID) and `WAYPOINT_BUNDLE_ID` (the bundle identifier from step 2). The workflow passes them to the build, so `Config.xcconfig` keeps its placeholders.

**First run:** the signing and upload path ran by hand for the first time on 2026-11-16, after #720, and succeeded. The automatic trigger has not run yet.

## What is here

| File | Does |
| --- | --- |
| `WaypointApp.swift` | Entry point: connect screen, or the web view if already connected. |
| `ConnectView.swift` | Asks for the server address and signs in. Plain system form; a designed screen needs the owner's sign-off. |
| `ServerClient.swift` | Talks to the server: address check, OAuth metadata, token exchange and refresh, revoke, web session. |
| `SignIn.swift` | `ASWebAuthenticationSession` with PKCE (S256), `state` and `iss` checks, redirect `waypoint://auth`. |
| `ServerSession.swift` | Keeps the server and tokens in the Keychain, decides how the web view opens at launch (`launchWebView`: the server, the cached page, signed out or an error), refreshes tokens one at a time (refresh tokens rotate; reuse revokes the grant), hands the web view its session cookie. |
| `UnauthorizedReport.swift` | Script injected into the web view that reports a same-origin `/api/` answer of 401 to the shell, and the checks on that report. |
| `SignedOutView.swift` | The screen shown after sign-out; its button goes back to the connect screen. |
| `ShellViewController.swift` | `CAPBridgeViewController` that loads the person's server instead of bundled files. The web view runs under the status bar and home indicator (`ignoresSafeArea()`, and `ios.contentInset` is `never` in `capacitor.config.json`); the web app pads itself once with `env(safe-area-inset-*)`. It also registers the offline bridge handler and the cached-page scheme handler, and watches the web view's own navigation delegate (it wraps Capacitor's) to show the cached page when the server cannot be reached (see "Cached page"). |
| `OfflineStore.swift` | The protected store for saved trips: the `GET /api/offline` reply as files in Application Support, one folder per server address, `.complete` file protection, no encryption of its own. Each save replaces the whole set (staged, then swapped in); a trip is dropped 3 days after its end date, checked on load; purge for one server or all. `OfflineSync` is what calls it. |
| `OfflineSync.swift` | Fills and clears the store (offline epic #734, issue 3). When saving is on (`OfflineSettings`, a per-phone `UserDefaults` flag named `offlineSaving`, missing means on, so a new install saves from its first online open after sign-in; the Offline access card in Settings switches it, and `ServerSession.signOut()` removes it so saving is on again after the next sign-in) it fetches `GET /api/offline` with the app's token after the web view is ready and each time the app becomes active, saves the reply only when `version` is 1, and keeps the old copy on a network error, a server error or an unknown version. A 401 or 403, a sign-in that ended, saving turned off, Remove (the web app sends it when it is told 401 or 403; the card has no button), a changed server address, `ServerSession.signOut()` and launching with no server purge it. A purge during a fetch stops that fetch's save. `refreshPages(loaded:)` keeps the server's public build files (see "Cached page") and every purge deletes them with the saved trips. It also holds `OfflineSyncState` (whether a fetch is running and whether the last save failed), which the bridge reports in `status`. No trip contents are logged. |
| `OfflinePages.swift` | The cache of the server's public build files for the cached page: one folder per server address in Application Support, `.complete` file protection, replaced as a whole (staged, then swapped in), tagged with the build (the hash of the app shell). Also the list of what is kept (the same files `sw.js` keeps) and the content types. |
| `OfflineBridge.swift` | The Swift side of the offline bridge: the four requests answered from `OfflineStore` and `OfflineSync`, the origin check, and the `waypointOffline` message handler. |
| `OfflinePageHandler.swift` | The cached page: the gate (saved trips and a saved page), the rule for when the server counts as unreachable, the `waypoint-offline` scheme handler that serves the saved files, the wrapper around Capacitor's navigation delegate, and the check that brings the web view back to the server. |
| `SavedTripsReader.swift` | A `Decodable` read model of the saved copy for Siri and Shortcuts, read through `SavedTrips.read` like the bridge. It decodes only the trip's `id`, `name`, dates, `destination` and `cities`, and each booking's `id`, `kind`, `status`, times and zones, `origin`, `destination`, `provider`, `details.flight_number`, `details.address` and `details.time_unknown`. It never decodes `confirmation`, `manage_url`, `travelers`, any other `details` key or `messages`. |
| `TripAnswers.swift` | Pure functions from that model, the clock and the phone's time zone to an `Answer` (spoken text, card fields, page to open): the next flight, tonight's stay and the check-out, plus the fixed answers (locked, not signed in, saving off, nothing saved, unreadable, nothing found). No network, no Keychain. |
| `WaypointIntents.swift` | `NextFlightIntent`, `TonightStayIntent` and `CheckOutIntent` (each `.requiresAuthentication`), `WaypointShortcuts` with their phrases, and `TripAnswerService`, which checks the phone is unlocked, a session exists and saving is on before it reads the saved trips. |
| `TripAnswerCard.swift` | The SwiftUI card shown under the spoken answer, as the frames in `docs/design/siri-shortcuts/` show it. |
| `TripEntity.swift` | Intent D's pieces: `TripEntity` (a saved trip as Siri knows it: id, place and dates only), `TripEntityQuery` (answers only from the saved copy, so empty after a purge) and `TripPlaces` (the pure rules for place, dates, matching and what "open my trip" says). |
| `PendingPage.swift` | The page a tapped card opens (`#trip/{id}` or `#trip/{id}/flight/{segmentId}`), held in memory for two minutes and used once. |
| `Keychain.swift`, `PKCE.swift` | Helpers. |
| `Tests/WaypointTests.swift` | PKCE (RFC 7636 vector), address normalising, sign-in reply checks. |
| `Tests/OfflineStoreTests.swift` | Save and load, replace not merge, per-server separation, expiry, purge, file protection. |
| `Tests/OfflineSyncTests.swift` | Sync with a fake network: saves, unknown version keeps the copy, 401 and 403 purge, network error keeps, sign-out and a changed server purge. |
| `Tests/OfflinePagesTests.swift` | The page cache: save and read, replace not merge, per-server separation, purge, file protection, which paths are fetched. |
| `Tests/OfflinePageSyncTests.swift` | Refreshing the cache with a fake network: what is fetched (never a token), same build skipped, new build replaces, a failed or redirected file keeps the old copy, purge with the trips. |
| `Tests/OfflineBridgeTests.swift` | The four bridge requests, the reply shapes, unknown requests refused, which origins are answered. |
| `Tests/WebLaunchTests.swift` | The launch with a fake `ServerAPI`: no connection with and without saved trips, a slow request, 401 and 403 signing out and purging, errors that aren't a lost connection, and renewing the web session on the way back to the server. |
| `Tests/OfflineShellTests.swift` | The gate, when the cached page is shown, the scheme handler, the bridge from a real web view, and the shell with a remote server address that cannot be reached. |
| `Tests/TripAnswersTests.swift` | The Siri and Shortcuts answers: the read model, the next flight, tonight's stay and the check-out rules (8 am and 11:01 am on check-out morning), the zones, a copy saved before `cities`, the fixed answers, canary values that must never be spoken or shown, no network request, `.requiresAuthentication`, and the page a card opens. |

## Offline bridge

How the web app reads saved trips from the shell (offline epic #734; the web side is `frontend/src/lib/offline-shell.ts`, the Swift side is issue #739). This is the one place the contract is written down.

**Marker.** The shell registers one `WKScriptMessageHandlerWithReply` named `waypointOffline` on the web view's user content controller (the same way `waypointUnauthorized` is added in `ShellViewController.webView(with:configuration:)`), for the main frame only. The web app is "in the shell" exactly when `window.webkit.messageHandlers.waypointOffline.postMessage` is a function; with no handler it behaves as in a browser (passkey vault, service worker) and never calls the bridge. Register the handler only for the person's own server origin and the cached page (below).

**Calls.** The page calls `window.webkit.messageHandlers.waypointOffline.postMessage(request)` and awaits the promise WebKit returns; the reply handler answers with a JSON object. A request is an object with a `type`:

| Request | Does | Reply |
| --- | --- | --- |
| `{ "type": "status" }` | Reads the saving flag and what is saved. | Status. |
| `{ "type": "load" }` | Reads the saved trips from `OfflineStore` (expired trips already dropped). | Load. |
| `{ "type": "setSaving", "on": true \| false }` | Sets the `offlineSaving` flag. Turning it off purges the saved copy and is how the settings card deletes it. Turning it on lets sync fill the store at the next opportunity. | Status after the change. |
| `{ "type": "remove" }` | Purges the saved copy for the current server. Leaves the saving flag alone. The settings card does not offer it (switching saving off is the only way to delete); the web app sends it when it is told 401 or 403. | Status after the purge. |

**Status reply:** `{ "version": 1, "saving": Bool, "syncing": Bool, "lastSaveFailed": Bool, "savedAt": Number | null, "trips": [{ "id": Number, "name": String }] }`. `saving` is the setting, which is on for a new install. `syncing` is true while a fetch of `GET /api/offline` is running (the settings card shows "Saving your trips…" and the web app asks again until it is false). `lastSaveFailed` is true after a failed fetch or save that kept the older copy (a network or server error, or a `version` the app does not know) and false after the next success, after a purge and when saving is switched off. The two flags are optional for the web app, and missing means false, so `version` stays 1. `savedAt` is milliseconds since the epoch of the last save (`null` when nothing is saved); `trips` lists the saved trips' ids and names in the order the server sent them (empty when nothing is saved).

**Load reply:** `{ "version": 1, "trips": [Trip] }`, each `Trip` being one element of the `GET /api/offline` reply's `trips` (`{ "trip": ..., "messages": [...], "cities": { "DEN": "Denver", ... }, "codes": [...] }`, exactly as saved; `cities` maps the airport codes of the trip's flights to their cities, and a copy saved before it existed has none; `codes` is the optional list `{ "segment_id", "type", "data" }` of the QR pictures of the parking bookings the person can see, which the app keeps with the saved trips under the same file protection by the owner's decision on #819 of 2026-11-18, and `load` passes it through unchanged, as it does each segment's `gate_code`) plus `"savedAt"`, the same milliseconds since the epoch. Nothing else is added or changed, and the shell never decrypts anything (there is no app-level encryption; see the epic's owner decisions).

**Errors and versions.** A reply with a `version` other than 1, or one that does not match the shapes above, is treated by the web app as an unreadable copy: it shows the offline screen's "can't be opened" state and never invents trips. Reject a request the handler does not know by failing the promise (reply with an error). The web app does not retry on its own. `version` is the same 1 as in `GET /api/offline`; change it only together with the web app.

**Where the copy is kept.** In the app's own private storage inside its sandbox (Application Support, one folder per server address), as files with `.complete` file protection (iOS Data Protection): readable only while the phone is unlocked, and not readable by other apps or websites. The app adds no encryption of its own, so `ITSAppUsesNonExemptEncryption` stays `false`, and opening saved trips needs no Face ID. The files are not excluded from backups, so they can be part of the iCloud and computer backups (the card says so). They are deleted on sign-out, on a 401 or 403 from the native fetch, when saving is switched off, when the server address changes and 3 days after each trip ends.

**Privacy.** The handler answers only the main frame of the person's own server or of the cached page, only while a session exists for that server, and never logs trip contents. The web app calls `status` when the offline screen or Settings opens, `load` only when the server cannot be reached, and `remove` when the web app is told 401 or 403 (the shell purges on those itself too).

## Cached page

Offline epic #734, issue #739. WKWebView has no service worker here, so native code keeps a copy of the server's own public build files and serves it when the server cannot be reached.

**What is kept.** While saving is on (`OfflineSettings`), after each successful load of the server's page the shell reads the paths the page loaded (`performance.getEntriesByType("resource")`, same-origin `/assets/*` only, as `shell-cache.ts` does for `sw.js`) and `OfflineSync.refreshPages(loaded:)` fetches the app shell `/`, those assets and the shell files `sw.js` lists (`OfflinePageFiles.shell`; `tests/test_ios_shell_cache.py` fails if the two lists drift). The fetch carries no token and no cookies and accepts only a plain 200 from the same origin (a redirect, for example to a sign-in page, is refused). The files are code only. The build is the SHA-256 of the app shell: with the same build only missing assets are added, with a new build the whole set is replaced at once, so a cached page always matches the server it came from. A failed fetch keeps the old copy. The copy lives in `Application Support/OfflinePages/<server>/` with `.complete` file protection and is deleted in the same places as the saved trips (sign-out, 401 or 403, saving off, Remove, a changed server address, no server, and when no trip is left).

**When it is shown.** Capacitor loads the server as before. `OfflineNavigation` wraps Capacitor's navigation delegate; when the main-frame load of the server fails with "not connected", "cannot connect", "cannot find host", DNS failure, timeout, connection lost, roaming off or data off (`OfflineFallback`), and saved trips exist for that server and a saved page exists (`OfflineGate`), the web view loads `waypoint-offline://waypoint.offline/`. Nothing else triggers it (not a certificate error, not a cancelled load, not an HTTP error), and with no saved trips nothing is served at all (the scheme handler asks the same gate for every file), so a signed-out person sees nothing: sign-out deletes the copy. The page boots as on the server, its `/api/` requests fail as a dead network would (so the web app shows its offline screen) and it reads the trips over the bridge. Those requests also check, at most every 5 seconds, whether the server answers again, and if so the shell first renews the web session when it needs it (`ServerSession.renewForReturn`, which can end in a sign-out like any renewal) and then loads the server (this covers "Try again" and the page's own once-a-minute check).

**Cold launch with no connection.** `WaypointApp.open()` asks `ServerSession.launchWebView(gate:patience:)`, which runs `prepareWebView()` (token renewal if needed, then `POST /auth/app-session`). A lost connection there is `ServerError.offline` (`ServerClient.failure(for:)` uses the same list of URL errors as `OfflineFallback`); any other failure stays `notReachable` or `notWaypoint`. Because `ServerClient.session` waits for connectivity, a request with no network would hang for up to 45 seconds, so when the gate already holds saved trips and a page the launch waits 5 seconds (`patience`) and then gives up on the request. With the gate open, a lost connection or that timeout returns `.cachedPage`: `WaypointApp` sets `ShellViewController.serverURL` and shows the shell with no cookie installed, so Capacitor's load of the server fails and the navigation wrapper shows the cached page as above (a token is never given to it; the bridge answers its `waypoint-offline://waypoint.offline/` main frame as before). With the gate shut (no saved trips, no saved page, another server) the error screen shows as it always did. A 401 or 403 from the cookie request or a refused renewal (`invalid_grant`) is `.signedOut`: the session signs out and purges the saved trips. `ServerSession` takes its network calls through the `ServerAPI` protocol so `WebLaunchTests` can use a fake. Not confirmed on a device: an airplane-mode launch showing the cached page, and how long the web view takes to give up on the server there.


**Why a scheme handler and not `setServerBasePath`.** In Capacitor 8.6.0 `CAPBridgeViewController.setServerBasePath` only changes the directory the `capacitor://` asset handler serves and then reloads `config.serverURL`, which is the remote server when `server.url` is set, so the page still comes from the network and nothing is served from the cache. A `WKURLSchemeHandler` for its own scheme works with a remote server address because it does not depend on that configuration; `OfflineShellTests` loads the shell with a remote address nothing listens on and checks that the cached page appears.

## How sign-in works

1. `GET <server>/api/trips` with no credentials. `200` means the server has no sign-in of its own: the app just opens it.
2. Otherwise read `/.well-known/oauth-authorization-server` (needs `WAYPOINT_PUBLIC_URL` on the server) and open `/oauth/authorize` for the built-in client `wpc_waypoint_ios`, scope `app`, resource `<issuer>/app`, in the system sheet. The sheet is ephemeral (`prefersEphemeralWebBrowserSession`): iOS shows no "wants to use <server> to Sign In" prompt, but the sheet does not share Safari's cookies, so the person signs in to their provider each time they sign in, then taps Allow.
3. The sheet returns `waypoint://auth?code=…`; the app swaps the code for tokens (`wpa_` access, `wpr_` refresh), stored in the Keychain.
4. While the web app is showing, a `401` from its own `/api/` ends the session: the shell signs out (revoking the refresh token) and shows "You are signed out of Waypoint." with a **Sign in** button back to the connect screen. It does not try to renew, so there is no renewal loop.
5. Each launch, `POST /auth/app-session` with the access token gives the web view its normal session cookie. With no connection and a saved copy, the launch skips this and opens the cached page (see "Cached page").

## Siri and Shortcuts

Intents A and B of [#820](https://github.com/AnthonyPluth/Waypoint/issues/820) (design: `docs/design/siri-shortcuts/`), built in #841: "next flight", "tonight's stay" and "check-out", answered from the saved trips on the phone alone, with no network request. Each intent is `.requiresAuthentication` (Siri asks for the unlock first; the saved trips are `.complete` file protected), and `TripAnswerService` answers "Unlock your iPhone to see your trips in Waypoint." without reading if protected data is unavailable. The spoken answer never holds a confirmation code, gate, loyalty number, seat, room, phone number, street address or another traveller's name (the read model doesn't decode them); the card shows the stay's street address and how old the copy is. Nothing is given to Spotlight, donations, `NSUserActivity` or Apple Intelligence schemas. Tapping the card brings the app forward and `PendingPage` opens the booking's page.

"Open my trip to a place" (#843): `OpenTripIntent` (`.requiresAuthentication`, opens the app) opens `#trip/{id}` for a saved trip named by its destination or name, and says "Opening your trip to \<place\>."; a trip no longer saved says "There's no trip to \<place\> saved on this iPhone. Opening Waypoint." and opens Upcoming. For a phrase to name a place, the saved trips' destinations and names (never a booking) are given to the system with `updateAppShortcutParameters()`: `OfflineSync` calls it after every save and after every purge (sign-out, 401 or 403, saving off, a changed server, no server), and `TripEntityQuery` reads only the saved copy, so it is empty after a purge. Two saved trips with one place are told apart by their dates. Device checks not run: Siri hearing the phrases with a place, asking which of two trips, the list emptying after sign-out, and what Siri itself says for a place that isn't saved.

## Not built yet

- Siri and Shortcuts: parking code (#842) and live flight status (not chosen). The device checks for the next flight and stay intents (design section 4) have not been run: Siri hearing each phrase, the unlock prompt (phone in hand, AirPods, CarPlay), the card's look, the actions in Shortcuts and Spotlight and nothing else of Waypoint's, empty answers after sign-out, and a tap on the card opening the right page.
- Local reminders, and a Face ID lock on the app or the saved trips (the saved trips open with the phone's own lock only).
- Share extension (Mail, Safari, Files) and its server route.
- Push notifications and the relay.
- A sign-out button in Settings or the web UI. `ServerSession.signOut` is called by the error screen's **Use another Waypoint**, when the server says the sign-in is no longer valid and when the web view reports a 401 in the foreground; each then shows the signed-out screen.
- Servers behind a forward-auth proxy, and self-signed certificates (App Transport Security only relaxes local-network addresses).
- File picker, downloads and `webcal://` handling in the web view.
- Running the app on a simulator or device in CI (the iOS workflow builds it and runs the unit tests only).

## Export compliance (encryption)

`Waypoint/Info.plist` sets `ITSAppUsesNonExemptEncryption` to `false` (added in #541). That key answers App Store Connect's export-compliance question once, so it does not ask on every build. It says the app uses only the encryption built into the phone: HTTPS, the Keychain and the system sign-in sheet.

The web app the shell loads has an offline vault for browsers (`frontend/src/lib/offline-vault.ts`: Web Crypto AES-256-GCM, ECDH, HKDF and a passkey-derived key). The shell does not use it: in the app the web app talks to the offline bridge instead (`inShell()` in `frontend/src/lib/offline-shell.ts`), no passkey is made, and `OfflineStore` writes the saved trips as plain files under `.complete` file protection, so the app adds no encryption of its own (the SHA-256 in `OfflineStore`, `OfflinePages` and `OfflineSync` names folders and tags a build). The owner judged `false` appropriate on that basis. This is not legal advice, and it is a judgment, not a ruling.

No change is needed while the app adds no encryption of its own. Revisit the declaration if the app ever encrypts the saved trips itself or runs the browser vault: answer Apple's export-compliance questions for that build and consider the annual self-classification report.
