# Offline access card in the iPhone app: signed-off design

This is the design for [#740](https://github.com/AnthonyPluth/Waypoint/issues/740), part of the offline epic [#734](https://github.com/AnthonyPluth/Waypoint/issues/734): the Settings card that shows and switches "save my upcoming trips" inside the iPhone app. The owner signed it off on 2026-11-17 (answers to the questions the first draft asked). The file is a self-contained HTML page (vector only, no raster images, dark only, phone width 390 px only). The page uses Waypoint's tokens from `frontend/src/app.css` and adds none. Every trip name and time in it is made up.

| Screen | File | What it shows |
| --- | --- | --- |
| a | [a-settings-card.html](a-settings-card.html) | The card in place (Settings, Offline & notifications), then every state: off, saving, saved with the trips and when (two trips, one, ten), on with nothing saved, couldn't save, can't be read, signed out, the browser card for reference, and the Upcoming and trip-page panels |

## Decisions

Decided by the owner on 2026-11-17, with the epic's earlier ones:

- No Face ID: the phone's lock is the gate. No encryption of Waypoint's own: the saved trips live in the app's private storage under iOS Data Protection, and the files may go into iCloud and computer backups.
- No Remove button. Switching saving off is the only way to delete the saved trips, and it deletes them at once, with no confirmation, as in the browser. Remove and its confirmation are not built.
- The card says "this device", not "this iPhone".
- The card keeps the line "The saved copy can be part of your iCloud and computer backups."
- No prompt offers saving. Saving is on by default for a new install and can be switched off in Settings. The very first save happens at the first online open after signing in, so until then the card says "On for this device" and "Nothing is saved yet".
- After signing in again, saving is on.
- The signed-out screen says "Saved trips were removed from this device."
- An app too old to have the offline bridge shows no Offline access card at all. Real browsers keep today's card and every word of it unchanged.
- Phone width is the only width that ships.
- Ten saved trips show three names, then "and 7 more" with Show all (and Show fewer).
- The privacy sentence: "Kept in Waypoint's private storage on this device, protected by the phone's lock. Other apps and websites can't read it, and Waypoint adds no encryption of its own."
- Inside the app that supports the bridge, the card never shows "Offline access isn't available on this device" or the passkey setup.

## What the card shows

One card in the same place and the same `rows` pattern as the browser's: a status line (On for this device, Off on this device, Couldn't save the trips, The saved trips can't be read) with a chip, the saved trips by name with when they were saved and when each is removed, a switch named "Save my upcoming trips", one sentence on how they are kept and the backup line. A failed save keeps the older copy and is tried again at the next online open. A copy that can't be read is deleted by switching saving off and on.

## Bridge status: what the build adds

The saving state (B) and the couldn't-save states (E) need two flags the bridge's `status` reply does not have today. When the card is built, `ios/README.md`'s "Offline bridge" section (and `frontend/src/lib/offline-shell.ts`'s `readStatus`) change to this shape:

```
{ "version": 1, "saving": Bool, "syncing": Bool, "lastSaveFailed": Bool, "savedAt": Number | null, "trips": [{ "id": Number, "name": String }] }
```

- `saving`: the setting, on by default for a new install, so the saving flag's default flips to on.
- `syncing`: true while a fetch of `GET /api/offline` is running. The card shows state B and disables the switch.
- `lastSaveFailed`: true after a failed fetch or save that kept the older copy, and false after the next success or when saving is switched off. The card shows state E.
- The two new fields are optional for the web app (missing means false), so `version` stays 1. A reply with a different `version` is still an unreadable copy.
- The web app calls `status` when Settings opens and again, while `syncing` is true, until it is false.

## Fonts

The page loads Geist and Geist Mono from Google Fonts when you are online and falls back to system fonts otherwise. This is for viewing the design file only; the app bundles its own fonts and loads nothing from outside.
