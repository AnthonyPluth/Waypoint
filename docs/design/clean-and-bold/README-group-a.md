# Clean and bold: Trips and the completed trip (group A of #879)

These designs are for items 1 and 2 of [#879](https://github.com/AnthonyPluth/Waypoint/issues/879), the other pages in the clean and bold look (epic [#875](https://github.com/AnthonyPluth/Waypoint/issues/875)). **Not signed off yet**: nothing here is built until the owner writes "Signed off" on #879 with the page's name (Trips; the completed-trip page). The owner may sign the pages off one at a time.

The files follow the format of the e to k frames in this folder: self-contained HTML, vector only (photos are drawn as gradient stand-ins, no raster images), dark only, phone (390 px) and desktop (1280 px) with the toggle at the top. Every trip, name, place, code, price and date is made up. They use the tokens as shipped in `frontend/src/app.css` (#880) and add none: page `#0d0c12`, black cards with no border or shadow, corners 30 px and 24 px, text `#ffffff`, secondary `#a9a8b2`, labels `#8f8e98`, hairline `#27262c`; blue `#3d8ef7` live, now or the one primary action, green `#4cc38a` confirmed or good news, amber `#eba43b` changed or needs attention; the kind outlines of #876 and #878; Inter, with Geist Mono for times, codes and seats (#877).

Each screen draws what the page does today in the new look. No feature is added or taken away, and every word on screen is today's.

| Item | File | What it shows |
| --- | --- | --- |
| 1 | [m-trips.html](m-trips.html) | Trips: the header and Add, the search and filters (phone sheet, desktop bar), the Upcoming cards in their three forms, the two panes from 73 rem, the Past list of #705 and #708 in every card form, and the loading, error, empty and no-match states |
| 2 | [m-past-trip.html](m-past-trip.html) | The completed-trip page (`PastTrip.svelte`, #709 and #710): photos hero and map hero on phone, Trip options, the sharing reminder and the Photo sharing sheet and popover, Replay, the desktop page with its 400 px column |
| 2 | [m-bookings.html](m-bookings.html) | The Bookings sheet and the desktop list (#711), and the booking detail of a completed trip (#712) for a changed stay, a car, a cancelled train, parking, a flight with a cancelled leg, a cruise and a visit after the trip's emails were removed |

## Item 1: Trips

**Replaces** the look of `frontend/src/pages/Trips.svelte`, `TripCard.svelte` (hero, row and card forms), `PastTripCard.svelte`, `YearChips.svelte` and `TravellerAvatars.svelte` as built.

**Keeps** the page as it works today: the summary line ("9 trips · 3 coming up", "5 of 9 trips"), Add (a round button with a three-item menu on phone; Add a past trip, Add a booking and Add a trip on desktop, the last the one blue action), the search and its placeholder, the Year and Travelling filters in a sheet on phone (with the blue dot when one is in use) and on one bar on desktop, Clear filters, the three empty texts, the Upcoming forms (the first trip as a hero and the rest as rows on phone; rows beside the pane; cards from 768 px when there is no pane), the two panes from 73 rem with the selected trip of #906 on the right (only a trip still to come), and the Past list year by year with the next year loading by itself on phone and "Show more" without IntersectionObserver.

**What changes**: black cards with 24 px corners and no border or shadow; the dashed stub line becomes the card's one hairline; the next trip's date and countdown are blue (now), the others grey; today's amber month goes (amber means attention); kind icons are outlines with no tile; the chosen year is a white chip and the chosen person keeps a blue ring.

**What of #705 stays**: all of design A for the Past list and the owner decisions of 2026-11-16 (#708): the photo mosaic (one large and two small, or two, or one), the name on the scrim, the photo-count pill, the footer of dates, nights and distance with the avatars, the year as an `h2` with its totals, one column on phone and two across on desktop with the destination under the name, the card link's name carrying the footer for the reader, the route map in place of the mosaic when there are no photos and the kinds tile when the route cannot be placed (MapKit-only design). Only the card's surface changes: black, 24 px, no border or shadow, the scrim ending in black.

## Item 2: the completed-trip page, its Bookings and the booking detail

**Replaces** the look of `PastTrip.svelte` (#709 phone, #710 desktop), `PastBookings.svelte` and `PastBookingsSheet.svelte` (#711), and `BookingDetail.svelte` (#712) on a completed trip. As the owner decided on #878 (2026-11-20), `BookingDetail.svelte` is restyled once and shared with trips still to come: [g-booking-detail.html](g-booking-detail.html) draws it on a trip still to come, `m-bookings.html` draws the completed-trip kinds and states, with no action row as today.

**Keeps** the back link "Past trips", Edit trip details (the pencil) and Trip options (Add a booking, Merge another trip, Delete trip), the hero (the photo mosaic, or the title, the route map and "No photos yet" when fewer than three photos can be shown), Sharing and the reminder with Share…, the facts line (Days, Nights, Distance, Photos on phone; Places on desktop), the total when costs are shown, the need-a-look link, Replay (inline on phone, in the column on desktop), the notes, the Bookings row and sheet (phone) or list (desktop), the photos by day with "+N", Far, video and itinerary marks, Show all N days, Open gallery, and the "Done" card. In Bookings: the groups (Whole trip, each day, Other), the flat dated list on desktop, the selected row while its detail is open, Changed and Cancelled. In the detail: the sheet and panel, Edit with More (Move, Remove) while the emails are kept, the rows each kind has, Copy, the cancelled note "Cancelled, so not in the trip's total", the Status row and traveller notes of a combined booking with a cancelled leg, a seat shown once, the cruise itinerary.

**What of #705 stays**: frames b, c and d with every owner decision recorded in [`docs/design/trips/README.md`](../trips/README.md) (2026-11-16 to 2026-11-18): the mosaic hero (three photos on phone, seven on desktop), each photo once, the 400 px column that stays in view, six photos a day on phone and up to twelve on desktop, the Bookings row and sheet, the detail's rows, More beside Edit, the Changed state; and the removals of 2026-11-18 (no photo pins, no stops list, no day glyph). Only the look changes.

**Photos are shared by their person**: the Past cards, the hero, the day grids, every count, the need-a-look count and the map are built only from photos the viewer may see, as today. A trip whose only photos are another person's unshared ones shows the route map on its card; `m-past-trip.html` p3 shows a viewer whose own photos are kept to themselves, with the reminder only they see. The sharing sheet and popover are `TripPhotoSharingMenu` restyled, for the people the viewer acts for only.

## Open for the owner

Drawn as the recommendation; each needs the owner's answer before it is built.

1. **The next trip in blue** (m1, m10, m12): the next trip's date and countdown blue, the others grey (drawn); or every countdown grey.
2. **The selected trip beside the pane** (m10): a 2 px blue ring (drawn, as today's primary border) or the black pill of the side navigation.
3. **The list column beside the pane** (m10) is about 262 px at 1280, as today, so names and the nights line truncate. Drawn as today; the alternative would be to drop the avatars from rows beside the pane.
4. **The scrim** on the Past cards and the hero: ends in black (drawn) or in the page colour as today. The photo-count pill stays as built.
5. **The day rail's dot** (p1): label grey (drawn), since a past day is not live; or blue as today.
6. **"3 photos need a look"** (p1, p6): a quiet line with an amber dot, like the review line on Upcoming (drawn), or today's soft amber chip.
7. **Status in the booking detail and list** (b1, b2, b4): amber "Changed" and "Cancelled" words in the detail's subtitle, following #878 item 5 and its open point 1 (today a warn chip and a red chip); "Changed" amber and "Cancelled" quiet grey on a list row (drawn).
8. **Destructive actions** (p3, p4): Delete trip after a divider and "Stop sharing on this trip" drawn without red, since #876 allows only blue, green and amber; the confirmation dialogs carry the warning. Or keep today's red (`--destructive`, `text-status-bad-ink`). Group C's shared pieces (buttons, dialogs) may settle this for every page.
9. **No blue action on a completed trip** (p1 to p7): nothing on a finished trip is drawn as the page's one blue action; Sharing, Replay, Open gallery and "Done" are plain buttons.
10. **The sharing scope** (p4, p7): "Everyone on this trip" as grey text beside "Your photos" (drawn) or today's blue info chip.
11. **Times on booking rows** in Geist Mono (b1, b9), as #877 keeps mono for times.
12. Followed from #876 and #878 as drawn there: neutral grey avatars (not the six avatar tones), the bed icon for a stay, and group C's look for inputs, chips, sheets, menus and the map surfaces; where group C's signed-off pieces differ, theirs win.
