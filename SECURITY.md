# Security

Waypoint holds a household’s travel plans and identity-adjacent numbers (frequent-flyer, hotel-loyalty, TSA PreCheck and Global Entry numbers), and is designed to be given read-only access to a mailbox. Security reports are welcome and taken seriously.

## Reporting a vulnerability

Report it privately through GitHub: the repository’s **Security** tab → **Report a vulnerability** ([open a private report](https://github.com/AnthonyPluth/Waypoint/security/advisories/new)). Don’t open a public issue for a security problem. Include what you found, how to reproduce it, and the version (shown under Settings → Account). You’ll get an answer within a week, and a fix is released as soon as it’s ready.

## Supported versions

Only the latest release gets security fixes. Update with `docker compose pull && docker compose up -d`.

## Running Waypoint safely

See [Putting Waypoint on the internet](https://anthonypluth.github.io/Waypoint/start/docker/#putting-waypoint-on-the-internet): HTTPS in front, sign-in limited to your household, a `WAYPOINT_SECRET_KEY` you keep, and private backups.

## What Waypoint holds

**Mailboxes and email.** A member connects their Gmail with the `gmail.readonly` scope only; the refresh token is kept encrypted, and disconnecting revokes it at Google. A scan asks Google for the subject, sender and snippet of each message, fetches only the ones those say are worth reading, and reads them in memory in one module; message bodies are never logged and never sent anywhere but Gmail’s own API, and nothing is sent to a service run by the project. What a scan keeps is the booking’s fields and each message’s Gmail id; for mail it couldn’t read, the sender’s domain, the day and a keyed hash of the confirmation code it names, never the code. The message itself (subject, text up to a cap, markup rebuilt to a safe subset that can’t run or load anything, and the images it shows) is kept encrypted with `WAYPOINT_SECRET_KEY` only while a review item or a booking needs it, and deleted with them. Its images are downloaded once by the server, over https from public addresses only, with size and time limits and no cookies or identifying headers, so the browser never contacts a sender and a sender learns only that its images were fetched once. The message is shown inline in an isolated shadow root, rebuilt a second time from the app’s own allowlist under a Content-Security-Policy that allows no inline script and no remote images or fonts; a corpus of hostile markup is tested against both. The details are on the [Email scanning](https://anthonypluth.github.io/Waypoint/privacy/email-scanning/) page.

**The optional AI fallback** sends a message’s plain text, unredacted, to the household’s own Ollama server when the AI is set to Local (Ollama), and nowhere else: a hosted provider (OpenRouter) never receives email. OpenRouter is used only for the trip destination button, which sends the trip’s name and places with email addresses and numbers removed.

**Loyalty and Known Traveler numbers** and the other secrets Waypoint saves (such as mailbox tokens) are encrypted with `WAYPOINT_SECRET_KEY`, in backups too. Numbers are masked in the app until revealed, never in logs, notifications or hosted AI prompts, and never reachable from an AI assistant. Backups hold everything else in the database, so keep them private and keep the key.

**A signed-in person’s own device** may hold a copy of their upcoming trips (every trip under way or starting within 7 days and the next one after that, at most 10): bookings, confirmation codes, times, places, travellers’ display names and each booking’s stored confirmation message without its images, never a loyalty or Known Traveler number. It is built through the same visibility rules as every trip route, shown only to that person, never sent anywhere else, and cleared on sign-out, when a request answers 401 or 403, when saving is turned off, and 3 days after each trip ends. It is always encrypted on the device and opens only with the device’s own check (Face ID, Touch ID, Windows Hello or the screen lock): setup creates a passkey whose only job is unlocking, and the trips are encrypted to a key wrapped under the passkey’s PRF output. The device stores ciphertext, the public key, the wrapped private key, the credential id and the save times, never a key or plaintext. The lock protects against a copy of the device’s storage, other apps and other people using the device. It does not protect against whoever can pass the device’s own check, malware or an extension while the trips are unlocked, or someone watching the screen. See the [Offline](https://anthonypluth.github.io/Waypoint/start/offline/) page.

**AI assistants** (Claude and the like) connect to `/mcp` with OAuth as the member who approved them. An assistant sees what that member sees, never a loyalty or Known Traveler number, and changes nothing unless the household turned on “Let assistants change trips”. Mailboxes, AI settings, backup and restore, sign-in, the calendar feed and push devices are never reachable from it. Email text is reachable only on a connection the household granted “Read email text”, off by default and warned about in Settings; without it an assistant sees a review item only as the fields Waypoint parsed. A connection ends when its approver can no longer sign in. See the [AI assistants](https://anthonypluth.github.io/Waypoint/start/mcp/) page.

A report about a way around any of this is as serious as one about sign-in.

## One household, not one account per person

Waypoint has no accounts of its own. In local mode, everyone who can reach it has household access, which is why the Compose file binds the port to localhost. With OIDC sign-in, your provider decides who gets in, and everyone who gets in (`OIDC_ALLOWED_EMAILS`, `OIDC_ALLOWED_GROUPS`) can change settings and saved keys, download the backup (the household’s data and its encrypted secrets, mailbox tokens included) and restore one. Which trips a person sees follows who is on them, booked them or received a booking’s confirmation; that is about what the app shows, not a boundary between people with access to the server or its backups. That’s by design: it’s built for one household. Don’t let in anyone you wouldn’t trust with the household’s travel details, and don’t share one Waypoint between households.
