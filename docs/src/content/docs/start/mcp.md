---
title: AI assistants (MCP)
description: Connect Claude or another assistant to Waypoint, to read your trips and, if you allow it, change them.
sidebar:
  order: 7
---

Waypoint serves a [Model Context Protocol](https://modelcontextprotocol.io) endpoint, so an assistant like Claude can answer questions about your travel (what’s coming up, who is on a trip, your stats) and, if you allow it, change it. It never sees your mailboxes, loyalty or Known Traveler numbers, backups or settings, and it reads the text of your email only if you switch that on for one connection.

**The assistant is the member who approved it.** It sees exactly what that member sees in the app: the trips they’re on, and nothing of a trip only someone else is on. A trip it can’t see is “No such trip”, the same as one that doesn’t exist.

## Connecting

Add Waypoint’s address, `<WAYPOINT_PUBLIC_URL>/mcp`, to the assistant. It’s shown with a copy button under **Settings → Connected assistants**.

- Claude Code: `claude mcp add --transport http waypoint https://waypoint.example.com/mcp`
- Claude on the web or desktop: **Settings → Connectors → Add custom connector**, with the same address.

The assistant then sends you to Waypoint to approve it (sign in first if you aren’t). The page names the app and the address it returns to; tick what you want to allow and choose **Allow**, or **Deny**. Each approval shows up under **Connected assistants** on the same card, with who approved it and when it was last used; **Disconnect** ends it at once.

An approval lasts only as long as its approver may sign in, like a browser session. Taking them off `OIDC_ALLOWED_EMAILS` ends their assistants’ connections too, and with `OIDC_ALLOWED_GROUPS` (checked only at sign-in) a connection ends `WAYPOINT_SESSION_DAYS` after its approver last signed in.

Waypoint is its own OAuth authorization server (OAuth 2.1 with PKCE, dynamic client registration), and its issuer is `WAYPOINT_PUBLIC_URL`. Without it, assistants can connect only on a home-network address (`http://localhost:8765`, `http://nas.local:8765`, …).

Clients that run OAuth inside a web page aren’t supported: Waypoint sends no CORS headers, and `/mcp` refuses requests from a page on another origin. Claude Code and Claude on the web or desktop work; test with those, not the MCP Inspector’s browser mode.

An app that registers but is never approved is forgotten after a day (and at most 50 wait at once). If Waypoint says it doesn’t know the app, remove Waypoint from the assistant and add it again.

## What it can read

An assistant always gets **read**: upcoming flights, stays, rentals, trains, cruises and parking, trips and a trip’s segments with who is travelling, people and guests, [stats](/Waypoint/start/stats/), and the live [flight status](/Waypoint/start/flight-status/) Waypoint already holds (an assistant never makes Waypoint look anything up). Times are the wall-clock times at the place, with its zone, as in the app.
The tools are `upcoming`, `list_trips`, `get_trip`, `list_people`, `get_stats` and `flight_status`.

### The Review queue

An assistant can also work the [Review](/Waypoint/start/review/) queue of the mailboxes whose items you can see (your own, and those a household member shared). It sees each item as the fields Waypoint already read from it, the same kind of data `get_trip` returns for a booking: the kind, provider, confirmation code, places, address, phone, start and end with their zones, travellers (as the email printed them), which fields the reader marked as read, the sender’s domain, why the item needs review and the bookings it could be. **It does not see the email’s subject, text, snippet or images** unless you [switch that on](#reading-email-text-optional) for the connection. An item that isn’t yours is “No such item”, like one that doesn’t exist.

- `list_review_items`: your pending items, newest first, with filters (`reason`, `kind`, `mailbox`, `has_match`, `since`) and pages of at most 50 with a `cursor`; it says how many it didn’t show.
- `get_review_item`: one item in full, with each booking in it and the bookings it could be. Every candidate carries a `confidence` of `exact`, `likely` or `possible` and the fields that agreed and differed (confirmation code, provider, kind, places, dates). It is worked out by fixed rules, the same every time, with no AI: `exact` when the confirmation codes agree and nothing else disagrees, `likely` when they agree but something else differs, or there is no code to compare and the dates, provider and places all agree, and `possible` otherwise.

Settling an item changes your trips, so these three need **Change trips** and the **Let assistants change trips** switch like any other change, and the assistant is told to ask first: `match_review_item` (attach the booking to a segment you can see, which gets the item’s confirmation code and link, or add it to a trip you can see), `create_segment_from_review_item` (add a booking from the item, correcting any field, with the same checks as adding by hand; when it is the same reservation as a booking you can see, the email joins that booking instead, filling only what it lacks) and `dismiss_review_item` (not a trip). **Dismissing is destructive**: it removes the item and deletes its stored message unless a booking was made from it, as the Review page’s dismiss does, so the assistant must get a separate yes. The reason it is given (not travel, duplicate, already added or other, and a short note) is not kept. No tool removes a segment through the queue, and none touches a mailbox.

## Letting it change trips (optional)

An assistant can also ask for **Change trips**: everything the app changes, as the approver. That’s trips (add, rename, merge, split, remove), segments (add, edit, move to another trip, remove), travellers, people and guests, and the distance unit; deletes are included, and marked as destructive. A change needs both:

- **Change trips** ticked on the approval page (offered only when the assistant asks for it, and never ticked for you), and
- **Let assistants change trips** switched on in the card. It’s off until you turn it on, and checked on every change.

Waypoint tells the assistant to describe every change and wait for your yes, and to confirm separately before anything destructive. The changing tools are `add_segment`, `update_segment`, `remove_segment`, `create_trip`, `update_trip`, `merge_trips`, `add_guest` and `update_person`. An assistant can read a booking’s cost and a trip’s totals (they are in the trip), and `update_segment` can set a cost (`price`: an amount in the currency’s smallest unit and a currency code, or `null` to remove it) under the same rules as any other change, which makes it a cost entered by hand that an email never replaces. A trip can have a list of people (`people` on `create_trip` and `update_trip`). An assistant can take people off it, but not someone who is a traveller on one of its flights, and it can’t add anyone who couldn’t already see the trip: that needs you, in the app. It also can’t merge two trips that involve different people (`merge_trips` is refused and tells it to send you to the app, where you confirm who will newly see what); merging trips of the same people works. `list_endpoints` lists everything else it can reach and `call_endpoint` calls it, through the same checks.

## Reading email text (optional)

Beyond the parsed fields, an assistant can read the text and kept markup of the emails Waypoint keeps for the items and bookings you can see, but only on a connection you allow, one by one. It is the mail of the member who connected it that the assistant reads (what that member can see, a shared mailbox included), and only that member can switch it on or off for their connection. It is **off for every connection** until the member who connected it ticks **Read email text** on that assistant’s row under **Connected assistants**, next to a plain warning: *This sends the email’s text and markup to the assistant you connected.* It is a scope of its own (`mail`), separate from **read** and **Change trips**, switched on and off from Settings only (an assistant can’t ask for it), and effective at once.

With it, `get_review_item` adds the item’s `email` (subject, sender’s domain, day, text and, for a message kept as the original, its kept markup as `html`, and whether the original or the plain text was kept) and `get_segment_email` gives the messages kept with a booking (newest first, at most 5). The text is cut at 20,000 characters and the markup at 100,000 (`html_truncated` says so). The markup is the cleaned copy Waypoint keeps (no scripts, forms or remote pictures), and a message kept as plain text has `html` null. An assistant never gets the images, or any message that is not on an item or booking you can see. Waypoint logs each such read as a count and the tool’s name only, never any content. Once an assistant has the text it is in that assistant’s hands, under its provider’s terms: turn the box off, or disconnect it, to stop further reads.

## What it can never reach

Whatever it was allowed and whatever the switch says, an assistant can never reach: loyalty and Known Traveler numbers (an assistant has no need of one, so not even their last four characters, nor the list of memberships), Gmail mailboxes and scanning, Review’s queue of mail it couldn’t read, the AI settings, backup and restore, sign-in and who’s signed in, the calendar feed and notification devices, the copies of your upcoming trips saved for offline use, the gate code picture of a parking booking (and any sign that a booking has one), the flight-status refresh (it spends the monthly budget and uses the key), the household's Home place, importing past flights from a file, and these assistant settings themselves. **Your email is reachable only on a connection you allowed to read email text**: otherwise an assistant gets no subject, text, snippet or image, only the fields Waypoint parsed from a review item, and the original Review and booking-email routes stay closed to it either way. A flight read from an email is a segment like any other, which is the household’s own data. The list is `BLOCKED` in `waypoint/server/mcp_access.py`, and a test lists every route as reachable or blocked, so a new route has to be decided on.

## Endpoints

| Path | What |
| --- | --- |
| `POST /mcp` | MCP (Streamable HTTP, JSON replies), with `Authorization: Bearer <access token>` |
| `GET /.well-known/oauth-protected-resource/mcp` | Protected-resource metadata (RFC 9728) |
| `GET /.well-known/oauth-authorization-server` | Authorization-server metadata (RFC 8414) |
| `POST /oauth/register` | Dynamic client registration (RFC 7591) |
| `GET/POST /oauth/authorize` | The approval page (needs you signed in) |
| `POST /oauth/token` | Codes and refresh tokens for tokens |
| `POST /oauth/revoke` | Revocation (RFC 7009) |

Access tokens last an hour and refresh tokens 90 days; refresh tokens rotate, and a used one sent again revokes the whole connection. Only hashes of tokens and codes are stored, and none of this goes into [backups](/Waypoint/start/docker/#moving-your-data-from-another-machine): reconnect assistants after a restore.

## Behind a proxy

Registration (`/oauth/register`) needs no sign-in, so anyone who can reach Waypoint can register apps (never more than 50 unapproved at once). Waypoint has no per-address rate limiting; put it at the reverse proxy.

With `WAYPOINT_ALLOW_NO_AUTH=1` and a forward-auth proxy (Authelia, Cloudflare Access, oauth2-proxy), exempt these paths from the proxy’s sign-in, since assistants call them without a browser: `/mcp`, `/oauth/register`, `/oauth/token`, `/oauth/revoke` and `/.well-known/oauth-*`. Keep `/oauth/authorize` behind it: that’s where you approve. Without sign-in of Waypoint’s own, an assistant acts as the whole household and sees every trip.
