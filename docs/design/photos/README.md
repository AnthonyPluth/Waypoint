# Trip photos and map: approved designs

The owner signed off these designs on [#485](https://github.com/AnthonyPluth/Waypoint/issues/485), and the sharing screens (i–m) for [#504](https://github.com/AnthonyPluth/Waypoint/issues/504) after. Each file is a self-contained HTML page (vector only, no raster images) for one screen group. Open it in a browser and use the toggle at the top to see it at phone width (390 px) or desktop width (1280 px; content-only screens show the 960 px content column). The pages use Waypoint's tokens from `frontend/src/app.css`, dark only. Every name, place, host and date in them is made up.

A UI issue builds the screens in the file it points at, and lists the accessible names and the tokens and components each mockup states.

| Screen | File | What it shows |
| --- | --- | --- |
| a | [a-trip-page.html](a-trip-page.html) | The trip page with the photo strip, and the gallery opened in place and grouped by day, with the far flag and the inferred-location mark |
| b | [b-photo-viewer.html](b-photo-viewer.html) | The viewer for a photo with GPS, a video placed from the itinerary, and a far photo; Open original |
| c | [c-trip-map.html](c-trip-map.html) | The route map with photo cluster pins, a tapped pin, and the replay passing a cluster |
| d | [d-map-pins-only.html](d-map-pins-only.html) | The map of a trip with no replayable route but with photo pins |
| e | [e-trip-summary.html](e-trip-summary.html) | The trip summary line: days, nights, distance in the household unit, states and countries, photos |
| f | [f-settings-photos.html](f-settings-photos.html) | Settings, Photos: the source cards and the Connect form with its plain-language note |
| g | [g-empty-states.html](g-empty-states.html) | No library connected (trip page and Settings), connected but nothing synced yet, a trip with no photos, a refused source, an unreachable source |
| h | [h-needs-a-look.html](h-needs-a-look.html) | Needs a look for ambiguous and far photos, with Pick a trip, Keep on this trip, Remove from this trip and Leave off |
| i | [i-sharing-prompt.html](i-sharing-prompt.html) | The sharing prompt on first visit (Only me preselected) and the reminder after Not now |
| j | [j-your-photos.html](j-your-photos.html) | Your photos on this trip: scope, Stop sharing and its confirmation, switching back to Only me with undo |
| k | [k-remove-photos.html](k-remove-photos.html) | Remove from this trip from the viewer and the gallery, and Put back |
| l | [l-others-view.html](l-others-view.html) | What everyone else sees (no trace of unshared photos), and the viewer when a photo is taken back |
| m | [m-sharing-settings.html](m-sharing-settings.html) | Settings, Photo sharing: default scope, Share on all my trips, per-trip list |

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

## Fonts

The pages load Geist and Geist Mono from Google Fonts when you are online and fall back to system fonts otherwise. This is for viewing these design files only; the app bundles its own fonts and loads nothing from outside.
