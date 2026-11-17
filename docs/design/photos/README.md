# Trip photos and map: approved designs

The owner signed off these designs on [#485](https://github.com/AnthonyPluth/Waypoint/issues/485), and the sharing screens (i–m) for [#504](https://github.com/AnthonyPluth/Waypoint/issues/504) after. Each file is a self-contained HTML page (vector only, no raster images) for one screen group. Open it in a browser and use the toggle at the top to see it at phone width (390 px) or desktop width (1280 px; content-only screens show the 960 px content column). The pages use Waypoint's tokens from `frontend/src/app.css`, dark only. Every name, place, host and date in them is made up.

A UI issue builds the screens in the file it points at, and lists the accessible names and the tokens and components each mockup states.

| Screen | File | What it shows |
| --- | --- | --- |
| a | [a-trip-page.html](a-trip-page.html) | The trip page with the photo strip, and the gallery opened in place and grouped by day, with the far flag and the inferred-location mark |
| b | [b-photo-viewer.html](b-photo-viewer.html) | The viewer for a photo with GPS, a video placed from the itinerary, and a far photo; Open original |
| c | [c-trip-map.html](c-trip-map.html) | The route map with photo cluster pins, a tapped pin, and the replay passing a cluster |
| d | [d-map-pins-only.html](d-map-pins-only.html) | The map of a trip with no placeable booking: photo pins only (decided) |
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
| o | [past-trip-sharing.html](past-trip-sharing.html) | **Awaiting sign-off** ([#772](https://github.com/AnthonyPluth/Waypoint/issues/772)): where the Sharing button sits on a completed trip's page (no Photos header there), how its panel opens, and every state of the panel; three placements side by side |

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

## Sharing on a completed trip (awaiting sign-off, #772)

A trip that has ended is drawn by `PastTrip.svelte` (the photo-led page, the days as a timeline), whose Photos heading is visible to screen readers only. #744's `Sharing` button has no header to sit in there, so the page keeps today's inline `Your photos on this trip` card under the days. The owner decided on 2026-11-17 that past trips get their own design. The page [past-trip-sharing.html](past-trip-sharing.html) draws it. It is a layout question only: the panel, its words (`Photo sharing for this trip`, the radio group, `Stop sharing on this trip`, `Removed from this trip (N)`) and who sees what are #744's and do not change.

The page draws, at phone and desktop width:

- Today's page with the card this replaces (0).
- Proposal A: `Sharing` beside `View photos` in the row under the hero, closed and open (a bottom sheet on phone, a non-modal popover under the button on desktop), for one section and for a steward with several (A).
- The states: Only me chosen, the first-visit prompt and the reminder after Not now (both stay inline, no button), a person who acts for no one (no control), and a trip with few photos (map hero, the row holds only `Sharing`) (S).
- Alternatives for comparison: B, a visible `Photos by day` header with `Sharing` at its right; C, `Sharing` after `Replay` in the facts line (B, C).

The desktop frames use the built page, one column at most 48 rem wide, not the two-column page of [trips b2](../trips/b-trip-page.html).

### Open questions for the owner

1. Where does the button sit: A (beside `View photos`, proposed), B (a visible `Photos by day` header) or C (in the facts line beside `Replay`)? A fourth option, D, is A on phone and the trips-b2 header on desktop; it is not drawn.
2. A page with fewer than three photos leads with the map and has no `View photos`. Is the button alone on its own row under the map (S5, as drawn), or should it join the facts line there while keeping A elsewhere?
3. In A the button is at the left, so the popover opens left-aligned under it with the caret over the button; in B and C it is right-aligned, as on a current trip. Is a left-aligned popover fine?
4. The reminder after Not now sits below the last day, far from the button. Keep it there, or move it up under the button row?
5. The sharing state loads after the page, so the button appears a moment late and the row can change height. Hold its space from the start (an empty row for a person who acts for no one), or let it appear when ready?
6. A current trip's header has `Select` beside `Sharing`; the completed page has none (a photo is taken off from the viewer, #748). Confirm `Select` stays off this page.

After sign-off the build is the one in #772: `TripPhotoSharingMenu.svelte` on the past trip page, the inline card removed there, the verify flows and the `trip` page images (the Denver trip) updated.

## Fonts

The pages load Geist and Geist Mono from Google Fonts when you are online and fall back to system fonts otherwise. This is for viewing these design files only; the app bundles its own fonts and loads nothing from outside.
