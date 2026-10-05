# Waypoint

[![Backend coverage](https://codecov.io/gh/AnthonyPluth/Waypoint/branch/main/graph/badge.svg?flag=backend)](https://app.codecov.io/gh/AnthonyPluth/Waypoint?flags%5B0%5D=backend)
[![Frontend coverage](https://codecov.io/gh/AnthonyPluth/Waypoint/branch/main/graph/badge.svg?flag=frontend)](https://app.codecov.io/gh/AnthonyPluth/Waypoint?flags%5B0%5D=frontend)

A self-hosted travel app for a household. Waypoint shows everyone the trips they’re on (flights, hotels, rental cars and their confirmation numbers) and keeps the family’s frequent-flyer, hotel-loyalty and TSA PreCheck numbers in one place, so anyone can book for anyone. Bookings are meant to arrive by scanning Gmail privately: read-only, searched on your server, bodies never stored.

**Status: early, Phase 0.** Today Waypoint offers OIDC sign-in (Authentik, Keycloak, Google, …), settings, and backups you can download and restore. The travel features come in later phases: people and loyalty IDs, trips and manual entry, Gmail scanning, vendor parsers, deep links and reminders, and optional AI suggestions.

## Quick start

```bash
git clone https://github.com/AnthonyPluth/waypoint.git
cd waypoint
cp .env.example .env      # set WAYPOINT_PUBLIC_URL, OIDC_ISSUER, OIDC_CLIENT_ID/SECRET, OIDC_ALLOWED_EMAILS
docker compose up -d
```

The image is `ghcr.io/anthonypluth/waypoint`. It uses SQLite in `./data`, or Postgres if you set `DATABASE_URL`. You see only the trips you’re on or booked, and one deployment serves one household.

## Documentation

https://anthonypluth.github.io/waypoint/ covers [installing with Docker](https://anthonypluth.github.io/waypoint/start/docker/), [configuration](https://anthonypluth.github.io/waypoint/reference/configuration/), [privacy](https://anthonypluth.github.io/waypoint/privacy/email-scanning/) and [contributing](https://anthonypluth.github.io/waypoint/contributing/development/). To report a vulnerability, see [SECURITY.md](SECURITY.md).

## License

[AGPL-3.0](LICENSE)
