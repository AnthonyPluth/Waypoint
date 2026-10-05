---
title: Configuration
description: Every environment variable Waypoint reads.
sidebar:
  order: 1
---

Settings that belong to the app live in **Settings** and are stored in the database. Everything about how and where Waypoint runs is set with environment variables, in `.env` for Docker (start from [`.env.example`](https://github.com/AnthonyPluth/waypoint/blob/main/.env.example)) or in the environment for a source checkout.

| Variable | Default | What it does |
|---|---|---|
| `WAYPOINT_PUBLIC_URL` | | The address you open Waypoint at, e.g. `https://waypoint.example.com`. Required with sign-in. The calendar feed’s address and Gmail’s return address are made from it. |
| `OIDC_ISSUER` | | Your identity provider’s issuer URL. Setting it turns sign-in on. |
| `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | | The client registered with your provider. Leave the secret empty for a public (PKCE-only) client. |
| `OIDC_ALLOWED_EMAILS` | | Comma-separated emails allowed in. An email counts only if your provider marks it verified (`email_verified`). |
| `OIDC_ALLOWED_GROUPS` | | Comma-separated groups (from the `groups` claim) allowed in. Groups are checked at sign-in. |
| `OIDC_ALLOW_ANY_USER` | | `1` lets in anyone your provider signs in. Only for a provider you fully control. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | | The OAuth client you create in your own Google Cloud project, so members can connect their Gmail from Settings (read-only). Both are needed; see [Google OAuth client for Gmail](/waypoint/start/gmail/). |
| `RAPIDAPI_KEY` | | Turns on [live flight status](/waypoint/start/flight-status/): your RapidAPI key, subscribed to AeroDataBox. It stays in the environment and is never saved or logged. Only a flight number and a date are sent. |
| `WAYPOINT_FLIGHT_STATUS_MONTHLY_LIMIT` | `400` | The calls a month your RapidAPI plan allows. At 90% scheduled checks stop except the one-hour check; at 100% nothing is fetched until the 1st. |
| `WAYPOINT_SESSION_DAYS` | `14` | Days a session lasts unused. Using Waypoint keeps it going, for up to 90 days after signing in. |
| `WAYPOINT_SECRET_KEY` | | Encrypts the secrets Waypoint saves (at least 32 characters: `openssl rand -base64 32`). Without it, Waypoint makes `secret.key` in `WAYPOINT_DATA`. |
| `WAYPOINT_SECRET_KEY_OLD` | | The previous key, for one start after changing `WAYPOINT_SECRET_KEY`; everything is re-encrypted with the new one. Also the way to restore a backup made under an earlier key. |
| `WAYPOINT_ALLOW_INSECURE_HTTP` | | `1` allows an `http://` `WAYPOINT_PUBLIC_URL` on an internet address. Don’t. |
| `WAYPOINT_ALLOW_NO_AUTH` | | `1` runs without sign-in on the network, for when a proxy in front already handles it. |
| `DATABASE_URL` | | `postgresql://user:password@host:5432/db` to use Postgres instead of the built-in SQLite file. |
| `WAYPOINT_DATA` | `./data` (`/data` in Docker) | Where the SQLite database lives. |
| `WAYPOINT_HOST` / `WAYPOINT_PORT` | `127.0.0.1` / `8765` | Address and port to listen on (`0.0.0.0` in Docker). |
| `TZ` | America/New_York (Docker image); the system’s otherwise | The time zone Waypoint uses for “today” and for its logs. |

Waypoint has no error-reporting service: errors go to its own log. See [Errors and logs](/waypoint/start/docker/#errors-and-logs).

With no `OIDC_ISSUER`, Waypoint refuses to listen beyond `localhost` unless `WAYPOINT_ALLOW_NO_AUTH` is set. See [Install with Docker](/waypoint/start/docker/) and [SECURITY.md](https://github.com/AnthonyPluth/waypoint/blob/main/SECURITY.md).

## Advanced

Rarely needed, so `.env.example` leaves them out. They work when set in `.env` (Docker passes everything in it to Waypoint) or in the environment.

| Variable | Default | What it does |
|---|---|---|
| `OIDC_SCOPES` | `openid email profile` | Add `groups` if your provider needs it to send group membership. |
| `OIDC_TRUST_UNVERIFIED_EMAIL` | | `1` lets `OIDC_ALLOWED_EMAILS` match an email your provider doesn’t mark verified. Only for a provider where nobody can register or change their own email (Microsoft Entra ID never sends `email_verified`). |
| `WAYPOINT_ALLOWED_HOSTS` | | Extra host names Waypoint answers to (local IPs, `*.local`, bare names and Tailscale names always work). |

Waypoint also sets `WAYPOINT_VERSION` itself in the Docker image; it’s shown in Settings and tagged on error reports, and you don’t set it.
