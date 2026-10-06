---
title: AI assistants (MCP)
description: Connect Claude or another assistant to Waypoint, to read your trips and, if you allow it, change them.
sidebar:
  order: 7
---

Waypoint serves a [Model Context Protocol](https://modelcontextprotocol.io) endpoint, so an assistant like Claude can answer questions about your travel (what’s coming up, who is on a trip, your stats) and, if you allow it, change it. It never sees your email, mailboxes, loyalty or Known Traveler numbers, backups or settings.

**The assistant is the member who approved it.** It sees exactly what that member sees in the app: the trips they’re on, and nothing of a trip only someone else is on. A trip it can’t see is “No such trip”, the same as one that doesn’t exist.

## Connecting

Add Waypoint’s address, `<WAYPOINT_PUBLIC_URL>/mcp`, to the assistant. It’s shown with a copy button under **Settings → Data → AI assistants (MCP)**.

- Claude Code: `claude mcp add --transport http waypoint https://waypoint.example.com/mcp`
- Claude on the web or desktop: **Settings → Connectors → Add custom connector**, with the same address.

The assistant then sends you to Waypoint to approve it (sign in first if you aren’t). The page names the app and the address it returns to; tick what you want to allow and choose **Allow**, or **Deny**. Each approval shows up under **Connected assistants** on the same card, with who approved it and when it was last used; **Disconnect** ends it at once.

An approval lasts only as long as its approver may sign in, like a browser session. Taking them off `OIDC_ALLOWED_EMAILS` ends their assistants’ connections too, and with `OIDC_ALLOWED_GROUPS` (checked only at sign-in) a connection ends `WAYPOINT_SESSION_DAYS` after its approver last signed in.

Waypoint is its own OAuth authorization server (OAuth 2.1 with PKCE, dynamic client registration), and its issuer is `WAYPOINT_PUBLIC_URL`. Without it, assistants can connect only on a home-network address (`http://localhost:8765`, `http://nas.local:8765`, …).

Clients that run OAuth inside a web page aren’t supported: Waypoint sends no CORS headers, and `/mcp` refuses requests from a page on another origin. Claude Code and Claude on the web or desktop work; test with those, not the MCP Inspector’s browser mode.

An app that registers but is never approved is forgotten after a day (and at most 50 wait at once). If Waypoint says it doesn’t know the app, remove Waypoint from the assistant and add it again.

## What it can read

An assistant always gets **read**: upcoming flights, stays, rentals and trains, trips and a trip’s segments with who is travelling, people and guests, [stats](/Waypoint/start/stats/), and the live [flight status](/Waypoint/start/flight-status/) Waypoint already holds (an assistant never makes Waypoint look anything up). Times are the wall-clock times at the place, with its zone, as in the app.
The tools are `upcoming`, `list_trips`, `get_trip`, `list_people`, `get_stats` and `flight_status`.

## Letting it change trips (optional)

An assistant can also ask for **Change trips**: everything the app changes, as the approver. That’s trips (add, rename, merge, split, remove), segments (add, edit, remove), travellers, people and guests, and the distance unit; deletes are included, and marked as destructive. A change needs both:

- **Change trips** ticked on the approval page (offered only when the assistant asks for it, and never ticked for you), and
- **Let assistants change trips** switched on in the card. It’s off until you turn it on, and checked on every change.

Waypoint tells the assistant to describe every change and wait for your yes, and to confirm separately before anything destructive. The changing tools are `add_segment`, `update_segment`, `remove_segment`, `create_trip`, `update_trip`, `merge_trips`, `add_guest` and `update_person`. `list_endpoints` lists everything else it can reach and `call_endpoint` calls it, through the same checks.

## What it can never reach

Whatever it was allowed and whatever the switch says, an assistant can never reach: loyalty and Known Traveler numbers (an assistant has no need of one, so not even their last four characters, nor the list of memberships), Gmail mailboxes and scanning, the “Couldn’t read” queue, the AI settings, backup and restore, sign-in and who’s signed in, the calendar feed and notification devices, the flight-status refresh (it spends the monthly budget and uses the key), the Logo.dev settings, importing past flights from a file, and these assistant settings themselves. **Nothing from your email is reachable**: no body, subject or review item. A flight read from an email is a segment like any other, which is the household’s own data. The list is `BLOCKED` in `waypoint/server/mcp_access.py`, and a test lists every route as reachable or blocked, so a new route has to be decided on.

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
