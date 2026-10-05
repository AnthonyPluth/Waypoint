# Security

Waypoint holds your household’s travel plans and identity-adjacent numbers (frequent-flyer, hotel-loyalty and TSA PreCheck numbers), and is designed to be given read-only access to a mailbox. Security reports are welcome and taken seriously.

## Reporting a vulnerability

Please report it privately through GitHub: the repository’s **Security** tab → **Report a vulnerability**
([open a private report](https://github.com/AnthonyPluth/waypoint/security/advisories/new)). Don’t open
a public issue for a security problem. Include what you found, how to reproduce it, and the version (shown in
Settings). You’ll get an answer within a week, and a fix is released as soon as it’s ready.

## Supported versions

Only the latest release gets security fixes. Update with `docker compose pull && docker compose up -d`.

## Running Waypoint safely

See [Putting Waypoint on the internet](https://anthonypluth.github.io/waypoint/start/docker/#putting-waypoint-on-the-internet) in the docs: HTTPS in front, sign-in
limited to your household, a `WAYPOINT_SECRET_KEY`, and private backups.

## What Waypoint will hold

Members can connect their Gmail read-only (the `gmail.readonly` scope only; the refresh token is kept encrypted, and disconnecting revokes it at Google). Waypoint scans those mailboxes for bookings, keeping the promises on the
[Email scanning](https://anthonypluth.github.io/waypoint/privacy/email-scanning/) page: read-only mailbox access,
messages searched on Google’s side so only likely bookings are downloaded, bodies read in memory by one module and never stored, logged or sent anywhere but Gmail’s own API (a member can preview the text of a message from their own mailbox: it is fetched when they ask, shown to them alone and kept nowhere),
and nothing sent to a service run by the project. What a scan keeps is the booking’s fields, each message’s Gmail id and, for mail it couldn’t read,
the sender’s domain and the day. A report about a way around any of those is as serious as one about sign-in.

The secrets Waypoint saves (such as the refresh token for that mailbox access) are encrypted with
`WAYPOINT_SECRET_KEY`, and so are the copies in backups. Backups also hold everything else in the database, so keep them private.

## One household, not one account per person

Waypoint has no accounts of its own: sign-in decides who gets in, and everyone who gets in (`OIDC_ALLOWED_EMAILS`,
`OIDC_ALLOWED_GROUPS`) can change settings and saved keys, download the backup (which
holds the household’s data and its encrypted secrets, mailbox tokens included) and restore one. Which trips a person sees follows who is on them,
booked them or got a booking’s confirmation in their own mailbox; that is about what the app shows, not a boundary between people with access to the server or its backups.
That’s by design: it’s built for one household. Don’t let in anyone you wouldn’t trust with the household’s travel
details, and don’t share one Waypoint between households.
