# Waypoint for iPhone

A native shell around the Waypoint web app. The person types the address of their own Waypoint; the app signs in to it with the system sign-in sheet and shows the web app in a Capacitor web view. Setup and sign-in are described in the [iPhone app page](https://anthonypluth.github.io/Waypoint/start/ios/).

**Status: built and unit-tested in CI, not run on a device or against a real server as far as this repo shows.** The iOS workflow (`.github/workflows/ios.yml`) builds the app and runs its unit tests on every change to `ios/`. Nothing signs the app or ships it to TestFlight yet: the bundle id and team in `Config.xcconfig` are placeholders. The server side it talks to is tested (`tests/test_app_sign_in.py`).

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

The icon is one 1024x1024 PNG with no transparency (`AppIcon` in `Waypoint/Assets.xcassets`, the single-size format; iOS rounds the corners). It is the Waypoint logo (`waypoint/static/logo.svg`) on its dark tile, full bleed. The PNG is committed once as `waypoint/static/ios-icon-1024.png`, the only place a raster image may live (its vector source is `waypoint/static/ios-icon.svg`); `xcodegen` copies it into the asset catalog (`preGenCommand` in `project.yml`, the copy is not committed), and `ASSETCATALOG_COMPILER_APPICON_NAME` / `CFBundleIconName` name it. App Store Connect refuses a build without it. The owner's sign-off on the icon is pending.

## TestFlight

The "iOS TestFlight" workflow (`.github/workflows/ios-testflight.yml`) archives a signed release, exports an `.ipa` and uploads it to TestFlight. Both iOS workflows run on `macos-26` and fail early if Xcode is older than 26. It starts only by hand (Actions, "iOS TestFlight", Run workflow, on `main`), never for a pull request. The build number is the run number (`CURRENT_PROJECT_VERSION`); the version is `MARKETING_VERSION` in `Config.xcconfig`. It uploads with `xcrun altool --upload-app` and an App Store Connect API key: altool is still Apple's supported command-line upload for an `.ipa` (its notarization mode is gone, and `notarytool` is for macOS apps only). Until the secrets below exist, the workflow stops at its first step and says which are missing.

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

**Not run yet:** the signing and upload path has never been run (no Mac or Apple account when it was written). Expect to fix the first run.

## What is here

| File | Does |
| --- | --- |
| `WaypointApp.swift` | Entry point: connect screen, or the web view if already connected. |
| `ConnectView.swift` | Asks for the server address and signs in. Plain system form; a designed screen needs the owner's sign-off. |
| `ServerClient.swift` | Talks to the server: address check, OAuth metadata, token exchange and refresh, revoke, web session. |
| `SignIn.swift` | `ASWebAuthenticationSession` with PKCE (S256), `state` and `iss` checks, redirect `waypoint://auth`. |
| `ServerSession.swift` | Keeps the server and tokens in the Keychain, refreshes tokens one at a time (refresh tokens rotate; reuse revokes the grant), hands the web view its session cookie. |
| `UnauthorizedReport.swift` | Script injected into the web view that reports a same-origin `/api/` answer of 401 to the shell, and the checks on that report. |
| `SignedOutView.swift` | The screen shown after sign-out; its button goes back to the connect screen. |
| `ShellViewController.swift` | `CAPBridgeViewController` that loads the person's server instead of bundled files. |
| `Keychain.swift`, `PKCE.swift` | Helpers. |
| `Tests/WaypointTests.swift` | PKCE (RFC 7636 vector), address normalising, sign-in reply checks. |

## How sign-in works

1. `GET <server>/api/trips` with no credentials. `200` means the server has no sign-in of its own: the app just opens it.
2. Otherwise read `/.well-known/oauth-authorization-server` (needs `WAYPOINT_PUBLIC_URL` on the server) and open `/oauth/authorize` for the built-in client `wpc_waypoint_ios`, scope `app`, resource `<issuer>/app`, in the system sheet. The person signs in through their provider and taps Allow.
3. The sheet returns `waypoint://auth?code=…`; the app swaps the code for tokens (`wpa_` access, `wpr_` refresh), stored in the Keychain.
4. While the web app is showing, a `401` from its own `/api/` ends the session: the shell signs out (revoking the refresh token) and shows "You are signed out of Waypoint." with a **Sign in** button back to the connect screen. It does not try to renew, so there is no renewal loop.
5. Each launch, `POST /auth/app-session` with the access token gives the web view its normal session cookie.

## Not built yet

- Offline encrypted store behind the web app's trip data, local reminders, Face ID lock.
- Share extension (Mail, Safari, Files) and its server route.
- Push notifications and the relay.
- A sign-out button in Settings or the web UI. `ServerSession.signOut` is called by the error screen's **Use another Waypoint**, when the server says the sign-in is no longer valid and when the web view reports a 401 in the foreground; each then shows the signed-out screen.
- Servers behind a forward-auth proxy, and self-signed certificates (App Transport Security only relaxes local-network addresses).
- File picker, downloads and `webcal://` handling in the web view.
- Running the app on a simulator or device in CI (the iOS workflow builds it and runs the unit tests only).
