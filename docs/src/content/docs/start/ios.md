---
title: iPhone app
description: How the Waypoint iPhone app signs in to your server, what it can reach and how to end it.
sidebar:
  order: 20
---

The Waypoint iPhone app is a native shell around your own Waypoint. It signs in to the server you point it at; nothing goes through anyone else's server except an optional wake-up signal for notifications.

## Signing in

The app opens a system sign-in sheet to your server's `/oauth/authorize` page. The sheet is private: iOS shows no consent prompt of its own, but it doesn't share Safari's logins, so you sign in to your OpenID Connect provider each time you sign in to the app. Waypoint sends you through your OpenID Connect provider first if you aren't signed in, then shows **Waypoint for iPhone wants to connect to Waypoint** with **Allow** and **Deny**. Allowing sends you back to the app with a one-time code, which the app swaps for a token using PKCE.

This needs `WAYPOINT_PUBLIC_URL` set, the same as [connecting an assistant](/Waypoint/start/mcp/). A Waypoint with no sign-in of its own (`OIDC_ISSUER` unset) needs no sign-in at all; the app just opens it.

## What the app can reach

The token has the `app` scope and is for `<WAYPOINT_PUBLIC_URL>/app` only. The server accepts it as a `Bearer` token on the web app's `/api/` routes, as you, so the app can do everything the web app can. It is never accepted on `/mcp`, and an assistant's token is never accepted on `/api/`.

The app's web view is given a normal web session by `POST /auth/app-session`, which needs a valid app token and the `X-Waypoint: 1` header.

## Ending it

The app's access ends when you can no longer sign in to Waypoint (you are taken off `OIDC_ALLOWED_EMAILS`, or, with groups, your last sign-in is older than `WAYPOINT_SESSION_DAYS`), or when the app drops the connection: it does so by itself when the server says the sign-in is no longer valid or when Waypoint answers 401 while you are using the app, and **Use another Waypoint** on its error screen signs out too. Each of these shows a "You are signed out of Waypoint" screen, and **Sign in** on it asks for the address again. There is no sign-out button in Settings yet. Unlike an assistant, the app does not appear under **Settings → Assistants**.

## Distribution (TestFlight)

You can put the app on your own iPhone through TestFlight with the "iOS TestFlight" workflow. It starts only by hand (Actions, **iOS TestFlight**, **Run workflow**, on `main`), never for a pull request, and runs in a protected `testflight` environment that holds the signing secrets and waits for a required reviewer. It builds on a macOS 26 runner with Xcode 26 (Apple only accepts uploads built with the iOS 26 SDK), archives a signed release, exports an `.ipa` and uploads it with an App Store Connect API key.

Setup happens once:

1. Join the Apple Developer Program and note your Team ID.
2. Register the bundle identifier and create the app in App Store Connect.
3. Create an Apple Distribution certificate and an App Store provisioning profile for that bundle identifier.
4. Create an App Store Connect API key with the App Manager role.
5. Create the `testflight` environment, restricted to `main` with required reviewers.
6. Add these secrets to it: `IOS_DIST_CERT_P12_BASE64`, `IOS_DIST_CERT_PASSWORD`, `IOS_PROVISIONING_PROFILE_BASE64`, `APP_STORE_CONNECT_KEY_ID`, `APP_STORE_CONNECT_ISSUER_ID` and `APP_STORE_CONNECT_KEY_P8_BASE64`. Add these variables: `DEVELOPMENT_TEAM` and `WAYPOINT_BUNDLE_ID`.

Until they exist, the workflow stops at its first step and names what is missing. The signing and upload path has not been run yet, so expect to fix the first run. The full checklist, with what each secret holds, is in the [iPhone app README](https://github.com/AnthonyPluth/Waypoint/blob/main/ios/README.md).
