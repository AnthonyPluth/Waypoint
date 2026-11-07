---
title: iPhone app
description: How the Waypoint iPhone app signs in to your server, what it can reach and how to end it.
sidebar:
  order: 20
---

The Waypoint iPhone app is a native shell around your own Waypoint. It signs in to the server you point it at; nothing goes through anyone else's server except an optional wake-up signal for notifications.

## Signing in

The app opens a system sign-in sheet to your server's `/oauth/authorize` page. If you aren't signed in, Waypoint sends you through your OpenID Connect provider first, then shows **Waypoint for iPhone wants to connect to Waypoint** with **Allow** and **Deny**. Allowing sends you back to the app with a one-time code, which the app swaps for a token using PKCE.

This needs `WAYPOINT_PUBLIC_URL` set, the same as [connecting an assistant](/Waypoint/start/mcp/). A Waypoint with no sign-in of its own (`OIDC_ISSUER` unset) needs no sign-in at all; the app just opens it.

## What the app can reach

The token has the `app` scope and is for `<WAYPOINT_PUBLIC_URL>/app` only. The server accepts it as a `Bearer` token on the web app's `/api/` routes, as you, so the app can do everything the web app can. It is never accepted on `/mcp`, and an assistant's token is never accepted on `/api/`.

The app's web view is given a normal web session by `POST /auth/app-session`, which needs a valid app token and the `X-Waypoint: 1` header.

## Ending it

The app's access ends when you can no longer sign in to Waypoint (you are taken off `OIDC_ALLOWED_EMAILS`, or, with groups, your last sign-in is older than `WAYPOINT_SESSION_DAYS`), or when the app drops the connection: it does so by itself when the server says the sign-in is no longer valid, and **Use another Waypoint** on its error screen signs out and asks for a new address. There is no sign-out button in Settings yet. Unlike an assistant, the app does not appear under **Settings → Assistants**.
