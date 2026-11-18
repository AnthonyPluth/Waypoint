# Trip photos and map: approved designs

The owner signed off these designs on [#485](https://github.com/AnthonyPluth/Waypoint/issues/485), and the sharing screens (i–m) for [#504](https://github.com/AnthonyPluth/Waypoint/issues/504) after. Each file is a self-contained HTML page (vector only, no raster images) for one screen group. Open it in a browser and use the toggle at the top to see it at phone width (390 px) or desktop width (1280 px; content-only screens show the 960 px content column). The pages use Waypoint's tokens from `frontend/src/app.css`, dark only. Every name, place, host and date in them is made up.

A UI issue builds the screens in the file it points at, and lists the accessible names and the tokens and components each mockup states.

| Screen | File | What it shows |
| --- | --- | --- |
| a | [a-trip-page.html](a-trip-page.html) | The trip page with the photo strip, and the gallery opened in place and grouped by day, with the far flag and the inferred-location mark |
| b | [b-photo-viewer.html](b-photo-viewer.html) | The viewer for a photo with GPS, a video placed from the itinerary, and a far photo; Open original |
| c | [c-trip-map.html](c-trip-map.html) | The route map with photo cluster pins, a tapped pin, and the replay passing a cluster (superseded 2026-11-18: see below) |
| d | [d-map-pins-only.html](d-map-pins-only.html) | The map of a trip with no placeable booking: photo pins only (decided, then superseded 2026-11-18: see below) |
| e | [e-trip-summary.html](e-trip-summary.html) | The trip summary line: days, nights, distance in the household unit, states and countries, photos |
| f | [f-settings-photos.html](f-settings-photos.html) | Settings, Photos: the source cards and the Connect form with its plain-language note |
| g | [g-empty-states.html](g-empty-states.html) | No library connected (trip page and Settings), connected but nothing synced yet, a trip with no photos, a refused source, an unreachable source |
| h | [h-needs-a-look.html](h-needs-a-look.html) | Needs a look for ambiguous and far photos, with Pick a trip, Keep on this trip, Remove from this trip and Leave off |
| i | [i-sharing-prompt.html](i-sharing-prompt.html) | The sharing prompt on first visit (Only me preselected) and the reminder after Not now |
| j | [j-your-photos.html](j-your-photos.html) | Your photos on this trip: scope, Stop sharing and its confirmation, switching back to Only me with undo |
| k | [k-remove-photos.html](k-remove-photos.html) | Remove from this trip from the viewer and the gallery, and Put back |
| l | [l-others-view.html](l-others-view.html) | What everyone else sees (no trace of unshared photos), and the viewer when a photo is taken back |
| m | [m-sharing-settings.html](m-sharing-settings.html) | Settings, Photo sharing: default scope, Share on all my trips, per-trip list |
| n | [trip-photo-sharing.html](trip-photo-sharing.html) | The trip page's Photos header with a Sharing button (beside Select and See all) that opens the sharing controls: a popover on desktop, a bottom sheet on phone; today's page and the closed state beside it |
| o | [past-trip-sharing.html](past-trip-sharing.html) | Decided by the owner on 2026-11-17 ([#772](https://github.com/AnthonyPluth/Waypoint/issues/772), amended the same day on [#789](https://github.com/AnthonyPluth/Waypoint/issues/789): `Sharing` alone where `View photos` isn't drawn): `Sharing` beside `View photos` on a completed trip's page, the panel as on a current trip (popover on desktop, bottom sheet on phone), every state of the panel, the reserved button slot; two placements not chosen kept for the record |

## Decisions the designs fix

- Needs a look lives in each source card in Settings, Photos. The trip page only shows a one-line pointer to a library's person when the trip has far photos of theirs.
- The gallery opens in place on the trip page, between the route map and the bookings, so tapping a map pin can scroll to its photos.
- A far photo has an amber Far tag on its tile and an amber dot on its pin. A photo placed from the itinerary has a hollow ring, matching the hollow pin.
- Photo pins use a new token, `--map-photo: var(--foreground)`, so they never read as a stop. Pin size is 16 px plus 4 px for each doubling of the count, up to 40 px, with the count inside.
- A far photo has a third action, Keep on this trip, because the trip's figures leave far photos out until they are accepted or moved.
- Save in the Connect form stays off until Test passes for the address and key as typed.
- Sharing (#504): Only me is the default; the prompt is a card in the Photos section; Share on all my trips is a standing setting; narrowing never asks, widening and Stop sharing ask once.
- Per-photo removal (Remove from this trip) replaces Hide; the trip owner cannot remove someone else's photo; removed photos can be put back.
- Other people see no trace of unshared photos: counts, pins, day groups, the summary and the viewer counter use only photos the viewer may see; another person's source card shows name, host and status only.
- Immediate removal needs `private, no-cache` thumbnails with the ETag, and open pages refetch on focus and every 60 s.
- A library for someone without a login is shared by whoever connected it.

The rules behind these screens (grants, scope, removal, caching) are in `docs/PHOTOS.md` as rewritten by [#536](https://github.com/AnthonyPluth/Waypoint/pull/536); until #536 merges, the copy on main still describes the earlier design. The user-facing page `docs/src/content/docs/start/photos.md` describes what the code does today and is rewritten with the code that implements these rules.

## Sharing button on the trip page

The owner signed off on moving the trip page's photo-sharing block behind a button in the Photos header, in chat on 2026-11-16 (variant A, then the owner changed the trigger from a cog icon to a text button). The build issue is [#744](https://github.com/AnthonyPluth/Waypoint/issues/744). The page [trip-photo-sharing.html](trip-photo-sharing.html) shows today's page, the closed state and the open panel at both widths.

- Variant A: a non-modal popover under the button on desktop, the app's existing bottom sheet on phone. The centred dialog (variant B) was dropped.
- The trigger is a text button labelled `Sharing`, in the style of `Select` and `See all`, first in the header's button row: `Sharing`, `Select`, `See all`. Its visible text is its accessible name; there is no icon-only button. The panel's title is `Photo sharing for this trip`.
- The button shows only while there is a sharing card to manage. The first-visit `ask` prompt and the `declined` reminder row stay inline with no button.
- People who cannot change anything see no button (not a disabled one).
- A steward managing a person without a sign-in gets one section per person in the panel, the viewer's own first and the others collapsed.
- The desktop popover is non-modal and closes on Escape, an outside click or Tab leaving it. Focus returns to the button on Escape. The sheet is modal.
- Nothing about who can see what changes.
- `docs/PHOTOS.md` mentions a one-line row with `Manage` that the code does not have; the build issue corrects it.

## Removed from the completed trip page (owner decision, 2026-11-18)

The owner looked at a completed trip on a phone and decided, in chat on 2026-11-18 (a chat decision with no issue; the owner then signed it off in chat the same day: "All fine, signed off"), to remove three things the signed-off designs draw. Where a frame below still shows one, this decision wins.

- **Photo pins.** The numbered white circles on the route replay map (one per cluster of photos, with the count inside, the hollow and far variants, the callout with **Show these photos**, the label card during the replay) and the **Photos**, **Photos placed from the itinerary** and **Far from every booking** entries of the map key are gone, on the bundled map and on Apple's alike. The map is the route alone and is fitted to the stops alone. Frames c (pins, tapped pin, replay passing a cluster) and d (a trip with no placeable booking drawn as pins only) are superseded; a trip with photos but no route to replay now shows no map. The `--map-photo` token stays in the theme for now: nothing uses it, and a token changes only on the owner's say.
- **The stops list.** The numbered, scrolling list of stops under the Replay controls (phone and desktop) is gone from the completed trip page. The older trip page for the static demo keeps it. The map still labels each stop as the replay reaches it and the slider reads out the stop it is on.
- **The day glyph.** The small squiggle beside each day on a phone drew no real path, so it is dropped; a day is its dot on the rail, its date, place and count, and its photos.

Photos are reached through the days, **Open gallery**, **View photos** and the viewer.

## Sharing on a completed trip (decided 2026-11-17, #772)

A trip that has ended is drawn by `PastTrip.svelte` (the photo-led page, the days as a timeline), whose Photos heading is visible to screen readers only. #744's `Sharing` button has no header to sit in there, so the page kept today's inline `Your photos on this trip` card under the days. The page [past-trip-sharing.html](past-trip-sharing.html) draws where the control goes. It is a layout change only: the panel, its words (`Photo sharing for this trip`, the radio group, `Stop sharing on this trip`, `Removed from this trip (N)`) and who sees what are #744's and do not change. The owner answered the design's questions in chat on 2026-11-17 (PR #787, issue #772); nothing is open.

The page draws, at phone and desktop width: today's page with the card this replaces (0); placement A, closed and open, for one section and for a steward with several (A); the states of the panel and the page (S); and the two placements not chosen (B, C).

### Amendment (2026-11-17, #789)

The frames draw `View photos` beside `Sharing` with 248 photos, but the page draws `View photos` only when the hero takes every photo the viewer can see (exactly three, so the days are empty; the #748 test "has no View photos button while the days show photos" holds that). The owner decided on 2026-11-17 (build issue [#789](https://github.com/AnthonyPluth/Waypoint/issues/789)): `Sharing` sits alone, left-aligned, in the row where `View photos` would be whenever `View photos` isn't drawn; `View photos` still appears beside it in the three-photo case; `View photos`'s behaviour does not change. Frames A1, A2, A3, S1, S3, S4 and S6 draw two buttons and so differ from the built page in the common case (a photo hero with days below). The reserved slot and its collapse work as decided below: with no `View photos` and no control, the row collapses once after the state loads, as under the map hero.

### Desktop placement (owner decision, 2026-11-17, after #794)

The frames are phone-first and draw the button in the row under the hero. #794 then gave the completed trip page two columns on desktop. The owner decided on 2026-11-17 that on desktop `Sharing` sits beside `Open gallery` in the right column's `Photos by day` header, not between the hero and the columns. The phone placement is unchanged. The Not now reminder sits directly under that header row on desktop (the same relation as on phone: directly under the button row), and the first-visit prompt stays above the days. The slot is still held blank while the sharing state loads and collapses for a person with no control, and the popover opens left-aligned under the button on the phone-width row. In the desktop header the button sits at the column's right edge, where a left-aligned 392 px popover would run off the screen, so it opens right-aligned, leftward, with its caret over the button.

### Decisions (2026-11-17)

- Placement A: a `Sharing` outline button in the row under the hero, beside `View photos` when that is drawn (see the amendment below). B (a visible `Photos by day` header with `Sharing` at its right) and C (`Sharing` after `Replay` in the facts line) are not chosen; they stay on the page for the record.
- The panel opens as on a current trip: a non-modal popover under the button on desktop, the app's modal bottom sheet on phone. The popover opens left-aligned under the left-hand button, with the caret over it.
- With fewer than three photos the page leads with the map and has no `View photos`; `Sharing` then sits alone on its own row under the map.
- The reminder after Not now moves up and sits directly under the button row (no button), instead of below the last day. The first-visit prompt stays inline above the days, with no button.
- The button's space is held from the start: while the sharing state loads, the slot where `Sharing` will be is reserved (the dashed outline in S6 and S7 is a drawing aid; it is blank in the app), so nothing jumps when the button arrives. Once the state is known and the person has no control, the slot collapses: a person with no control sees a blank space only while the state loads, then none. Beside `View photos` the collapse moves nothing; with the map hero the blank row under the map collapses and the page below moves up once. The owner accepted that one-time collapse for people with no sharing control on 2026-11-17.
- A person who acts for no one sees no control and no disabled button (S4). Only the people the viewer acts for get a button, as on a current trip.
- `Select` stays off the completed page: the panel is its only sharing control, and a photo is taken off from the viewer (#748).
- The inline card is removed from the completed page; its controls live in the panel only.
- The desktop frames use the built page, one column at most 48 rem wide (`max-w-3xl`), not the two-column page of [trips b2](../trips/b-trip-page.html).

The build is the one in #772: `TripPhotoSharingMenu.svelte` on the past trip page, the inline card removed there, the verify flows and the `trip` page images (the Denver trip) updated.

## Fonts

The pages load Geist and Geist Mono from Google Fonts when you are online and fall back to system fonts otherwise. This is for viewing these design files only; the app bundles its own fonts and loads nothing from outside.
