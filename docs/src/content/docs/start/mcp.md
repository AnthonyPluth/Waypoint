---
title: AI assistants (MCP)
description: Connect Claude or another assistant to Waypoint, to read your trips and, if you allow it, change them.
sidebar:
  order: 7
---

Waypoint serves a [Model Context Protocol](https://modelcontextprotocol.io) endpoint, so an assistant like Claude can answer questions about your travel (what’s coming up, who is on a trip, your stats) and, if you allow it, change it. It never sees your mailboxes, loyalty or Known Traveler numbers, backups or settings, and it reads the text of your email only if you switch that on for one connection.

The assistant is the member who approved it. It sees what that member sees in the app: the trips they’re on, and nothing of a trip only someone else is on. A trip it can’t see is “No such trip”, the same as one that doesn’t exist.

## Connecting

Add Waypoint’s address, `<WAYPOINT_PUBLIC_URL>/mcp`, to the assistant. It is shown under **Settings → Connected assistants**.

- Claude Code: `claude mcp add --transport http waypoint https://waypoint.example.com/mcp`
- Claude on the web or desktop: **Settings → Connectors → Add custom connector**, with the same address.

The assistant then sends you to Waypoint to approve it (sign in first if you aren’t). Tick what you want to allow and choose **Allow**, or **Deny**. Each approval is listed under **Connected assistants** with who approved it and when it was last used; **Disconnect** ends it at once.

- An approval lasts only as long as its approver may sign in. Taking them off `OIDC_ALLOWED_EMAILS` ends their assistants’ connections too. With `OIDC_ALLOWED_GROUPS`, which is checked only at sign-in, a connection ends `WAYPOINT_SESSION_DAYS` after its approver last signed in.
- Waypoint is its own OAuth authorization server (OAuth 2.1 with PKCE, dynamic client registration), and its issuer is `WAYPOINT_PUBLIC_URL`. Without it, assistants can connect only on a home-network address such as `http://localhost:8765`.
- Clients that run OAuth inside a web page, such as the MCP Inspector’s browser mode, aren’t supported: `/mcp` sends no CORS headers and refuses requests from another origin.
- An app that registers but is never approved is forgotten after a day. If Waypoint says it doesn’t know the app, remove it from the assistant and add it again.

## What it can read

An assistant always gets read access to upcoming bookings, trips and their segments with who is travelling, people and guests, [stats](/Waypoint/start/stats/), and the live [flight status](/Waypoint/start/flight-status/) Waypoint already holds. It never makes Waypoint look anything up. Times are wall-clock times at the place, with its zone, as in the app.

### The Review queue

An assistant can also work the [Review](/Waypoint/start/review/) queue of the mailboxes whose items you can see (your own, and those a household member shared). It sees each item as the fields Waypoint already read from it (kind, provider, confirmation code, places, dates, travellers), the sender’s domain, why the item needs review and the bookings it could be. **It does not see the email’s subject, text, snippet or images** unless you [switch that on](#reading-email-text-optional) for the connection. An item that isn’t yours is “No such item”.

- `list_review_items` lists your pending items, newest first, in pages of at most 50.
- `get_review_item` returns one item in full. Each booking it could be carries a `confidence`, worked out by fixed rules with no AI: `exact` when the confirmation codes agree and nothing else disagrees, `likely` when they agree but something else differs (or there is no code and dates, provider and places agree), and `possible` otherwise.

Settling an item changes your trips, so these three need the permissions below, and the assistant is told to ask first. `match_review_item` attaches the booking to a segment or trip you can see. `create_segment_from_review_item` adds a booking from the item, or joins the email to a booking you can see when it is the same reservation. `dismiss_review_item` is destructive: it removes the item and deletes its stored message unless a booking was made from it, so the assistant must get a separate yes. The reason it is given is not kept. No tool removes a segment through the queue, and none touches a mailbox.

## Letting it change trips (optional)

An assistant can ask for **Change trips**: everything the app changes, as the approver, including trips, segments, travellers, people and guests, and the distance unit. Deletes are included and marked as destructive. A change needs both:

- **Change trips** ticked on the approval page. It is offered only when the assistant asks for it, and never ticked for you.
- **Let assistants change trips** switched on in the **Connected assistants** card. It is off until you turn it on, and checked on every change.

Waypoint tells the assistant to describe every change and wait for your yes, and to confirm separately before anything destructive. Anything else the app can do is reached through the same checks.

- An assistant can read a booking’s cost and set one. A cost set this way is entered by hand, so an email never replaces it.
- It can take people off a trip, but not someone who is a traveller on one of its flights. It can’t add anyone who couldn’t already see the trip; that needs you, in the app.
- It can’t merge two trips that involve different people: that is refused and sends you to the app, where you confirm who will newly see what. Merging trips of the same people works.

## Reading email text (optional)

An assistant can read the text and kept markup of the emails Waypoint keeps for the items and bookings you can see, but only on a connection you allow, one by one. It reads the mail of the member who connected it (a shared mailbox included), and only that member can switch it on or off.

It is off for every connection until that member ticks **Read email text** on the assistant’s row under **Connected assistants**, next to the warning *Sends saved booking and Review emails to this assistant. No images or other mail.* An assistant can’t ask for it, and switching it takes effect at once. With it, `get_review_item` adds the item’s `email` and `get_segment_email` returns the messages kept with a booking, newest first, at most 5.

- Text is cut at 20,000 characters and markup at 100,000.
- The markup is the cleaned copy Waypoint keeps, with no scripts, forms or remote pictures.
- An assistant never gets the images, or any message that is not on an item or booking you can see.
- Waypoint logs each such read as a count and the tool’s name only, never any content.

Once an assistant has the text it is in that assistant’s hands, under its provider’s terms. Turn the box off, or disconnect it, to stop further reads.

## What it can never reach

Whatever it was allowed, an assistant can never reach:

- loyalty and Known Traveler numbers, not even their last four characters;
- Gmail mailboxes and scanning, and Review’s queue of mail Waypoint couldn’t read;
- the AI settings, backup and restore, sign-in, and these assistant settings;
- the calendar feed, notification devices and the copies saved for [offline](/Waypoint/start/offline/) use;
- the gate code picture of a parking booking;
- the flight-status refresh, which spends the monthly budget and uses the key;
- the household’s Home place, and importing past flights from a file.

Email is reachable only on a connection you allowed to read email text.

## Tokens

`/mcp` speaks Streamable HTTP with JSON replies and a bearer access token. Access tokens last an hour and refresh tokens 90 days. Refresh tokens rotate, and a used one sent again revokes the whole connection. Only hashes of tokens and codes are stored, and none of this goes into [backups](/Waypoint/start/docker/#moving-your-data-from-another-machine): reconnect assistants after a restore.

## Behind a proxy

Registration needs no sign-in, so anyone who can reach Waypoint can register apps, with at most 50 unapproved at once. Waypoint has no per-address rate limiting; put it at the reverse proxy.

With `WAYPOINT_ALLOW_NO_AUTH=1` and a forward-auth proxy (Authelia, Cloudflare Access, oauth2-proxy), exempt `/mcp`, `/oauth/register`, `/oauth/token`, `/oauth/revoke` and `/.well-known/oauth-*` from the proxy’s sign-in, since assistants call them without a browser. Keep `/oauth/authorize` behind it: that is where you approve. Without sign-in of Waypoint’s own, an assistant acts as the whole household and sees every trip.
