---
title: Install with Docker
description: Register Waypoint with your sign-in provider, start it, move your data over and put it on the internet.
sidebar:
  order: 1
---

Waypoint signs you in through your OpenID Connect provider (Authentik, Authelia, Keycloak, Pocket ID, Google, Microsoft Entra, …). The image holds Python, Waypoint’s dependencies and Waypoint itself. It uses SQLite in `/data`, or Postgres if you set `DATABASE_URL`.

:::note
Waypoint is in an early phase: today it offers sign-in, settings and backups. Installing it now gets you the foundation the travel features will be added to.
:::

## 1. Register Waypoint with your provider

Create an OIDC / OAuth2 application (a “confidential” client, authorization code flow):

| Setting | Value |
|---|---|
| Redirect URI | `<WAYPOINT_PUBLIC_URL>/auth/callback` |
| Post-logout redirect URI | `<WAYPOINT_PUBLIC_URL>/auth/signed-out` (optional) |
| Scopes | `openid email profile` (+ `groups` if you use group-based access) |
| ID token signing | RS256 (the usual default); PS256, ES256 and EdDSA work too |

Note the issuer URL, client ID and client secret.

## 2. First start

```bash
git clone https://github.com/AnthonyPluth/waypoint.git
cd waypoint
cp .env.example .env        # fill in WAYPOINT_PUBLIC_URL, OIDC_* and OIDC_ALLOWED_EMAILS
docker compose up -d
docker compose logs -f waypoint
```

The image is `ghcr.io/anthonypluth/waypoint:latest` (Intel/AMD and ARM). To stay on a version, set `image: ghcr.io/anthonypluth/waypoint:1.2` in `docker-compose.yml`.

Then open `WAYPOINT_PUBLIC_URL`. You’re sent to your provider to sign in, then back to Waypoint. If a setting is missing, the container stops with a message saying which one (see the logs).

## Moving your data from another machine

1. On the old machine: Settings → Data → Backup → **Download a backup** (or `poetry run python run.py backup`).
2. Start the container on the server, sign in, and go to Settings → Data → Backup → **Restore**, choosing that file. (Or copy the file into `./data`, stop the running container, and run `docker compose run --rm waypoint python run.py restore /data/<file> --yes`.)

A backup holds saved secrets encrypted with your key: set the same `WAYPOINT_SECRET_KEY` on the server (or copy `secret.key` into its `./data`) before restoring. Restored under another key, they can’t be read: put the key the backup was made with in `WAYPOINT_SECRET_KEY_OLD` and restart once, and Waypoint re-encrypts them with the current key. Delete stray copies of the file once you’ve restored it.

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

## Putting Waypoint on the internet

Waypoint is built to be reachable from anywhere, as long as it’s set up like this:

1. **HTTPS in front.** A reverse proxy with a certificate, or Tailscale Funnel, with `WAYPOINT_PUBLIC_URL` set to that `https://` address. Waypoint refuses to start with a plain `http://` internet address.
2. **Sign-in limited to your household.** Use `OIDC_ALLOWED_EMAILS` and/or `OIDC_ALLOWED_GROUPS`; avoid `OIDC_ALLOW_ANY_USER`. Turn on two-factor sign-in at your identity provider: it guards everything behind it. Everyone you let in shares one Waypoint and can change its settings, download the backup and restore one (see [SECURITY.md](https://github.com/AnthonyPluth/waypoint/blob/main/SECURITY.md)).
3. **A secret key.** Set `WAYPOINT_SECRET_KEY` (`openssl rand -base64 32`) and keep a copy in your password manager. It encrypts the secrets Waypoint saves, such as the mailbox access planned for [email scanning](/waypoint/privacy/email-scanning/). Without it, the key is `./data/secret.key`: back it up with the database. When you change it, put the old one in `WAYPOINT_SECRET_KEY_OLD` for one start, and keep it as long as you keep backups made with it.
4. **Rate limiting at the proxy** (optional but good): Waypoint caps how many requests it handles at once, and the proxy can limit requests per address.
5. **Backups kept private.** They hold everything in your database, and saved secrets encrypted with your `WAYPOINT_SECRET_KEY`.
6. **Updates.** Pull new images regularly.

## Everyday

- Update to the newest image: `docker compose pull && docker compose up -d` (or let Watchtower do it). If you pinned a version, change the tag first. Database changes are applied automatically when the new version starts; take a backup first if you like to be careful.
- Stop: `docker compose down` (data stays in `./data`).
- Back up: Settings → Data → Backup → Download a backup (works for either database), or `run.py backup`.
- Health check: `<WAYPOINT_PUBLIC_URL>/healthz` answers without signing in.

## Error reports (optional)

Set `SENTRY_DSN` (Sentry → your project → Settings → Client Keys) and Waypoint sends its errors to your Sentry project, from the server and from the web app, tagged with the version. Without it, nothing is sent anywhere.

- A report has the error, its stack trace and the page or API path. It never has request bodies, cookies, headers or query strings.
- `SENTRY_BROWSER_DSN` sends the web app’s reports to a separate Sentry project; `WAYPOINT_SENTRY_BROWSER=0` keeps the web app from sending any.
- `SENTRY_ENVIRONMENT` names the environment (default `production`).
- Waypoint never records sessions or sends replays. If `SENTRY_REPLAY_SAMPLE_RATE` or `SENTRY_REPLAY_ON_ERROR_SAMPLE_RATE` is still set, Waypoint warns at startup that it’s no longer read.

## Notes

- Only people in `OIDC_ALLOWED_EMAILS` / `OIDC_ALLOWED_GROUPS` get in, even if your provider lets others sign in.
- A session ends after 14 days without using Waypoint (`WAYPOINT_SESSION_DAYS`); using it keeps you signed in, for up to 90 days after you signed in. If you’re let in by `OIDC_ALLOWED_GROUPS` rather than by email, it ends 14 days after signing in, so leaving the group takes effect.
- Someone who isn’t allowed in sees that, with a button to sign in with another account; the log says who was refused.
- Waypoint answers only to addresses that are yours: `WAYPOINT_PUBLIC_URL`’s host, local IPs, `*.local`, plain names like `nas`, and Tailscale names. Add others with `WAYPOINT_ALLOWED_HOSTS` ([Configuration](/waypoint/reference/configuration/#advanced)).
- Use `https://` for `WAYPOINT_PUBLIC_URL`: session cookies are then marked Secure. On an internet address Waypoint requires it.
