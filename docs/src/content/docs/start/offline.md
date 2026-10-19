---
title: Offline
description: Which trips Waypoint saves on your device so they open with no connection, how they are locked and when each is cleared.
sidebar:
  order: 6
---

Waypoint can keep your upcoming trips on your phone or computer, so their confirmation codes, times and places are there at the airport and in the air. The copies are shown only to you, never sent anywhere else, always encrypted on the device, and opened only with the device’s own check: Face ID, Touch ID, a fingerprint reader, Windows Hello, or the screen lock code where that is what the device offers. Nothing is saved in the clear.

## Setting it up

The first time a trip loads online on a device that isn’t set up, Waypoint offers **Keep this trip available offline** and asks for the device’s check. Choose **Not now** to leave it off; you can set it up later in **Settings → Offline & notifications → Set up offline access**. Until then nothing is saved. After that, every online load keeps the upcoming trips up to date with no prompt.

Setting up creates a passkey for this site, whose only job is unlocking the saved trips. Signing in still goes through your identity provider, and nothing about the passkey is sent to the server. On an iPhone, add Waypoint to the Home Screen first (Share → Add to Home Screen): Safari clears the stored data of sites you haven’t visited for a while, and an installed app is exempt.

The device must be able to make a passkey with the PRF extension from its built-in authenticator, with user verification. One that can’t never saves anything, and **Offline access** in Settings says why.

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
- the confirmation message kept for each booking, as **View email** shows it, without images: subject, the sender’s domain and day, its text and its formatting. Offline, each image shows its description in place of the picture.

Never saved: loyalty and Known Traveler numbers, the QR code of a [parking booking](/Waypoint/start/trips/#the-gate-code-of-a-parking-booking), live flight status, any trip that isn’t saved, and People, Settings, the review queue, mailboxes, AI settings and sign-in data.

## Checking before you travel

Upcoming and each trip’s page show an **Offline access** panel. A green **Saved for offline** pill means saving is set up and working; the other states say what is missing, such as **This trip isn’t saved on this device** or **Couldn’t save the trips on this device**, with **Try again**.

## Using it with no connection

Open Waypoint offline and it shows **Saved trip is locked**. Unlock it once, with the device’s check, and every saved trip opens, read-only, under a banner with the age of the copy.

- Editing and adding are off, and every other page says it needs a connection.
- Live flight status is not shown; the check-in countdown and the plane on the route line keep working from the booked times and the device’s clock.
- Saving never asks for the device’s check; only opening the copy offline does. It locks again when you close the app and after 5 minutes without use.
- Online, Waypoint shows trips from the server as usual; the lock protects only the saved copy.

If the passkey is gone (a new device, or it was deleted), the saved trips can’t be unlocked and there is no recovery or passphrase option. Choose **Remove saved trips**, then set offline access up again while online.

## When it is cleared

Every saved copy is removed:

- when you sign out;
- when any request answers that you’re no longer signed in or allowed (401 or 403) while you’re online;
- when you turn off **Save my upcoming trips on this device** or choose **Remove from this device**, in **Settings → Offline & notifications → Offline access**;
- 3 days after its trip ends, on the device’s clock, even if you never open it again;
- when the next online load no longer includes a trip, or finds you can’t see it.

The switch applies to that device only. Turning it off clears every copy; **Remove from this device** also removes the key, so offline access is set up again from scratch. Settings shows what is saved on this device and when.

## What the lock protects against

It protects against a copy or backup of the device’s stored data (which holds only ciphertext), other apps on the device, and other people using it who can’t pass its check. It doesn’t protect against whoever can pass the device’s own check (the screen lock code works in place of Face ID or a fingerprint), malware or a browser extension while the trip is unlocked, or someone watching the screen.

## How it is stored

Copies live on the device you signed in on, in the browser’s Cache storage, as one encrypted entry per trip. Setting up makes an ECDH P-256 key pair in the browser. The private key is wrapped with AES-GCM under a key derived (HKDF) from the passkey’s PRF output; each online save encrypts to the public key, so saving never needs the authenticator. Unlocking asks the authenticator once and holds the unwrapped key in memory only. No key, PRF output or plaintext of a trip is stored. Beside the ciphertext sit a few small facts in the clear, because the app must read them without the device’s check: when the copies were saved, when each runs out, each saved trip’s number and whether saving is switched off.

See also [Security](https://github.com/AnthonyPluth/Waypoint/blob/main/SECURITY.md).
