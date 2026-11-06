# Waypoint push relay

A small Cloudflare Worker that holds the Apple Push Notification key so a self-hosted Waypoint can wake the iPhone app. Apple only accepts pushes signed with the app publisher's key, which self-hosters can't have; this relay is the one place that does.

## What it knows and sends

- It stores, per phone: the Apple device token, whether it is a production or development build, a random device id, and a hash of a random secret. Nothing else: no server address, no account, no trip data.
- A wake-up carries no content from the caller. The relay sends one of two fixed payloads: an alert reading "Open Waypoint to see an update." (the app's notification extension then replaces it with the real text, fetched from the person's own server), or a silent background push. Only an optional `collapse_id` (letters, digits, dashes) is passed on.
- The app registers its token with the relay, then gives the device id and secret to its own Waypoint server. That server calls the relay when something is due. Whoever holds the secret can wake that one phone, and nothing more.

## API

| Call | Auth | Does |
| --- | --- | --- |
| `POST /v1/devices` `{apns_token, environment?}` | none; limited to 10 a minute per address | Registers a phone; returns `{device_id, secret}`. Registering the same token again keeps the id and replaces the secret. |
| `POST /v1/devices/{id}/wake` `{kind?: "alert" \| "background", collapse_id?}` | `Authorization: Bearer <secret>`; limited to 20 a minute per device | Sends the fixed push. `410` means Apple no longer knows the device, and the relay has forgotten it. |
| `DELETE /v1/devices/{id}` | `Authorization: Bearer <secret>` | Forgets the phone. |
| `GET /healthz` | none | `{ok: true}` |

## Deploying

1. In the Apple developer account, create an APNs key (Keys → Apns) and note its Key ID and your Team ID. Download the `.p8` once.
2. `npm install`, then `npx wrangler kv namespace create DEVICES` and put the id in `wrangler.toml`.
3. Set `APNS_TOPIC` in `wrangler.toml` to the app's bundle identifier.
4. `npx wrangler secret put APNS_KEY` (paste the whole `.p8`), `APNS_KEY_ID`, `APNS_TEAM_ID`. Never commit the key.
5. `npm run deploy`, and give self-hosters the Worker's address.

## Tests

`npm test` runs `test/relay.test.js` with Node's built-in runner: registration, secrets, fixed payloads, rate limits, Apple's replies and the signed provider token (verified with the public key).

## Not verified

- Sending to Apple from a Worker: the code uses `fetch` to `api.push.apple.com`, which needs HTTP/2. Tests use a fake. Try it with a real device on the sandbox (`environment: "development"`) before relying on it.
- The `ratelimit` bindings in `wrangler.toml` follow Cloudflare's documented shape; `wrangler deploy` hasn't been run.
- Workers KV is eventually consistent: a registration can take a few seconds (Cloudflare says 60 seconds or more) to be seen from another location, so a replaced secret or a deleted device can still be accepted elsewhere for that long, and two registrations of one new token made at once from different locations can each get an id. Making these strictly ordered needs a Durable Object per device; not built yet.
- The rate limits are per Cloudflare location and approximate, not global. Registration also has a global limit of 60 a minute, and records expire after 180 days (the app registers again when it opens), so a flood of made-up tokens cannot fill storage for good; it can still use up a free account's daily KV writes.
- Apple's `410` carries the time the token was last known invalid; the relay keeps a registration newer than that.
