# Clean and bold: People, Settings and the shared pieces (group C of #879)

These designs are for items 6, 7 and 8 of [#879](https://github.com/AnthonyPluth/Waypoint/issues/879), the other pages in the clean and bold look (epic [#875](https://github.com/AnthonyPluth/Waypoint/issues/875)). **Not signed off yet**: nothing here is built until the owner writes "Signed off" on #879 with the page's name (People; Settings, with the design specimen page; the shared pieces). The owner may sign the pages off one at a time.

The files follow the format of the e to k frames in this folder and of groups A (m files) and B (n files): self-contained HTML, vector only, no raster images (photos are gradient stand-ins and Apple's map a drawn stand-in), dark only, phone (390 px) and desktop (1280 px) with the toggle at the top; pieces drawn alone show at 608 px on desktop. Every person, address, host, program, count and date is made up. They use the tokens as shipped in `frontend/src/app.css` (#880) and add none: page `#0d0c12`, black cards with no border or shadow, corners 30 px and 24 px, text `#ffffff`, secondary `#a9a8b2`, labels `#8f8e98`, hairline `#27262c`; blue `#3d8ef7` live, now or the one primary action, green `#4cc38a` confirmed or good news, amber `#eba43b` changed or needs attention; the kind outlines of #876 and #878; the `--map-*` colours for maps; Inter, with Geist Mono for times, codes and seats (#877). Buttons, inputs and menus use the fill (`#1a1920`) and well (`#141319`) greys the e to k frames introduced (see point 5 below). The phone frames carry the frosted tab bar and the desktop frames the side navigation of [j-navigation.html](j-navigation.html).

Each screen draws what the page does today in the new look. No feature is added or taken away, and the words on screen are today's.

| Item | File | What it shows |
| --- | --- | --- |
| 6 | [p-people.html](p-people.html) | People: the list with numbers by kind, masked (phone and desktop); adding a guest and editing a person (phone sheet, desktop in place); adding and editing a loyalty or traveler number; showing and copying a number; the three confirmations; loading, error and empty |
| 7 | [p-settings.html](p-settings.html) | Settings: the seven groups; a group page and Account (signed in, running without sign-in); Mail & review (mailboxes, labels, Review at a glance, reconnect, AI with an Ollama address); Photos (libraries, Needs a look, connecting a library, photo sharing); Travel preferences; Offline & notifications (offline access and its passkey sheet, reminders, calendar feed); Connected assistants; Backup & import (backup, restore with type to confirm, import preview); and the design specimen page (`Design.svelte`) |
| 8 | [p-shared.html](p-shared.html) | The shared pieces: buttons (destructive included), forms and inputs, status chips and tags, dialogs, sheets and the discard guard, menus, alerts, notices, toasts and loading, and the map surfaces (the MapKit slot, loading, failure and the no-key state) |

## Item 6: People

**Replaces** the look of `frontend/src/pages/People.svelte`: the person rows, the Member and Guest badges, the loyalty list, the in-place forms on desktop and the sheets on the phone, the confirmations, and the loading, error and empty states. No signed-off design covered People before.

**Keeps** everything the page does: the title and "Add a guest"; the line "Saved loyalty and Known Traveler numbers are visible to every signed-in household member. They stay hidden until someone asks to show them."; each person with Member or Guest, Edit, Remove for a guest, the legal name and aliases line, "Linked from guest … by … on …", "Two numbers for …: both are kept. Remove the one that's wrong."; the numbers grouped by kind in today's order with their brand mark (or monogram), program, masked number, expiry, notes, Edit and Remove; "Can't be read with this key: enter it again"; "Add loyalty or traveler number" and "This is me"; both forms with every field, limit, help text and the discard guard; the three confirmations with their words; the toasts ("Guest added", "Saved", "Number added", "Removed", "Copied", "Couldn't copy it: select the number instead.").

**Privacy (IDs are for the household)**: every number is drawn masked, as `mask()` in `waypoint/domain/loyalty.py` sends it (four dots and the last four digits); the digits in the masks are placeholders, not numbers. The full number reaches the browser only when someone taps it, and the shown state draws it as a hatched bar, so no file here carries a number, real or real-looking. The edit form never puts the saved number back in its field ("Leave empty to keep ••••5678"). The list and the sentence under the Number field say, as today, that every signed-in member can show a saved number.

## Item 7: Settings and the design specimen

**Replaces** the look of `frontend/src/pages/Settings.svelte` (the index of groups with tinted icon chips, and the group page with its list on desktop) and every section under `frontend/src/lib/components/settings/`, with `OfflineSetup.svelte`'s sheet; and the look of `frontend/src/pages/Design.svelte`. No signed-off design covered them; [mapkit-only](../mapkit-only/README.md) frame c4 drew a Travel "Maps" row that the owner dropped on 2026-11-19, and it is not drawn.

**Keeps** the seven groups in today's order with their labels and sentences, "Make Waypoint yours", the back link and the list beside the content from `lg`, and every section and control that exists today:

- Account: signed in as, Sign out (it also clears the saved route cache, map snapshots and offline copy); "Running without sign-in" with Local; "Not signed in"; Advanced with Version, Database and the flight status calls this month. Sign-in is the household's own; Waypoint has no passkey sign-in, and the only passkey is the one offline access makes to unlock the saved trips, which its sheet says.
- Mail & review: each Gmail mailbox with its state, read-only line, last scan and summary or "Scanning for bookings…", the household sharing checkbox, Choose labels and its list, Ignored senders with Stop ignoring, Review at a glance (counts and sender domains only) with Ignore this sender, scan notices, Scan now, Look back through all mail, Reconnect and Disconnect, with their dialogs; Connect your Gmail, Add another Gmail or "Gmail isn't set up". AI: an Ollama address and model only (there is no hosted provider), "How email is shared", Save.
- Photos: each Immich library with its state, Sync now, Change key, Pause or Resume, Remove; Needs a look; Connect an Immich library with Whose library, address, key with Show, permissions, what Waypoint reads, Test and Save; Photo sharing with the person switch, default scope, Share on all my trips and the trips list with Share… or Stop sharing.
- Travel preferences: Home (city, state or region, ZIP, country code, Save, Clear), Distances (Miles, Kilometres), Trip costs (Show, Hide).
- Offline & notifications: offline access in every state, the iPhone app's card, Set up offline access, Remove from this device; reminders (Check-in opens, Day-of summary, Booking emails to review), devices, Register this device, the calendar feed with New address, Turn off and the address shown once.
- Connected assistants: the MCP address with Copy, "Let assistants change trips", each assistant with its access, "Read email text" and Disconnect.
- Backup & import: Download backup, Restore from a file with the summary, table, type-to-confirm dialog and result; Import past flights with the preview, who was on the flights, filters, search, rows, paging and Add.
- Design: its sections in today's order (Status, Airport codes, Route line, the cards, Kind icons, Avatar stack, Type, Colour rules, Surfaces). Pass card and Flight card, and the kind tiles, are drawn as what replaced them (point 12).

**Privacy**: Review at a glance shows counts and sender domains only, never anything from a message. Photos are shared by their person: Needs a look and the trips list show only libraries the viewer owns or manages. Keys, the calendar address and the backup's secrets are drawn masked or as placeholders.

## Item 8: the shared pieces

**Replaces** the look of `frontend/src/lib/components/ui/` (button, input, badge, alert, sheet, confirm-dialog, discard-dialog, options-menu), `StatusChip.svelte`, the native checkbox, radio, switch, select, date and file controls as Settings and People style them, the toasts, and the map slot of `StatsMapKit.svelte`, `RouteReplay.svelte` and the Trips cards.

**Keeps** each piece's behaviour, focus order, words and sizes (44 px tap areas on the phone; field text 16 px on the phone), the sheet's drag to close and guard, type to confirm, the toast's place above the tab bar, and every map rule signed off in [mapkit-only](../mapkit-only/README.md) (#828): what Apple is asked and when, no map and no slot with no key, offline or nothing to place, the kinds tile on a Trips card, and "The map couldn't load" after a failed replay.

Groups A and B follow these pieces and say that where group C's signed-off pieces differ, group C's win.

## Open for the owner

Drawn as the recommendation; each needs the owner's answer before it is built.

1. **Destructive actions** (p-shared s1, s4, s6; People p5; Settings): a plain button or menu row with an amber label, not red, since #876 allows only blue, green and amber; or keep today's red (`--destructive`, `#ff7b72`). This answers group A's point 8 and group B's point 6 for every page.
2. **Status chips** (p-shared s3): a coloured dot and word with no tinted background; the amber filled pill only for Delayed; the bad tone (Cancelled, Diverted, Key refused) amber, not red or grey (#878 open point 1); "On time" green instead of today's info blue, and Departed and Syncing blue (live). Badges that are not a status (Member, Guest, Local, an assistant's access) become grey tags.
3. **Chosen is white** (p-shared s2): ticked checkboxes, chosen radios, switches that are on and the chosen side of a two-choice switch in white, as the chosen year chip of group B; or blue.
4. **Form problems** (p-shared s2, s7): an amber ring and an amber line under the field, and alerts as black cards whose icon carries the tone; or today's tinted amber box and red alert text.
5. **The fills** (p-shared s1): buttons on `#1a1920` and inputs and menus on `#141319`, as the e to k frames draw them. The shipped `--secondary` (`#1a1e29`), `--input` (`#2c3243`) and `--popover` (`#181c26`) are still the earlier blue-greys; this design leaves them as they are, and a build issue would change them only on the owner's say.
6. **The `action` button variant** (`--action`, `#3563e0`) folds into the blue primary (drawn) or keeps its own deeper blue.
7. **One blue per section in Settings** (s3 to s8): each section's Save or Connect is blue, since each section is its own task; or one blue per page.
8. **A shown number** (People p4): the tap target with a blue ring while shown (drawn) or no ring; and the masked number as a quiet button on the well grey (drawn, so it reads as tappable) or plain text that underlines on hover, as built.
9. **Member and Guest** (People p1): grey tags (drawn) instead of today's filled blue Member badge and outline Guest badge.
10. **The Settings index** (s1): "Make Waypoint yours" in label grey (drawn) instead of blue, and the group icons as white outlines with no tinted chip (drawn) or in label grey.
11. **A mailbox's state** (s3): Connected as a green status word (drawn) instead of today's outline badge; Reconnect amber.
12. **The design specimen** (s9): the built hero and booking cards in place of Pass card and Flight card, the outline kind icons in place of kind tiles, and Surfaces as the three fills instead of three shadowed elevations (drawn), so the page describes what was built (#875); or keep today's sections.
13. **Map surfaces** (p-shared s8): the slot with 24 px corners and no border or shadow (drawn) or today's hairline border and elevation; the overlays keep the shipped `--map-airport`, `--map-stay` and `--map-visited` (drawn) or move to the kind and status colours (the airport's `#f6b73c` is close to amber, "needs attention").
14. Followed from #876, #878 and groups A and B as drawn there: neutral grey avatars (not the six avatar tones) and the bed icon for a stay (the app uses a building), both still open on #876.
