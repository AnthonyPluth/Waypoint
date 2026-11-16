# Feature gotchas

Hand-edited. `tools/user_feature_map.py` merges these into [feature-map.md](feature-map.md) (generated; never edit that one). A `## <name>` heading must be a page (`upcoming`, `trips`, ...) or a flow's name (a file in `frontend/verify/flows/`), and only `- ` bullets go under it. Demo data only; no real names, codes or numbers. General advice is in [gotchas.md](gotchas.md).

## upcoming
- A session that hasn't run `tools/control offline` shows an "Offline access" panel saying the device can't make a passkey; make verify's images show the page after offline access is set up.
- The first card is the next thing under way on the frozen day (2026-06-15): in the demo it is a London hotel check-in two days out. Nothing here moves with the real date.

## trips
- The list loads after the heading renders (a Loading indicator first): `wait-settle`, then `snapshot`.
- A trip's link is `#trip/<id>`; at desktop width the page shows the trip beside the list (the route becomes `#trips?trip=<id>`), so click the link and read the route in the answer.

- Past cards: the demo's Past list shows photo mosaics only on a signed-in session (`--signed-in jane`; local mode has no photos and draws the route-map tile). Distances and the route maps load after the cards, so `wait-settle` and then wait a few seconds before a screenshot. A past trip never opens the side pane: the pane (desktop width) shows only for a trip still to come, so filter to a year with none (`#trips?year=2025`) to see the Past cards two across.

## trip
- Without `--signed-in`, the demo runs as the local user, for whom photos are off: the page then has no hero photos and no days, and shows the route map and its replay in the hero's place.
- The page opens the road trip, which is over, so it is the completed trip page: a photo hero, the facts line and the photos day by day. Its booking cards sit below the days until the Bookings sheet lands.
- The route replay plays on its own once it is on the page (the hero when there are no photos, or the replay that Replay trip opens); press `End` on "Position along the route" before a screenshot, as make verify does, so the picture is the same every time.

## past-trip-page
- A past trip with photos (the road trip), one with none (the Paris trip, whose hero is the route map with "No photos yet") and, with `fake_photo_limit`, one with two photos (the Lakeside Resort trip), then the Trip options menu, Show all days and a photo in the viewer. Needs `--signed-in jane` for `tools/control`.
- The map hero plays the replay on its own; the flow presses `End` on "Position along the route" before those pictures, as make verify does for the trip page, so they are the same every time.

## review
- The demo has emails waiting (the Upcoming page links "emails to review"). The flows that ignore a sender or read mail fake the replies (`fake_ignore`, `fake_labels`, `fake_ignored`): the demo mailbox can't reach Google and ignoring a sender must not change the demo data.

## people
- Loyalty and Known Traveler numbers are masked until asked for. The flows stop at the form (`people-add-id`); put no real number in one, demo or not.

## settings
- Sections are routes of their own (`#settings/offline`, `#settings/account`); `goto` the section rather than clicking down from `settings`.
- Photos: the demo's photos are generated placeholder pictures from `demo` libraries (one per member), so the road trip, the Lakeside Resort trip and the current trip show photos with no Immich server. A demo library's Test and Sync now do nothing real (Test answers with the person's name, Sync now answers `started: false`) and open no connection, so pressing them gives no 5xx and nothing in `console`. Connecting a new library needs the `fake_immich` flow step (PHOTOS-UI-SETTINGS).

## design
- Not in the navigation: the navigation keeps Settings lit on it. It shows the app's own components (booking cards, chips, tiles) on made-up data, and make verify checks it like any page.

## oauth-approve
- Not a route of the app: it is the page an assistant's connection request lands on. make verify registers made-up assistants and opens it; `tools/control` has no way to, so check it with `make verify PAGES="oauth-approve"`.

## add-booking-direct
- Starts with `fake_first_run` and a `reload`: the page then believes the household has a connected mailbox and no trips, so it isn't the demo trips you see on Upcoming.

## offline-trip
- Opens on `localhost`, because a passkey needs a host name. Chrome allows one virtual authenticator per browser context, so `tools/control flow` runs it in a new browser; run `offline` first and it still passes.
- It expects the browser's own "ERR_INTERNET_DISCONNECTED" console errors while it is offline on purpose, and ends back online.

## more-menu
- Phone only: it opens the More menu of the tab bar. At desktop width (`flow more-menu --viewport desktop`) its first step fails, because there is no More button.

## open-settings
- Desktop only: it clicks the sidebar's Settings link, which isn't there on a phone.

## trips-widths
- Runs at laptop, desktop, wide and zoomed widths and writes no image (make verify writes images at phone and desktop only); `tools/control` saves them anyway under `artifacts/control/flows/`.

## people-add-id
- Opens the form for a made-up member's number and takes the screenshot. It never saves one.
