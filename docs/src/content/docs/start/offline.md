---
title: Offline
description: How the saved offline trip is kept encrypted on your device, what the lock protects against and what it doesn’t.
sidebar:
  order: 6
---

Waypoint can keep a copy of a trip on your phone or computer so you can open it without a connection. That copy is always encrypted on the device, and it opens only with the device’s own check: Face ID, Touch ID, a fingerprint reader, Windows Hello, or the screen lock code where that is what the device offers. Nothing is ever saved in the clear.

## Setting it up

The first time a trip loads while you’re online on a device that isn’t set up, Waypoint shows **Keep this trip available offline** and asks for the device’s check. Choose **Not now** to leave offline off on that device; you can set it up later in Settings → Data → **Set up offline access**. Until it is set up, nothing is saved.

Setting up creates a passkey for this site. Its only job is unlocking the saved trip: signing in to Waypoint still goes through your identity provider, and nothing about the passkey is sent to the server. Waypoint asks for user verification, so the passkey can’t be used without the device’s check.

## Saving and unlocking

- **Saving never asks.** Once it is set up, opening a trip online saves a fresh encrypted copy in the background, with no Face ID prompt.
- **Opening it offline asks.** Offline, the trip shows **Saved trip is locked** with an **Unlock** button. A cancelled or failed unlock stays on that screen with **Try again** and never shows the trip.
- **It locks again** when you close the app and after 5 minutes without use.
- **Online, nothing changes.** While you’re online and signed in, Waypoint shows the trip from the server as usual. The lock protects only the saved offline copy.
- **A lost passkey.** On a new device, or if the passkey was deleted, the saved trip can’t be unlocked. The screen says so and offers **Remove saved trip**. Set offline access up again while online and Waypoint saves a fresh copy. There is no recovery of the old copy and no passphrase option.

**Remove saved trip** in Settings deletes the copy and the key from the device.

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
- What is stored on the device is the ciphertext, the public key, the wrapped private key, the passkey’s credential id and the nonces. No key, no PRF output and no plaintext is stored.

See also [Security](https://github.com/AnthonyPluth/Waypoint/blob/main/SECURITY.md).
