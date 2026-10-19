---
title: Install with Docker
description: Start locally with no accounts or API keys, add sign-in if you want it, move your data over and put it on the internet safely.
sidebar:
  order: 1
---

Waypoint starts locally with no account, sign-in provider or third-party credentials. The image holds Python, Waypoint’s dependencies, the web app and the travel brand logos. It keeps its data in SQLite under `/data`, or in Postgres if you set `DATABASE_URL`.

## First start

```bash
git clone https://github.com/AnthonyPluth/Waypoint.git
cd Waypoint
docker compose up -d
docker compose logs -f waypoint
```

Open `http://localhost:8765` and add household members and bookings straight away. No `.env` file is needed. The database and its generated encryption key are saved in `./data`: keep that folder when you update or move the container.

The Compose file publishes port 8765 on localhost only. Without sign-in, anyone who can reach the app sees the household’s trips and can change its settings, so before you publish the port to other devices, keep it on a trusted private network or turn on sign-in. Never publish an unauthenticated instance to the internet.

Gmail, AI suggestions, live flight status, connected assistants and push notifications are optional and each has its own page. [Brand logos](/Waypoint/start/logos/) and the trip map are bundled and need no connection.

The image is `ghcr.io/anthonypluth/waypoint:latest`, for Intel/AMD and ARM. To stay on a version, pin a tag in `docker-compose.yml`: `image: ghcr.io/anthonypluth/waypoint:2` follows a major version, `:2.131` a minor one and `:2.131.5` one release.

## Optional sign-in

Waypoint signs people in through your own OpenID Connect provider (Authentik, Authelia, Keycloak, Pocket ID, Google, Microsoft Entra, …). Create a confidential OIDC / OAuth2 application there with the authorization code flow:

| Setting | Value |
|---|---|
| Redirect URI | `<WAYPOINT_PUBLIC_URL>/auth/callback` |
| Post-logout redirect URI | `<WAYPOINT_PUBLIC_URL>/auth/signed-out` (optional) |
| Scopes | `openid email profile`, plus `groups` for group-based access |
| ID token signing | RS256 (the usual default); PS256, ES256 and EdDSA work too |

Copy `.env.example` to `.env`, fill in `WAYPOINT_PUBLIC_URL`, `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` and `OIDC_ALLOWED_EMAILS` or `OIDC_ALLOWED_GROUPS`, and restart with `docker compose up -d`. Setting `OIDC_ISSUER` turns sign-in on; incomplete settings stop startup with a message in the logs. Leave the issuer empty to keep local mode.

Everyone who can sign in belongs to one household: they share settings and loyalty numbers, and each sees the trips they travel on, booked or received the confirmation for. In local mode there is one household that sees every trip.

- Only people in `OIDC_ALLOWED_EMAILS` or `OIDC_ALLOWED_GROUPS` get in, even if your provider lets others sign in. Someone refused sees that, with a button to try another account, and the log says who was refused.
- A session ends after 14 days without using Waypoint (`WAYPOINT_SESSION_DAYS`), or 90 days after signing in. Someone let in by group rather than by email is signed out 14 days after signing in, so leaving the group takes effect.
- Waypoint answers only to addresses that are yours: the host in `WAYPOINT_PUBLIC_URL`, local IPs, `*.local`, plain names like `nas` and Tailscale names. Add others with `WAYPOINT_ALLOWED_HOSTS` ([Configuration](/Waypoint/reference/configuration/#advanced)).
- Use an `https://` address for `WAYPOINT_PUBLIC_URL`, so session cookies are marked Secure. On an internet address Waypoint requires it.

**Settings** is grouped into cards: Account, Mail & review, Travel preferences, Offline & notifications, Connected assistants, and Backup & import. The rest of these pages name a control by its card.

## Moving your data from another machine

1. On the old machine, go to **Settings → Backup & import → Backup** and choose **Download a backup** (or run `poetry run python run.py backup`).
2. Start the container on the new machine, sign in, and go to **Settings → Backup & import → Backup → Restore** with that file. Or copy the file into `./data`, stop the container and run `docker compose run --rm waypoint python run.py restore /data/<file> --yes`.

A backup holds Waypoint’s saved secrets encrypted with your key, so set the same `WAYPOINT_SECRET_KEY` on the new machine (or copy `secret.key` into its `./data`) before restoring. If you restore under a different key, put the old key in `WAYPOINT_SECRET_KEY_OLD` and restart once: Waypoint re-encrypts the secrets with the current key. Delete stray copies of the backup once it is restored.

:::note
A backup made before Waypoint’s migration history was squashed can’t be restored by this version, and Waypoint says so. Restore it with the last release before the squash, take a new backup there and restore that one here. The same applies to updating in place: a database last started before the squash must first run the last release before it once.
:::

## Using Postgres (optional)

Set `DATABASE_URL` in `.env` (for example `postgresql://waypoint:password@db-host:5432/waypoint`) and restart. Waypoint creates its tables on first start and applies schema migrations when a new version starts. To bring existing data along, restore a backup into it as above. `docker-compose.yml` has a commented-out `db` service if you want Postgres alongside Waypoint.

## Behind a reverse proxy

Run Waypoint behind a reverse proxy that terminates HTTPS (Caddy, Traefik, nginx) and set `WAYPOINT_PUBLIC_URL` to the public `https://` address. When the proxy runs on the same machine, keep the port published on localhost only, so nothing reaches Waypoint around it:

```yaml
ports:
  - "127.0.0.1:8765:8765"
```

A minimal Caddyfile:

```
waypoint.example.com {
    reverse_proxy 127.0.0.1:8765
}
```

If you already sign in at the proxy (Authelia forward-auth, Cloudflare Access, oauth2-proxy), leave `OIDC_ISSUER` empty, set `WAYPOINT_ALLOW_NO_AUTH=1`, and expose port 8765 only through that proxy.

Behind Cloudflare or another CDN, leave it on its default of respecting the origin’s cache headers: Waypoint caches the web app’s files under `/assets/` for a year and its fonts and icons for a week, and marks everything else uncacheable. A “cache everything” rule would break the page at `/`, which carries a fresh security nonce on every request, and leak the private replies under `/api/`, `/auth/`, `/oauth/` and `/mcp`. Keep Cloudflare’s Rocket Loader off: it rewrites scripts that Waypoint’s security policy only allows by their nonce.

## Putting Waypoint on the internet

Waypoint is built to be reachable from anywhere, set up like this:

1. **HTTPS in front.** A reverse proxy with a certificate, or Tailscale Funnel, with `WAYPOINT_PUBLIC_URL` set to that `https://` address. Waypoint refuses to start with a plain `http://` internet address.
2. **Sign-in limited to your household.** Use `OIDC_ALLOWED_EMAILS` and/or `OIDC_ALLOWED_GROUPS`, not `OIDC_ALLOW_ANY_USER`, and turn on two-factor sign-in at your identity provider. Everyone you let in shares one Waypoint: they can change its settings, download the backup and restore one (see [SECURITY.md](https://github.com/AnthonyPluth/Waypoint/blob/main/SECURITY.md)).
3. **A secret key you keep.** Set `WAYPOINT_SECRET_KEY` (`openssl rand -base64 32`) and keep a copy in your password manager. It encrypts the secrets Waypoint saves, such as each member’s mailbox access. Without it, the key is `./data/secret.key`: back it up with the database. To change it, put the old one in `WAYPOINT_SECRET_KEY_OLD` for one start, and keep it as long as you keep backups made with it.
4. **Rate limiting at the proxy** (optional). Waypoint caps how many requests it handles at once; the proxy can limit requests per address.
5. **Backups kept private.** They hold everything in your database, with saved secrets encrypted under your key.
6. **Updates.** Pull new images regularly.

## Everyday

- **Update:** `docker compose pull && docker compose up -d`, or let Watchtower do it. If you pinned a version, change the tag first. Database changes apply when the new version starts; take a backup first if you like to be careful.
- **Stop:** `docker compose down`. Data stays in `./data`.
- **Back up:** Settings → Backup & import → Backup → **Download a backup**, for either database, or `run.py backup`.
- **Health check:** `<WAYPOINT_PUBLIC_URL>/healthz` answers without signing in.

## Errors and logs

Waypoint sends nothing about itself anywhere: there is no error-reporting or analytics service. Its log (`docker logs waypoint`) has a line per request, with the path but never the query string, and the details of any error. An error the app shows carries a reference such as `reference 1a2b3c4d`; search the log for it. Credentials, query strings and the values a database error would quote are blanked.
