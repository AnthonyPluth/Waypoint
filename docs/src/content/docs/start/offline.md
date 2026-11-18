---
title: Offline
description: Which trips Waypoint saves on your device so they open with no connection, how they are locked and when each is cleared.
sidebar:
  order: 6
---

Waypoint can keep your upcoming trips on your phone or computer, so their confirmation codes, times and places are there at the airport and in the air. The copies are shown only to you and never sent anywhere else. In a browser they are always encrypted on the device and opened only with the device’s own check: Face ID, Touch ID, a fingerprint reader, Windows Hello, or the screen lock code where that is what the device offers. The iPhone app keeps its own copy, in files protected by the phone, and works differently (see [In the iPhone app](#in-the-iphone-app)).

## Setting it up

The first time a trip loads online on a device that isn’t set up, Waypoint offers **Keep this trip available offline** and asks for the device’s check. Choose **Not now** to leave it off; you can set it up later in **Settings → Offline & notifications → Set up offline access**. Until then nothing is saved. After that, every online load keeps the upcoming trips up to date with no prompt.

Setting up creates a passkey for this site, whose only job is unlocking the saved trips. Signing in still goes through your identity provider, and nothing about the passkey is sent to the server. On an iPhone, add Waypoint to the Home Screen first (Share → Add to Home Screen): Safari clears the stored data of sites you haven’t visited for a while, and an installed app is exempt.

The device must be able to make a passkey with the PRF extension from its built-in authenticator, with user verification. One that can’t never saves anything, and **Offline access** in Settings says why.

## In the iPhone app

The [iPhone app](/Waypoint/start/ios/) saves trips itself, with no passkey, no setup sheet and no Face ID. **Save my upcoming trips** is on by default: after a new install, and also after the app on a phone that already had it is updated to a version with this switch, so an updated app starts saving your trips without you choosing it. The first save happens when you open Waypoint online after signing in. To change it, open **Settings → Offline & notifications → Offline access**: the card says **On for this device** or **Off on this device**, names the saved trips and when they were saved, and has the one switch. Switching it off deletes the saved trips at once, with no confirmation, and it is the only way to delete them: there is no **Remove** button. Signing in again turns saving back on. The card says **Saving your trips…** while the app is fetching, **Couldn’t save the trips** when a save failed for any reason, including a phone that can’t reach the server (the older copy is kept, and saving is tried again each time you open Waypoint online), and, if the saved copy can’t be read, to switch saving off and on again to start afresh. An installed app too old to offer this shows no Offline access card.

The app fetches the trips with its own sign-in token when you open Waypoint after signing in, each time you return to the app, and when you switch saving on. A Waypoint with no sign-in of its own needs no token.

Where the copy is kept: in the app’s own private storage on the phone (its sandbox), as files protected by iOS Data Protection, so they are readable only while the phone is unlocked. Other apps and websites can’t read them. Waypoint adds no encryption of its own, and opening saved trips needs no Face ID: the phone’s lock is the gate. The files are included in the phone’s iCloud and computer backups when those are on, and the card says so. They are deleted at the moments listed under [When it is cleared](#when-it-is-cleared).

To open with no connection, the app also keeps a copy of your server’s public web app files (its pages, scripts, styles and fonts: code only, with no trip data, no cookies and no sign-in token), taken after a page loads online while saving is on. Without that copy the app has nothing to show offline, so it is kept up to date the same way and deleted together with the saved trips.

### With no connection, in the app

When the app is already showing Waypoint’s pages and then can’t reach your server (no connection, airplane mode, no signal or data, a DNS failure, a timeout or a dropped connection) and a trip and the app files are saved, it shows the saved copy instead of an error. There is nothing to unlock. Under a banner with the age of the copy, every saved trip opens as in a browser: editing and adding are off, every other page says it needs a connection, and live flight status is not shown. While it shows the copy, the app checks whether your server answers again (at most every 5 seconds, when the page tries to reach it, and so when you choose **Try again**) and goes back to the live pages as soon as it does. A certificate error or an error answered by the server never shows the saved copy, and with no trip saved nothing is served from the phone at all. Starting the app with no connection is different today: on a server that needs sign-in, the app first asks the server for its web session, and when that fails it shows an error and not the saved trips. That works only when the app is already running, or when that step can finish. On a Waypoint with no sign-in of its own there is no such step. This is tracked in #786. The no-connection copy has been tried against a server that can’t be reached, in the app’s tests, and not yet in airplane mode on a phone, and an airplane-mode launch is not promised.

### Starting with no connection

Opening the app with no connection, from a cold start in airplane mode for example, works the same way as losing the connection while it is open: if the app can’t reach the server to start its web session (it waits about 5 seconds), and trips and a copy of the web app’s files are saved for this server, it opens the saved trips instead of an error. Nothing is sent to that page: no cookie and no sign-in token. When the server answers again, the app gets a fresh web session and returns to the server. If the server answers that you are no longer signed in (401 or 403), the app signs you out and deletes the saved trips, and with no saved trips, or with an error that isn’t a lost connection (a certificate problem, say), it shows the same error as before. This path is covered by the app’s unit tests; it has not yet been confirmed on a phone in airplane mode.

## What is saved

Each time Waypoint loads online on a set-up device, it replaces the saved copies with these trips, together:

- every trip under way;
- every trip starting within the next 7 days;
- the next upcoming trip, however far out, if it isn’t one of those already.

It is a replacement, never a merge: a trip you can no longer see, or that has dropped out of those three, disappears at the next online load. At most 10 trips are kept (under way first, then those starting soonest, always keeping the next upcoming one). A trip you aren’t on is never included.

For each trip, Waypoint saves:

- the bookings, with confirmation codes, times and their time zones, places, seats, rooms, addresses, phone numbers and manage links;
- each booking’s [cost](/Waypoint/start/trips/#cost) and the trip’s total;
- the travellers’ display names;
- the cities of the trip’s airports: for each airport code on the trip’s own flights, its city name (for example `DEN` is Denver), so the saved copy can say where a flight goes without a connection. Only the flights you can see add to it, and a code Waypoint has no city for is left out;
- the coordinates of the airports your car rentals name as their pickup: for each airport code on the trip’s own car bookings, its latitude and longitude from Waypoint’s built-in airport table, so the iPhone app can tell when you arrive near a pickup that has only an airport code. These are public reference data about the airport, not your location, and a booking whose pickup is an address, or a code Waypoint doesn’t know, adds nothing;
- the confirmation message kept for each booking, as **View email** shows it, without images: subject, the sender’s domain and day, its text and its formatting. Offline, each image shows its description in place of the picture;
- in the iPhone app, the QR code of the [parking bookings](/Waypoint/start/trips/#the-gate-code-of-a-parking-booking) you can see on those trips (the owner’s decision, 2026-11-18). The picture is kept on the phone with the saved trips and the **Show QR code** dialog shows it when the app can’t reach your server. The saved-trips page itself has no **Show QR code** button yet; a later change (#850) adds a way to open it from there.

Never saved: loyalty and Known Traveler numbers, the QR code of a parking booking in a browser, live flight status, any trip that isn’t saved, and People, Settings, the review queue, mailboxes, AI settings and sign-in data.

## The reply, and the iPhone app

`GET /api/offline` is the one source of the saved copy. Its reply is `{"version": 1, "trips": [...]}`: `version` is the shape of the reply, 1 today. Each entry of `trips` is `{"trip": {...}, "messages": [...], "cities": {"DEN": "Denver", "GJT": "Grand Junction"}, "airports": [{"code": "DEN", "latitude": 39.86, "longitude": -104.67}]}`: the trip, the kept emails of its bookings, the `cities` map from each airport code of the trip’s flights to its city (`{}` for a trip with no flights), and `airports`, the `{code, latitude, longitude}` of each airport code named as the pickup of the trip’s car bookings (`[]` for a trip with none). Adding `cities` or `airports` did not change `version`: each is an additive field, and a reader that doesn’t use it ignores it, so an installed app that knows only version 1 keeps saving the reply as before. The iPhone app checks `version` before it saves a reply, and keeps the copy it already has when it doesn’t know the number. The browser’s own offline vault doesn’t read it today. The trips are those above, only the ones the signed-in person may see. For a request made with the iPhone app’s token, each trip also carries `codes`, a list of `{segment_id, type, data}` with the QR picture (base64) of the parking bookings the person can see on it that aren’t cancelled and have a code chosen; its parking segments keep their `gate_code` state. A browser session’s reply has no `codes`.

The [iPhone app](/Waypoint/start/ios/) reads the route with its own sign-in token (an OAuth access token of scope `app`, sent as `Authorization: Bearer …`), the same way it calls the rest of the API. An assistant’s token is never accepted: assistants can’t read this route, whatever their switches say, and a request with no sign-in is refused with 401.

## Checking before you travel

Upcoming and each trip’s page show an **Offline access** panel. A green **Saved for offline** pill means saving is set up and working; the other states say what is missing, such as **This trip isn’t saved on this device** or **Couldn’t save the trips on this device**, with **Try again** in a browser. In the iPhone app a failed save has no button: saving is tried again each time you open Waypoint online.

## Using it with no connection, in a browser

Open Waypoint offline and it shows **Saved trip is locked**. Unlock it once, with the device’s check, and every saved trip opens, read-only, under a banner with the age of the copy.

- Editing and adding are off, and every other page says it needs a connection.
- Live flight status is not shown; the check-in countdown and the plane on the route line keep working from the booked times and the device’s clock.
- Saving never asks for the device’s check; only opening the copy offline does. It locks again when you close the app and after 5 minutes without use.
- Online, Waypoint shows trips from the server as usual; the lock protects only the saved copy.

If the passkey is gone (a new device, or it was deleted), the saved trips can’t be unlocked and there is no recovery or passphrase option. Choose **Remove saved trips**, then set offline access up again while online.

## When it is cleared

Every saved copy is removed:

- when you sign out (in the iPhone app, also when its sign-in is no longer valid and when you choose **Use another Waypoint**);
- when any request answers that you’re no longer signed in or allowed (401 or 403) while you’re online;
- when you turn off **Save my upcoming trips on this device** or choose **Remove from this device** (in the iPhone app, only the switch **Save my upcoming trips** exists), in **Settings → Offline & notifications → Offline access**;
- 3 days after its trip ends, on the device’s clock. In a browser that happens even if you never open it again; in the iPhone app the trip is dropped the next time the app reads the copy (opening Waypoint, Settings or the saved trips) or saves a new one, so its files can stay on the phone until then;
- when the next online load no longer includes a trip, or finds you can’t see it;
- in the iPhone app, when the server address changes.

The switch applies to that device only. Turning it off clears every copy; **Remove from this device** also removes the key, so offline access is set up again from scratch. Settings shows what is saved on this device and when. In the iPhone app, the copy of the server’s web app files is deleted at the same moments as the trips, and also when no trip is left.

## What the lock protects against, in a browser

It protects against a copy or backup of the device’s stored data (which holds only ciphertext), other apps on the device, and other people using it who can’t pass its check. It doesn’t protect against whoever can pass the device’s own check (the screen lock code works in place of Face ID or a fingerprint), malware or a browser extension while the trip is unlocked, or someone watching the screen.

## How it is stored, in a browser

Copies live on the device you signed in on, in the browser’s Cache storage, as one encrypted entry per trip. Setting up makes an ECDH P-256 key pair in the browser. The private key is wrapped with AES-GCM under a key derived (HKDF) from the passkey’s PRF output; each online save encrypts to the public key, so saving never needs the authenticator. Unlocking asks the authenticator once and holds the unwrapped key in memory only. No key, PRF output or plaintext of a trip is stored. Beside the ciphertext sit a few small facts in the clear, because the app must read them without the device’s check: when the copies were saved, when each runs out, each saved trip’s number and whether saving is switched off.

The app itself opens offline too. The service worker keeps the app’s files (its pages, scripts and styles) in the same Cache storage, and once it is active the page hands it the files it loaded before the worker took control, so the first reload after a first visit doesn’t depend on the browser’s own HTTP cache still holding them. They are public build files and hold no trip data.

See also [Security](https://github.com/AnthonyPluth/Waypoint/blob/main/SECURITY.md).
