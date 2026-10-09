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

See [Putting Waypoint on the internet](https://anthonypluth.github.io/Waypoint/start/docker/#putting-waypoint-on-the-internet) in the docs: HTTPS in front, sign-in
limited to your household, a `WAYPOINT_SECRET_KEY`, and private backups.

## What Waypoint will hold

Members can connect their Gmail read-only (the `gmail.readonly` scope only; the refresh token is kept encrypted, and disconnecting revokes it at Google). Waypoint scans those mailboxes for bookings, keeping the promises on the
[Email scanning](https://anthonypluth.github.io/Waypoint/privacy/email-scanning/) page: read-only mailbox access,
messages searched on Google’s side so only likely bookings are downloaded, bodies read in memory by one module and never logged or sent anywhere but Gmail’s own API,
and nothing sent to a service run by the project. What a scan keeps is the booking’s fields, each message’s Gmail id and, for mail it couldn’t read,
the sender’s domain and the day. It also keeps the message itself (its subject, text and markup cleaned of anything that loads or runs), encrypted with `WAYPOINT_SECRET_KEY` like the mailbox token, only while something needs it: a review item waiting on it, or a booking made from it. It is deleted when the item is dismissed (unless a booking was made from it), when the last booking made from it is removed and when the mailbox is disconnected. Anyone who can see the item or the booking can read it, no one else can, and an AI assistant over MCP can’t. A backup holds it, still encrypted, so keep backups private and keep the key. A report about a way around any of those is as serious as one about sign-in.

The secrets Waypoint saves (such as the refresh token for that mailbox access) are encrypted with
`WAYPOINT_SECRET_KEY`, and so are the copies in backups. Backups also hold everything else in the database, so keep them private.

The saved offline trip is always encrypted on the device it is saved on, and opens only with that device’s own check (Face ID, Touch ID, a fingerprint reader, Windows Hello, or the screen lock). Setting up creates a passkey for the site whose only job is unlocking (sign-in stays OIDC), with user verification required, and an ECDH P-256 key pair made in the browser. The private key is wrapped with AES-GCM under a key derived (HKDF, fixed versioned label) from the passkey’s WebAuthn PRF output; each online save encrypts to the public key, so saving never prompts and only unlocking asks for the authenticator. The device stores the ciphertext, the public key, the wrapped private key, the passkey’s credential id and nonces, and nothing else: never a key, a PRF output or plaintext. The unwrapped key lives in memory only, and the trip locks again when the app is closed and after 5 minutes idle. A device that can’t make a PRF passkey from its built-in authenticator saves nothing offline, and there is no passphrase fallback. `frontend/src/lib/offline-vault.ts` is the only module allowed to use the Cache API (an ESLint rule enforces it).

The lock protects against a copy of the device’s stored data, a backup of the device, other apps and other people using the device. It does not protect against whoever can pass the device’s own check (the phone’s screen lock code is the fallback for Face ID on iPhone and Android), malware or a browser extension while the trip is unlocked, someone watching the screen, or the signed-in app while online, which it doesn’t lock. A lost passkey means the saved copy can’t be opened and is replaced by setting up again online; nothing recovers it. See the [Offline](https://anthonypluth.github.io/Waypoint/start/offline/) page.

An AI assistant (Claude and the like) can connect to Waypoint's `/mcp` endpoint with OAuth, as the member who approved it: it sees what they see, never a loyalty or Known Traveler number (nothing under them is reachable from it), and changes nothing unless the household turned on "Let assistants change trips". Mailboxes, email content, the review queue, AI settings, backup and restore, sign-in, the calendar feed and push devices are never reachable from it, and a connection ends when its approver can no longer sign in. See the [AI assistants](https://anthonypluth.github.io/Waypoint/start/mcp/) page.

## One household, not one account per person

Waypoint has no accounts of its own: sign-in decides who gets in, and everyone who gets in (`OIDC_ALLOWED_EMAILS`,
`OIDC_ALLOWED_GROUPS`) can change settings and saved keys, download the backup (which
holds the household’s data and its encrypted secrets, mailbox tokens included) and restore one. Which trips a person sees follows who is on them,
booked them or got a booking’s confirmation in their own mailbox; that is about what the app shows, not a boundary between people with access to the server or its backups.
That’s by design: it’s built for one household. Don’t let in anyone you wouldn’t trust with the household’s travel
details, and don’t share one Waypoint between households.
