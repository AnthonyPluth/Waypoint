---
title: Offline
description: Which trips Waypoint saves on your device so they open with no connection, where they are kept, how they are locked and when each is cleared.
sidebar:
  order: 6
---

Waypoint can keep your **upcoming trips** on your phone or computer, so their confirmation codes, times and places are there at the airport and in the air. The copies are saved by the app, shown only to you, never sent anywhere else, always encrypted on the device, and opened only with the device’s own check: Face ID, Touch ID, a fingerprint reader, Windows Hello, or the screen lock code where that is what the device offers. Nothing is ever saved in the clear.

## What is saved

Three kinds of trip, together:

- every trip **under way** (it has started and not ended);
- every trip **starting within the next 7 days**;
- the **next upcoming trip, however far out it is**, if it isn’t one of those already. A trip months away is saved as soon as it is the next one, so you can look it up on the way to the airport even if you never opened it in the last week.

Each time Waypoint loads online on a device that is set up, it asks the server for those trips, which are built the same way as everything else you see, so a trip you aren’t on is never in them, and replaces the saved copies with them. It is a replacement, never a merge: a trip you can no longer see, or one that is no longer in those three kinds, disappears from the device at the next online load. To keep the copy small, at most 10 trips are saved (trips under way first, then those starting soonest, always keeping the next upcoming trip), and each trip’s emails are saved only for the trips that are saved.

Saved:

- the trip’s bookings: kind, provider, confirmation codes, flight numbers, times with their time zones, places, terminal, gate, seat, cabin, room, car class, addresses, phone numbers and manage links;
- each booking’s [cost](/Waypoint/start/trips/#cost) and the trip’s total, which anyone who can see the trip already sees;
- the travellers’ display names;
- the confirmation message Waypoint keeps for each of the trip’s bookings, as **View email** shows it, except for its images: subject, the sender’s domain and day, its text and its formatting. The images stay on the server, so offline an email shows its text and layout, with each image’s description in place of the picture.

Not saved: loyalty and Known Traveler numbers (they need a connection, as always), the QR code of a [parking booking](/Waypoint/start/trips/#the-gate-code-of-a-parking-booking) (a gate credential is only ever shown online), any trip that isn’t saved, and People, Settings, the review queue, mailboxes, AI settings and sign-in data. Live flight status is not kept either.

The server answers this on `GET /api/offline`. It needs sign-in and an AI assistant over [MCP](/Waypoint/start/mcp/) can’t reach it.

## Where it is kept

On the device you signed in on, in the browser’s Cache storage, by one part of the app only, as ciphertext. Nothing else about the trip is kept in the browser’s storage. Each saved trip is its own encrypted entry. A few small facts are kept next to them in the clear because the app has to read them without asking for Face ID: when the copies were saved, when each trip’s copy runs out (three days after that trip ends), each saved trip’s number and whether saving is switched off on this device. Nothing about a trip itself is in them beyond that number and a rough date.

An **installed home-screen app** keeps the copy far more reliably than a browser tab does on iPhone: Safari clears the stored data of sites you haven’t visited for a while, and an app added to the Home Screen is exempt from that. On an iPhone, add Waypoint to the Home Screen (Share → Add to Home Screen) before you rely on this.

## Seeing it before you rely on it

Upcoming and each trip’s page show a small **Offline access** panel, so you can check before you board:

- **Saved on this device · updated 2 h ago** says the copy is there and how fresh it is. On Upcoming it also names every saved trip. On a trip that is saved, it adds **also saved:** with the others.
- **This trip isn’t saved on this device** appears on a trip that is not among the saved ones, such as a trip months away that isn’t the next one yet, with the trips that are saved and the rule above. It never says nothing is saved while other trips are.
- **Nothing is saved yet** appears only when no trip is saved at all.
- **Set up offline access** appears when the device isn’t set up; it opens the same sheet as Settings. A device that can’t do it says so and why, and a saved trip that can’t be read links to Settings to remove it.
- **Couldn’t save the trips on this device** appears when the last save failed, with **Try again** and the age of the copy still on the device.

The saved trips’ names are known only while the app is open: they aren’t written to the device in the clear, so after a reload the panel counts the saved trips (and still tells a saved trip from one that isn’t) until the next online save names them again.

## Opening it with no connection

Open Waypoint offline and it shows **Saved trip is locked**. Unlock it once, with the device’s check, and every saved trip opens: with one saved it opens straight to it, read-only, under a banner such as “Offline. Saved 2 h ago.”; with several, Upcoming lists them to choose from, and a trip’s own page opens that trip, or says that it isn’t saved and lists the ones that are.

- Editing and adding are off, with the reason on screen.
- Live flight status is not shown. The check-in countdown and the plane on the route line keep working: they are worked out from the booked times and the device’s clock.
- Every other page says it needs a connection.
- With nothing saved, Waypoint says so.

## When it is cleared

Every saved copy is removed:

- when you sign out, before the session ends;
- when any request answers that you’re no longer signed in or allowed (401 or 403) while you’re online;
- when you turn saving off for the device, or choose **Remove from this device**, in Settings → Offline & notifications → **Offline access**;
- 3 days after its trip ends, on the device’s clock, even if you never open it again: each trip’s copy goes on its own day and the others stay;
- when the next online load no longer includes a trip, or finds you can’t see it.

Settings shows what is saved on this device and when it was saved. The switch **Save my upcoming trips on this device** turns saving off and on for that device only, and it is kept in the same store as the saved trip, nowhere else. Turning it off clears every copy; **Remove from this device** also removes the key, so offline access is set up again from scratch.

## Setting it up

The first time a trip loads while you’re online on a device that isn’t set up, Waypoint shows **Keep this trip available offline** (it keeps your other upcoming trips too) and asks for the device’s check. Choose **Not now** to leave offline off on that device; you can set it up later in Settings → Offline & notifications → **Set up offline access**. Until it is set up, nothing is saved. Once it is, every online load of Waypoint on that device keeps the upcoming trips up to date, with no further prompt.

Setting up creates a passkey for this site. Its only job is unlocking the saved trips: signing in to Waypoint still goes through your identity provider, and nothing about the passkey is sent to the server. Waypoint asks for user verification, so the passkey can’t be used without the device’s check.

## Saving and unlocking

- **Saving never asks.** Once it is set up, opening Waypoint online saves a fresh encrypted copy in the background, with no Face ID prompt.
- **Opening it offline asks.** Offline, the trip shows **Saved trip is locked** with an **Unlock** button. A cancelled or failed unlock stays on that screen with **Try again** and never shows the trip.
- **It locks again** when you close the app and after 5 minutes without use.
- **Online, nothing changes.** While you’re online and signed in, Waypoint shows the trip from the server as usual. The lock protects only the saved offline copy.
- **A lost passkey.** On a new device, or if the passkey was deleted, the saved trip can’t be unlocked. The screen says so and offers **Remove saved trips**. Set offline access up again while online and Waypoint saves a fresh copy. There is no recovery of the old copy and no passphrase option.

**Remove from this device** in Settings deletes the copy and the key from the device.

## Devices that can’t do it

The device has to be able to make a passkey with the PRF extension from its built-in authenticator, with user verification. A device or browser that can’t never saves anything for offline use. Settings → Offline & notifications → **Offline access** says why, and Waypoint works online as always. Waypoint can require the device’s own check but not biometrics specifically, so on a device whose check is a screen lock code, that code is accepted.

## What the lock protects against, and what it doesn’t

It protects against:

- a copy of the device’s stored data, or a backup of the device, which holds only ciphertext;
- other apps on the device;
- other people using the device who can’t pass its check.

It doesn’t protect against:

- whoever can pass the device’s own check. On an iPhone and on Android the screen lock code works in place of Face ID or a fingerprint;
- malware, or a browser extension, while the trip is unlocked;
- someone watching the screen;
- the signed-in app while you’re online, which this lock doesn’t cover.

## How it works

For the curious, and for anyone who wants to check it against the code (`frontend/src/lib/offline-vault.ts`):

- Setting up makes an ECDH P-256 key pair in the browser. The public key is stored in the clear. The private key is wrapped with AES-GCM under a key derived (HKDF) from the passkey’s PRF output, with a fixed, versioned label.
- Each online save encrypts each trip to the public key (a fresh ephemeral key, ECDH, HKDF, AES-GCM), which is why saving never needs the authenticator.
- Unlocking asks the authenticator once for the PRF output, unwraps the private key and decrypts every saved trip. The unwrapped key lives in memory only.
- What is stored on the device is the ciphertext, the public key, the wrapped private key, the passkey’s credential id and the nonces, and, in the clear, the time the copies were saved, the time each trip’s copy runs out, each saved trip’s number and the saving switch. No key, no PRF output and no plaintext of a trip is stored.

See also [Security](https://github.com/AnthonyPluth/Waypoint/blob/main/SECURITY.md).
