---
title: Google OAuth client for Gmail
description: "Coming in Phase 3: the Google Cloud client Waypoint will use to read your booking emails."
sidebar:
  order: 3
---

:::caution[Coming in Phase 3]
Email scanning isn’t built yet, so there is nothing to set up. This page will walk through the steps below once it is.
:::

Waypoint will read your bookings with a Google OAuth client that **you** create in your own Google Cloud project, so no one else’s app sits between your mailbox and your server. The outline:

1. Create a Google Cloud project and enable the Gmail API.
2. Configure the OAuth consent screen with only the read-only Gmail scope.
3. Create a “Web application” client with `<WAYPOINT_PUBLIC_URL>/…` as its redirect URI (the exact path will be given here).
4. Paste the client ID and secret into Waypoint’s Settings, then connect the mailbox.

What Waypoint does with the mailbox is described under [Email scanning](/waypoint/privacy/email-scanning/).
