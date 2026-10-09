---
title: Offline
description: What Waypoint saves on your device so your current trip opens with no connection, where it is kept, how it is locked and when it is cleared.
sidebar:
  order: 6
---

Waypoint can keep your **current trip** on your phone or computer, so its confirmation codes, times and places are there at the airport and in the air. The copy is saved by the app, shown only to you, never sent anywhere else, always encrypted on the device, and opened only with the device’s own check: Face ID, Touch ID, a fingerprint reader, Windows Hello, or the screen lock code where that is what the device offers. Nothing is ever saved in the clear.

## What is saved

The trip under way, or else the next trip starting within 7 days. Each time Waypoint loads online on a device that is set up, it asks the server for that one trip, which is built the same way as everything else you see, so a trip you aren’t on is never in it, and replaces the saved copy with it. It is a replacement, never a merge: a trip you can no longer see disappears from the device at the next online load.

Saved:

- the trip’s bookings: kind, provider, confirmation codes, flight numbers, times with their time zones, places, terminal, gate, seat, cabin, room, car class, addresses, phone numbers and manage links;
- the travellers’ display names;
- the confirmation message Waypoint keeps for each of the trip’s bookings, as **View email** shows it today: subject, the sender’s domain and day, its text and its cleaned-up formatting.

Not saved: loyalty and Known Traveler numbers (they need a connection, as always), any other trip, and People, Settings, the review queue, mailboxes, AI settings and sign-in data. Live flight status is not kept either.

The server answers this on `GET /api/offline`. It needs sign-in and an AI assistant over [MCP](/Waypoint/start/mcp/) can’t reach it.

## Where it is kept

On the device you signed in on, in the browser’s Cache storage, by one part of the app only, as ciphertext. Nothing else about the trip is kept in the browser’s storage. Three small facts are kept next to it in the clear because the app has to read them without asking for Face ID: when the copy was saved, when it runs out (three days after the trip ends) and whether saving is switched off on this device. Nothing about the trip itself is in them beyond that rough date.

An **installed home-screen app** keeps the copy far more reliably than a browser tab does on iPhone: Safari clears the stored data of sites you haven’t visited for a while, and an app added to the Home Screen is exempt from that. On an iPhone, add Waypoint to the Home Screen (Share → Add to Home Screen) before you rely on this.

## Opening it with no connection

Open Waypoint offline and it shows **Saved trip is locked**. Unlock it with the device’s check and it opens to the saved trip, read-only, under a banner such as “Offline. Saved 2 h ago.”

- Editing and adding are off, with the reason on screen.
- Live flight status is not shown. The check-in countdown and the plane on the route line keep working: they are worked out from the booked times and the device’s clock.
- Every other page says it needs a connection.
- With nothing saved, Waypoint says so.

## When it is cleared

The saved copy is removed:

- when you sign out, before the session ends;
- when any request answers that you’re no longer signed in or allowed (401 or 403) while you’re online;
- when you turn saving off for the device, or choose **Remove from this device**, in Settings → Data → **Offline access**;
- 3 days after the trip ends, on the device’s clock, even if you never open it again;
- when the next online load finds you have no current trip, or can’t see the one you had.

Settings shows what is saved on this device and when it was saved. The switch **Save my current trip on this device** turns saving off and on for that device only, and it is kept in the same store as the saved trip, nowhere else. Turning it off clears the copy; **Remove from this device** also removes the key, so offline access is set up again from scratch.

## Setting it up

The first time a trip loads while you’re online on a device that isn’t set up, Waypoint shows **Keep this trip available offline** and asks for the device’s check. Choose **Not now** to leave offline off on that device; you can set it up later in Settings → Data → **Set up offline access**. Until it is set up, nothing is saved. Once it is, every online load of Waypoint on that device keeps the current trip up to date, with no further prompt.

Setting up creates a passkey for this site. Its only job is unlocking the saved trip: signing in to Waypoint still goes through your identity provider, and nothing about the passkey is sent to the server. Waypoint asks for user verification, so the passkey can’t be used without the device’s check.

## Saving and unlocking

- **Saving never asks.** Once it is set up, opening Waypoint online saves a fresh encrypted copy in the background, with no Face ID prompt.
- **Opening it offline asks.** Offline, the trip shows **Saved trip is locked** with an **Unlock** button. A cancelled or failed unlock stays on that screen with **Try again** and never shows the trip.
- **It locks again** when you close the app and after 5 minutes without use.
- **Online, nothing changes.** While you’re online and signed in, Waypoint shows the trip from the server as usual. The lock protects only the saved offline copy.
- **A lost passkey.** On a new device, or if the passkey was deleted, the saved trip can’t be unlocked. The screen says so and offers **Remove saved trip**. Set offline access up again while online and Waypoint saves a fresh copy. There is no recovery of the old copy and no passphrase option.

**Remove from this device** in Settings deletes the copy and the key from the device.

## Devices that can’t do it

The device has to be able to make a passkey with the PRF extension from its built-in authenticator, with user verification. A device or browser that can’t never saves anything for offline use. Settings → Data → **Offline access** says why, and Waypoint works online as always. Waypoint can require the device’s own check but not biometrics specifically, so on a device whose check is a screen lock code, that code is accepted.

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
- Each online save encrypts the trip to the public key (a fresh ephemeral key, ECDH, HKDF, AES-GCM), which is why saving never needs the authenticator.
- Unlocking asks the authenticator for the PRF output, unwraps the private key and decrypts. The unwrapped key lives in memory only.
- What is stored on the device is the ciphertext, the public key, the wrapped private key, the passkey’s credential id and the nonces, and, in the clear, the time the copy was saved, the time it runs out and the saving switch. No key, no PRF output and no plaintext of the trip is stored.

See also [Security](https://github.com/AnthonyPluth/Waypoint/blob/main/SECURITY.md).
