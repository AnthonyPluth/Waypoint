---
title: Install with Docker
description: Start locally with no accounts or API keys, optionally add sign-in, move your data over and put it on the internet.
sidebar:
  order: 1
---

Waypoint starts locally with no account, sign-in provider or third-party credentials. The image holds Python, Waypoint’s dependencies, the web app and travel brand logos. It uses SQLite in `/data`, or Postgres if you set `DATABASE_URL`.

## First start

```bash
git clone https://github.com/AnthonyPluth/waypoint.git
cd waypoint
docker compose up -d
docker compose logs -f waypoint
```

Open `http://localhost:8765`. You can add household members and bookings by hand straight away. No `.env` file is needed. The database and its generated encryption key are saved in `./data`; keep that folder when updating or restarting.

The default Compose file publishes port 8765 only on localhost. Without sign-in, anyone who can reach the app sees the household’s trips and can change its settings. For other devices, explicitly change the published address and use a trusted private network or enable sign-in first. Do not publish an unauthenticated instance to the internet.

Gmail, AI suggestions, live flight status, connected assistants and push notifications are optional. [Brand logos](/Waypoint/start/logos/) and the basic trip map work without any connection.

The image is `ghcr.io/anthonypluth/waypoint:latest` (Intel/AMD and ARM). To stay on a version, set `image: ghcr.io/anthonypluth/waypoint:1.2` in `docker-compose.yml`.

## Optional sign-in

To use your OpenID Connect provider (Authentik, Authelia, Keycloak, Pocket ID, Google, Microsoft Entra, …), create an OIDC / OAuth2 application (a “confidential” client, authorization code flow):

| Setting | Value |
|---|---|
| Redirect URI | `<WAYPOINT_PUBLIC_URL>/auth/callback` |
| Post-logout redirect URI | `<WAYPOINT_PUBLIC_URL>/auth/signed-out` (optional) |
| Scopes | `openid email profile` (+ `groups` if you use group-based access) |
| ID token signing | RS256 (the usual default); PS256, ES256 and EdDSA work too |

Copy `.env.example` to `.env` and fill in `WAYPOINT_PUBLIC_URL`, `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` and `OIDC_ALLOWED_EMAILS` or `OIDC_ALLOWED_GROUPS`. Then restart with `docker compose up -d`. Setting `OIDC_ISSUER` enables sign-in; incomplete settings stop startup with a message in the logs. Leave the issuer empty to keep local mode.

Everyone who can sign in belongs to one household and shares settings and loyalty IDs. Authenticated members see the trips they travel on, book or receive; local mode shows the whole household’s trips.

**Settings** groups preferences into six cards: Account, Mail & review, Travel preferences, Offline & notifications, Connected assistants, and Backup & import. Open a card to see its controls. On wider screens, the section navigation stays beside the controls; **All settings** returns to the overview.

## Moving your data from another machine

1. On the old machine: Settings → Backup & import → Backup → **Download a backup** (or `poetry run python run.py backup`).
2. Start the container on the server, sign in, and go to Settings → Backup & import → Backup → **Restore**, choosing that file. (Or copy the file into `./data`, stop the running container, and run `docker compose run --rm waypoint python run.py restore /data/<file> --yes`.)

A backup holds saved secrets encrypted with your key: set the same `WAYPOINT_SECRET_KEY` on the server (or copy `secret.key` into its `./data`) before restoring. Restored under another key, they can’t be read: put the key the backup was made with in `WAYPOINT_SECRET_KEY_OLD` and restart once, and Waypoint re-encrypts them with the current key. Delete stray copies of the file once you’ve restored it.

A backup made before Waypoint’s database migrations were squashed into one can’t be restored by this version, and Waypoint says so. Restore it with the last release before the squash, then take a new backup and restore that one here. Backups made since restore as before, including into a newer version.

The same goes for updating in place: a Waypoint that has not been started since before the squash must first be updated to the last release before the squash and started once, then updated to this version. Starting this version on such a database stops with a message saying so, and changes nothing.

## Using Postgres (optional)

Set `DATABASE_URL` in `.env` (e.g. `postgresql://waypoint:password@db-host:5432/waypoint`) and restart. Waypoint creates its tables on first start and applies any schema migrations each time a new version starts. To bring your data along, restore a backup into it as above. There’s a commented-out `db` service in `docker-compose.yml` if you want Postgres alongside Waypoint. Without `DATABASE_URL`, Waypoint keeps using its built-in database in `./data`.

## Behind a reverse proxy

Run Waypoint behind a reverse proxy that terminates HTTPS (Caddy, Traefik, nginx), and set `WAYPOINT_PUBLIC_URL` to the public `https://` address. If the proxy runs on the same machine, publish the port on localhost only, so nothing reaches Waypoint around it:

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

Already sign in through a proxy (Authelia forward-auth, Cloudflare Access, oauth2-proxy)? Leave `OIDC_ISSUER` empty and set `WAYPOINT_ALLOW_NO_AUTH=1` instead, and don’t expose port 8765 except through that proxy.

## Caching behind Cloudflare or another CDN

Waypoint sets its own cache headers, so a CDN needs no rules of its own: the web app's files under `/assets/` are cached for a year (their names change with their content), and the fonts and icons for a week. Leave the CDN on its default of respecting the origin's headers, and turn on Brotli and HTTP/3 if it offers them.

Never cache the rest. The page at `/` carries a fresh security nonce on every request, and `/api/`, `/auth/`, `/oauth/` and `/mcp` answer with one person's private data, so a "cache everything" rule would break the first and leak the others. Keep Cloudflare's Rocket Loader off: it rewrites scripts that Waypoint's security policy only allows by their nonce.

## Putting Waypoint on the internet

Waypoint is built to be reachable from anywhere, as long as it’s set up like this:

1. **HTTPS in front.** A reverse proxy with a certificate, or Tailscale Funnel, with `WAYPOINT_PUBLIC_URL` set to that `https://` address. Waypoint refuses to start with a plain `http://` internet address.
2. **Sign-in limited to your household.** Use `OIDC_ALLOWED_EMAILS` and/or `OIDC_ALLOWED_GROUPS`; avoid `OIDC_ALLOW_ANY_USER`. Turn on two-factor sign-in at your identity provider: it guards everything behind it. Everyone you let in shares one Waypoint and can change its settings, download the backup and restore one (see [SECURITY.md](https://github.com/AnthonyPluth/waypoint/blob/main/SECURITY.md)).
3. **A secret key.** Set `WAYPOINT_SECRET_KEY` (`openssl rand -base64 32`) and keep a copy in your password manager. It encrypts the secrets Waypoint saves, such as the mailbox access planned for [email scanning](/Waypoint/privacy/email-scanning/). Without it, the key is `./data/secret.key`: back it up with the database. When you change it, put the old one in `WAYPOINT_SECRET_KEY_OLD` for one start, and keep it as long as you keep backups made with it.
4. **Rate limiting at the proxy** (optional but good): Waypoint caps how many requests it handles at once, and the proxy can limit requests per address.
5. **Backups kept private.** They hold everything in your database, and saved secrets encrypted with your `WAYPOINT_SECRET_KEY`.
6. **Updates.** Pull new images regularly.

## Everyday

- Update to the newest image: `docker compose pull && docker compose up -d` (or let Watchtower do it). If you pinned a version, change the tag first. Database changes are applied automatically when the new version starts; take a backup first if you like to be careful.
- Stop: `docker compose down` (data stays in `./data`).
- Back up: Settings → Backup & import → Backup → Download a backup (works for either database), or `run.py backup`.
- Health check: `<WAYPOINT_PUBLIC_URL>/healthz` answers without signing in.

## Errors and logs

Waypoint sends nothing about itself anywhere: there's no error-reporting or analytics service. Its log (`docker logs waypoint`) has a line per request (the path, never the query string) and the details of any error. An error the app shows has a reference (`reference 1a2b3c4d`); search the log for it. Credentials, query strings and the values a database error would quote are blanked in the log.

## Notes about sign-in

- Only people in `OIDC_ALLOWED_EMAILS` / `OIDC_ALLOWED_GROUPS` get in, even if your provider lets others sign in.
- A session ends after 14 days without using Waypoint (`WAYPOINT_SESSION_DAYS`); using it keeps you signed in, for up to 90 days after you signed in. If you’re let in by `OIDC_ALLOWED_GROUPS` rather than by email, it ends 14 days after signing in, so leaving the group takes effect.
- Someone who isn’t allowed in sees that, with a button to sign in with another account; the log says who was refused.
- Waypoint answers only to addresses that are yours: `WAYPOINT_PUBLIC_URL`’s host, local IPs, `*.local`, plain names like `nas`, and Tailscale names. Add others with `WAYPOINT_ALLOWED_HOSTS` ([Configuration](/Waypoint/reference/configuration/#advanced)).
- Use `https://` for `WAYPOINT_PUBLIC_URL`: session cookies are then marked Secure. On an internet address Waypoint requires it.
