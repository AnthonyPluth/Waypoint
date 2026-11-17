---
title: iPhone app
description: How the Waypoint iPhone app signs in to your server, what it can reach and how to end it.
sidebar:
  order: 20
---

The Waypoint iPhone app is a native shell around your own Waypoint. It signs in to the server you point it at; nothing goes through anyone else's server except an optional wake-up signal for notifications.

## Signing in

The app opens a system sign-in sheet to your server's `/oauth/authorize` page. The sheet is private: iOS shows no consent prompt of its own, but it doesn't share Safari's logins, so you sign in to your OpenID Connect provider each time you sign in to the app. Waypoint sends you through your OpenID Connect provider first, then shows **Waypoint for iPhone wants to connect to Waypoint** with **Allow** and **Deny**. Allowing sends you back to the app with a one-time code, which the app swaps for a token using PKCE.

This needs `WAYPOINT_PUBLIC_URL` set, the same as [connecting an assistant](/Waypoint/start/mcp/). A Waypoint with no sign-in of its own (`OIDC_ISSUER` unset) needs no sign-in at all; the app just opens it.

## What the app can reach

The token has the `app` scope and is for `<WAYPOINT_PUBLIC_URL>/app` only. The server accepts it as a `Bearer` token on the web app's `/api/` routes, as you, so the app can do everything the web app can. It is never accepted on `/mcp`, and an assistant's token is never accepted on `/api/`.

The app's web view is given a normal web session by `POST /auth/app-session`, which needs a valid app token and the `X-Waypoint: 1` header.

## Saved trips

The app can keep your trips on the phone. Saving is on by default on a new install and is per phone. The switch is **Save my upcoming trips** in **Settings → Offline & notifications → Offline access**; switching it off deletes the saved trips at once, and there is no separate Remove. The first save happens when you open Waypoint online after signing in, and signing in again turns saving back on. An older version of the app without this switch shows no Offline access card.

With saving on, the app reads `GET /api/offline` with its own token when the web app opens and each time you return to the app, and replaces the saved set with the reply. Only the trips you are on are in it, and it never holds loyalty or Known Traveler numbers (see [Offline access](/Waypoint/start/offline/)). The reply carries a `version`; the app saves only a version it knows and otherwise keeps the copy it has. If the phone can't reach the server, the copy it has stays and the app tries again the next time, with nothing shown to you.

The saved trips are files in the app's private storage inside its sandbox, protected by iOS Data Protection so they are readable only while the phone is unlocked. Other apps and websites can't read them, Waypoint adds no encryption of its own, and the files can be part of your iCloud and computer backups. Opening saved trips needs no Face ID: the phone's lock is the gate. See [Offline](/Waypoint/start/offline/#in-the-iphone-app). The app deletes them when you sign out (**Use another Waypoint** and a 401 from the server included), when the server answers the app's request with 401 or 403, when saving is turned off or removed, and when the server address changes.

## Ending it

The app's access ends when you can no longer sign in to Waypoint (you are taken off `OIDC_ALLOWED_EMAILS`, or, with groups, your last sign-in is older than `WAYPOINT_SESSION_DAYS`), or when the app drops the connection: it does so by itself when the server says the sign-in is no longer valid or when Waypoint answers 401 while you are using the app, and **Use another Waypoint** on its error screen signs out too. Each of these shows a "You are signed out of Waypoint" screen, and **Sign in** on it asks for the address again. There is no sign-out button in Settings yet. Unlike an assistant, the app does not appear under **Settings → Assistants**.

## Distribution (TestFlight)

You can put the app on your own iPhone through TestFlight with the "iOS TestFlight" workflow. It starts when a change to the iPhone app (`ios/` or its icon; Markdown-only changes under `ios/` do not count, and neither does changing the icon's SVG source alone: regenerate the PNG) is pushed to `main`, or by hand (Actions, **iOS TestFlight**, **Run workflow**, on `main`); never for a pull request. Changes to the web app alone do not start it, because the app loads your server and bundles no web files. It runs in a protected `testflight` environment that holds the signing secrets, and every run, automatic or by hand, waits there until the required reviewer clicks **Approve**. Only one upload runs at a time: while a run waits for approval a newer one queues behind it, and shows Pending with no Approve button until the older one finishes. If a newer push has queued behind a waiting run, cancel the older waiting run on the Actions page (Cancel workflow; it shows grey, not as a rejected deployment), then approve the newest once it asks. The version TestFlight shows is the latest Waypoint release when the run starts building (the same version as the server image, for example 3.49.0), and the number in brackets is the build number, the workflow's run number, so TestFlight lists a build as 3.49.0 (87). If the latest release can't be read, the run stops with an error instead of uploading a made-up version. The build number rises with each new run; re-running a run keeps its number, and App Store Connect refuses a number it already has. It builds on a macOS 26 runner with Xcode 26 (Apple only accepts uploads built with the iOS 26 SDK), archives a signed release, exports an `.ipa` and uploads it with an App Store Connect API key.

Setup happens once:

1. Join the Apple Developer Program and note your Team ID.
2. Register the bundle identifier and create the app in App Store Connect.
3. Create an Apple Distribution certificate and an App Store provisioning profile for that bundle identifier.
4. Create an App Store Connect API key with the App Manager role.
5. Create the `testflight` environment, restricted to `main` with required reviewers.
6. Add these secrets to it: `IOS_DIST_CERT_P12_BASE64`, `IOS_DIST_CERT_PASSWORD`, `IOS_PROVISIONING_PROFILE_BASE64`, `APP_STORE_CONNECT_KEY_ID`, `APP_STORE_CONNECT_ISSUER_ID` and `APP_STORE_CONNECT_KEY_P8_BASE64`. Add these variables: `DEVELOPMENT_TEAM` and `WAYPOINT_BUNDLE_ID`.

Until they exist, the workflow stops at its first step and names what is missing. The first run, started by hand on 2026-11-16, succeeded. The full checklist, with what each secret holds, is in the [iPhone app README](https://github.com/AnthonyPluth/Waypoint/blob/main/ios/README.md).

## Export compliance (encryption)

The app declares `ITSAppUsesNonExemptEncryption` as `false` in its `Info.plist`. This is the answer to Apple's export-compliance question, given once so App Store Connect does not ask on every build. It says the app uses only the encryption built into the phone: HTTPS, the Keychain and the system sign-in sheet.

The Waypoint web app has an offline vault that encrypts saved trips with Web Crypto (AES-256-GCM, ECDH, HKDF and a key derived from a passkey). The iPhone app does not offer it yet, and it would run through the phone's own browser engine. The owner judged the declaration appropriate on that basis. This is not legal advice.

The declaration must be revisited before the offline vault ships on the iPhone. If it does, the export-compliance questions are answered again for that build, and the annual self-classification report is worth considering.
