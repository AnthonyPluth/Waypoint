# Offline access card in the iPhone app: design for sign-off

This is the design for [#740](https://github.com/AnthonyPluth/Waypoint/issues/740), part of the offline epic [#734](https://github.com/AnthonyPluth/Waypoint/issues/734): the Settings card that turns "save trips on this device" on and off inside the iPhone app. Nothing is built until the owner signs it off on #740. The file is a self-contained HTML page (vector only, no raster images, dark only). Open it in a browser and use the toggle at the top to see it at phone width (390 px) or desktop width (960 px for the cards, 1280 px for the page in place). The page uses Waypoint's tokens from `frontend/src/app.css` and adds none. Every trip name and time in it is made up.

| Screen | File | What it shows |
| --- | --- | --- |
| a | [a-settings-card.html](a-settings-card.html) | The card in place (Settings, Offline & notifications) at phone and desktop width, then every state: off, turning on and saving, saved with the trips and when (two trips, one, ten, Remove's confirmation), on with nothing saved, couldn't save, can't be read, signed out, not supported, and the Upcoming and trip-page panels |

## Decisions already made (the epic, 2026-11-16)

- No Face ID. The phone's lock is the gate, so the card never mentions a device check or a passkey.
- No encryption of Waypoint's own. The saved trips live in the app's private storage under iOS Data Protection, and the files may go into iCloud and computer backups.
- The app shows a cached copy of the server's own pages when the server can't be reached, and reads the saved trips over the native bridge.
- Inside the app that supports the bridge, the card never shows "Offline access isn't available on this device" or the passkey setup.
- A trip is removed 3 days after it ends, and everything is removed on sign-out, on a 401 or 403, when saving is turned off and on Remove.

## What the design proposes

- One card, in the same place and the same `rows` pattern as the browser's: a status line (On for this iPhone, Off on this iPhone), a switch named "Save my upcoming trips", the saved trips by name with when they were saved, one sentence on how they are kept, and Remove from this iPhone.
- The switch is the whole setup: no sheet, no prompt, no device check. Switching off deletes the saved trips at once, as in the browser.
- A failed save keeps the older copy. A copy that can't be read can only be removed.
- In a browser nothing changes, and signed-out people see the app's existing sign-out screen.

## Open decisions for the owner

These are questions, not guesses. Where a frame shows an answer, it is a proposal and says so.

1. **What should Remove from this iPhone do while the switch is on?** The bridge's `remove` deletes the copy and leaves saving on, so the trips would come back at the next online open. The page draws A.
    - A. Remove also switches saving off (two calls from the web, no native change).
    - B. Remove deletes and keeps saving on; the dialog says the trips come back.
    - C. No Remove button; the switch is the only control, since switching off already deletes.
2. **"This iPhone" or "this device"?** The app may also run on an iPad; "this device" is the browser card's word.
3. **Does the card mention backups?** It has one quiet line, "The saved copy can be part of your iCloud and computer backups." Keep it, move it to the docs only, or drop it?
4. **Should the app offer saving the first time a trip opens?** The browser offers "Keep this trip available offline" in a sheet. The app as drawn has no prompt, only Settings.
5. **Does saving start off or on for a new install?** Today it starts off and the person turns it on (A). It could start on at the first sign-in.
6. **May the app report progress and failures to the card?** The saving state (B) and couldn't-save states (E) need the bridge's `status` reply to say "saving now" and "last save failed". It has neither today. Add them (a small change to the Swift side), or show only the off, saved and nothing-saved states?
7. **Does the signed-out screen say the saved trips were removed?** F adds one line to a native screen outside this issue.
8. **After signing in again, is saving on or off?** Sign-out deletes the trips; the saving flag is per phone.
9. **What does an app too old for the bridge show?** It can't be told from a browser. Leave today's passkey or "isn't available" card (G1), show an update note (G2), or detect the app and show nothing.
10. **Does the wide layout matter?** 0b shows desktop width. Is the app expected on an iPad or a Mac, or is phone width the only one that ships?
11. **How should ten saved trips be listed?** C4 and C5 show three names and "and 7 more" with Show all and Show fewer. The alternatives are always listing all, or only "10 trips saved".
12. **Is the privacy sentence right?** "Kept in Waypoint's private storage on this iPhone, protected by the phone's lock. Other apps and websites can't read it, and Waypoint adds no encryption of its own."

## Fonts

The page loads Geist and Geist Mono from Google Fonts when you are online and falls back to system fonts otherwise. This is for viewing the design file only; the app bundles its own fonts and loads nothing from outside.
