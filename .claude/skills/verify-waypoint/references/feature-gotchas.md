# Feature gotchas

Hand-edited. `tools/user_feature_map.py` merges these into [feature-map.md](feature-map.md) (generated; never edit that one). A `## <name>` heading must be a page (`upcoming`, `trips`, ...) or a flow's name (a file in `frontend/verify/flows/`), and only `- ` bullets go under it. Demo data only; no real names, codes or numbers. General advice is in [gotchas.md](gotchas.md).

## upcoming
- A session that hasn't run `tools/control offline` shows an "Offline access" panel saying the device can't make a passkey; make verify's images show the page after offline access is set up.
- The first card is the next thing under way on the frozen day (2026-06-15): in the demo it is a London hotel check-in two days out. Nothing here moves with the real date.

## trips
- The list loads after the heading renders (a Loading indicator first): `wait-settle`, then `snapshot`.
- A trip's link is `#trip/<id>`; at desktop width the page shows the trip beside the list (the route becomes `#trips?trip=<id>`), so click the link and read the route in the answer.

## review
- The demo has emails waiting (the Upcoming page links "emails to review"). The flows that ignore a sender or read mail fake the replies (`fake_ignore`, `fake_labels`, `fake_ignored`): the demo mailbox can't reach Google and ignoring a sender must not change the demo data.

## people
- Loyalty and Known Traveler numbers are masked until asked for. The flows stop at the form (`people-add-id`); put no real number in one, demo or not.

## settings
- Sections are routes of their own (`#settings/offline`, `#settings/account`); `goto` the section rather than clicking down from `settings`.

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
