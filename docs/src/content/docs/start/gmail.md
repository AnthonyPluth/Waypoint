---
title: Google OAuth client for Gmail
description: Create the Google Cloud OAuth client Waypoint uses to connect each member’s Gmail, read-only.
sidebar:
  order: 3
---

Waypoint reads bookings from Gmail with a Google OAuth client that **you** create in your own Google Cloud project, so no one else’s app sits between your mailbox and your server. This page sets that up once for the household; after that, each member connects their own Gmail from **Settings → Gmail**.

:::note[What’s here today]
Connecting, disconnecting and the “Reconnect” state work. Scanning the mailbox for bookings isn’t built yet, so a connected Gmail isn’t read for anything until it is. What Waypoint will do with it is described under [Email scanning](/waypoint/privacy/email-scanning/).
:::

## Create the client

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project (any name, such as “Waypoint”).
2. **APIs & Services → Library**: enable the **Gmail API**.
3. **APIs & Services → OAuth consent screen**: choose **External**, give it a name and your email, and add only one scope: `https://www.googleapis.com/auth/gmail.readonly`. Waypoint asks for nothing else, so it can’t send, delete, label or change anything.
4. Still on the consent screen, set the publishing status to **In production** (**Publish app**). Leave it unverified: Google doesn’t need to review an app that only your household uses, and each member clicks through its “Google hasn’t verified this app” warning once when connecting.

   :::caution[Don’t leave it in “Testing”]
   While an app is in **Testing**, Google expires its refresh tokens after 7 days, so every Gmail would turn to “Reconnect” weekly. Publish it **In production**.
   :::
5. **APIs & Services → Credentials → Create credentials → OAuth client ID**: choose **Web application**, and add this **authorized redirect URI**, using the address you open Waypoint at (`WAYPOINT_PUBLIC_URL`):

   ```
   https://waypoint.example.com/api/mailboxes/callback
   ```

   Without sign-in, on your own machine, it is the address you open Waypoint at instead, such as `http://localhost:8765/api/mailboxes/callback`.
6. Copy the client ID and secret into `.env` and restart Waypoint:

   ```
   GOOGLE_CLIENT_ID=1234567890-example.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=GOCSPX-example
   ```

Until both are set, Settings says Gmail isn’t set up and shows no Connect button.

## Connect a Gmail

Each member opens **Settings → Gmail** and chooses **Connect Gmail**, picks the Google account and agrees to read-only access. A member can connect more than one address (a personal and a work one, say), and sees only their own connections: nobody else’s address or status appears for them.

- **Reconnect.** If Google stops honouring a connection (you removed Waypoint at [myaccount.google.com/permissions](https://myaccount.google.com/permissions), the grant expired, or Waypoint’s secret key changed), its row says **Reconnect**. Choosing it connects the same address again.
- **Disconnect.** Waypoint tells Google to revoke its access, then deletes the connection. If Google can’t be reached it keeps the connection and says so, rather than showing it gone while it still works; try again, or remove Waypoint at the Google permissions page.
- **When someone loses access.** A connection ends when the person who made it can no longer sign in to Waypoint (taken off `OIDC_ALLOWED_EMAILS`, or past their sign-in with `OIDC_ALLOWED_GROUPS`): Waypoint checks before every use, revokes the token at Google and deletes it.

## What Waypoint keeps

Per connection: the Gmail address, a **refresh token** and where its scans had got to. The refresh token is encrypted with `WAYPOINT_SECRET_KEY` (in backups too), is decrypted only to refresh or revoke it, and never appears in logs or error pages. Access tokens are used for the one call that needs them and aren’t kept. A backup holds the connections, so restoring one needs the same key; otherwise the connections turn to **Reconnect**.
