# Waypoint for iPhone

A native shell around the Waypoint web app. The person types the address of their own Waypoint; the app signs in to it with the system sign-in sheet and shows the web app in a Capacitor web view. Scope and decisions: https://claude.ai/artifact/4ipdDY5JrUtsfmrxWJ9fXG

**Status: written without Xcode or a Mac, never compiled or run.** Expect to fix compile errors on first build. The server side it talks to is tested (`tests/test_app_sign_in.py`).

## Build

Needs a Mac with Xcode 16+, Node 22+ and [XcodeGen](https://github.com/yonaskolb/XcodeGen).

```sh
cd ios
npm ci            # Capacitor 8.6.0
npx cap sync ios  # not needed for the first build; the project below takes Capacitor from the capacitor-swift-pm package
xcodegen          # writes Waypoint.xcodeproj from project.yml (not committed)
open Waypoint.xcodeproj
```

Set `WAYPOINT_BUNDLE_ID` and `DEVELOPMENT_TEAM` in `Config.xcconfig` (placeholders: `com.anthonypluth.waypoint`, empty). The bundle identifier must match the one registered in the Apple developer account.

## What is here

| File | Does |
| --- | --- |
| `WaypointApp.swift` | Entry point: connect screen, or the web view if already connected. |
| `ConnectView.swift` | Asks for the server address and signs in. Plain system form; a designed screen needs the owner's sign-off. |
| `ServerClient.swift` | Talks to the server: address check, OAuth metadata, token exchange and refresh, revoke, web session. |
| `SignIn.swift` | `ASWebAuthenticationSession` with PKCE (S256), `state` and `iss` checks, redirect `waypoint://auth`. |
| `ServerSession.swift` | Keeps the server and tokens in the Keychain, refreshes tokens one at a time (refresh tokens rotate; reuse revokes the grant), hands the web view its session cookie. |
| `ShellViewController.swift` | `CAPBridgeViewController` that loads the person's server instead of bundled files. |
| `Keychain.swift`, `PKCE.swift` | Helpers. |
| `Tests/WaypointTests.swift` | PKCE (RFC 7636 vector), address normalising, sign-in reply checks. |

## How sign-in works

1. `GET <server>/api/trips` with no credentials. `200` means the server has no sign-in of its own: the app just opens it.
2. Otherwise read `/.well-known/oauth-authorization-server` (needs `WAYPOINT_PUBLIC_URL` on the server) and open `/oauth/authorize` for the built-in client `wpc_waypoint_ios`, scope `app`, resource `<issuer>/app`, in the system sheet. The person signs in through their provider and taps Allow.
3. The sheet returns `waypoint://auth?code=…`; the app swaps the code for tokens (`wpa_` access, `wpr_` refresh), stored in the Keychain.
4. Each launch, `POST /auth/app-session` with the access token gives the web view its normal session cookie.

## Not built yet

- Offline encrypted store behind the web app's trip data, local reminders, Face ID lock.
- Share extension (Mail, Safari, Files) and its server route.
- Push notifications and the relay.
- Sign out in Settings (the code, `ServerSession.signOut`, exists but nothing calls it from the web UI).
- Servers behind a forward-auth proxy, and self-signed certificates (App Transport Security only relaxes local-network addresses).
- File picker, downloads and `webcal://` handling in the web view.
- Running the app on a simulator or device in CI (the iOS workflow builds it and runs the unit tests only).
