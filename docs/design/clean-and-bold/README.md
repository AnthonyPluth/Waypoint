# Clean and bold: the states and screens the mockups do not draw

These designs are for [#878](https://github.com/AnthonyPluth/Waypoint/issues/878), a sub-issue of the clean and bold redesign ([#875](https://github.com/AnthonyPluth/Waypoint/issues/875)). The approved mockups of [#876](https://github.com/AnthonyPluth/Waypoint/issues/876) draw trip detail, Upcoming at phone width, the flight card in four states and the stay, car and train cards; these files draw what the build issues ([#881](https://github.com/AnthonyPluth/Waypoint/issues/881) to [#884](https://github.com/AnthonyPluth/Waypoint/issues/884)) need beyond that. **Not signed off yet**: nothing here is built until the owner writes "Signed off" on #878 after the last revision.

#876's own files (screens a to d) are not on `main` yet, so this folder starts at e. Until they land, **the tokens in [#880](https://github.com/AnthonyPluth/Waypoint/issues/880) are the source for the look**, and these frames use them and add none:

- Page `#0d0c12`, cards `#000000` with no border, gradient or shadow; corners 30 px on the flight hero card and 24 px on booking cards.
- Text `#ffffff`, secondary `#a9a8b2`, small uppercase labels `#8f8e98` (11 px, weight 600, 0.09em), one hairline `#27262c` per card.
- Blue `#3d8ef7` is live, now or the one primary action; green `#4cc38a` is confirmed, on time or good news; amber `#eba43b` is changed or needs attention. Nothing else is coloured.
- Kind icons are coloured outlines with no chip: flight `#4f9dff`, stay `#38c6d9`, car `#f4d35e`, train `#c79bff`, cruise `#ff8fab`; parking and visit are proposed here (item 4).
- Type: Inter for everything, with Geist Mono kept for confirmation codes, times and seats, as `docs/src/content/docs/contributing/design.md` documents and as given for this work; [#877](https://github.com/AnthonyPluth/Waypoint/issues/877) records the owner's choice, and the frames follow it if it differs.

Each file is a self-contained HTML page (vector only, no raster images, dark only) for one screen group. Open it in a browser and use the toggle at the top for phone (390 px) or desktop (1280 px). Cards drawn alone show at desktop width at 576 px, the width of a column of the desktop trip page; full screens show the whole 1280 px. Every name, place, flight, seat, code, price and date is made up, and the QR pattern is random. The pages load Inter and Geist Mono from Google Fonts for viewing only; the app bundles its own fonts and loads nothing from outside.

| Item | File | What it shows |
| --- | --- | --- |
| 1, 2, 3 | [e-flight-states.html](e-flight-states.html) | The flight hero card boarding, cancelled, diverted and scheduled with no live data; the three facts and the colours of all eight states; where a time's zone shows and the struck-through original time when delayed |
| 4, 5 | [f-booking-kinds.html](f-booking-kinds.html) | Booking cards for a cruise, a parking booking (with Show code) and a past visit; a changed and a cancelled booking |
| 6 | [g-booking-detail.html](g-booking-detail.html) | The opened booking: `BookingDetail.svelte` restyled, as a phone sheet and a desktop panel, for a flight and a stay on a trip still to come and the same flight on a completed trip |
| 7 | [h-show-code.html](h-show-code.html) | The gate code dialog opened, phone and desktop |
| 8 | [i-upcoming.html](i-upcoming.html) | Upcoming at desktop width; the empty states (no trips, with and without Gmail to connect; nothing next) at phone and desktop |
| 9 | [j-navigation.html](j-navigation.html) | The phone tab bar, frosted (recommended) and plain black, More opened; the side navigation from `lg` |
| 10 | [k-travellers-connection.html](k-travellers-connection.html) | The hero with three travellers' seats, and a connection before the first leg and at the stop |

## Owner decisions (2026-11-20)

Given in chat on 2026-11-20 and recorded in [a comment on #878](https://github.com/AnthonyPluth/Waypoint/issues/878#issuecomment-7043311182):

1. **Item 6: the opened state is `BookingDetail.svelte` (#712) restyled**, one component for completed and upcoming trips. It keeps its sheet and panel, header, More menu (Move, Remove) and rows; a trip not yet over adds the action row (email, directions, call, the airline app) the old booking card had, and a completed trip shows none, as today.
2. **The mockup labels Nights, Days, Return and From are adopted**, beside the words `frontend/src/lib/trips.ts` uses today (`START_WORD`, `END_WORD`): a card's middle fact is Nights or Days, and the cruise, parking and visit cards use today's Embarks and Disembarks, Entry and Exit, From and To.

## Decisions the designs propose

These follow from the issue, #876's colour rules and how the app works today; they stand unless the owner says otherwise in review.

- **Item 1.** Boarding reads like on time with a blue "Boarding" marker; the gate stays a fact, not the big fact (the card never repeats itself, #714). Cancelled has no plane, grey struck codes and times, and the quiet line "Contact Aurora Air about rebooking."; diverted shows the new airport with the booked one struck above it and the arrival facts as dashes; scheduled with no live data has no green "on time" and says "Times from your booking. Live status starts 1 day before."
- **Item 2.** Departure side (Terminal, Gate, Seats) before take-off, arrival side (Arrival term, Arrival gate, Bag claim) from take-off; an unknown value is a grey dash. The fourth fact (Cabin; Seat on arrival) moves to the opened booking. The live and booked marks of #666 go: the quiet line says once where the card's values come from ("Updated 9 minutes ago" or "Times from your booking"). A late landing is amber.
- **Item 4.** Cruise `#ff8fab`; a single-day visit keeps From and To.
- **Item 5.** The status word replaces the green "Confirmed" at the end of the grey line; a changed booking marks the changed values amber when the app knows which; a cancelled one is greyed with struck facts, keeps its place and loses Show code.
- **Item 7.** The existing gate code dialog, restyled; "Choose another picture" stays where it is offered today.
- **Item 8.** Desktop Upcoming has the side navigation, the 64 px title, the review line and two columns (hero, day list). The empty states keep today's titles, texts, buttons and order of cases; the first button is the page's one blue action.
- **Item 10.** Codes for the whole journey with the stop on the arc and "1 stop, JFK"; facts and seats for the leg you are on; a "Then" line for the next leg, "Earlier" during the connection.
- Nothing here changes what a page shows a person: travellers appear only where the app shows them today, price only when costs are shown, and a confirmation code only in the opened booking. Every time is a wall-clock time at its place.

## Open for the owner

Drawn as the recommendation; each needs the owner's answer before it is built.

1. **Cancelled colour** (items 1 and 5): amber, as drawn (you may need to act), or grey. Red is not used, as #876 allows only blue, green and amber.
2. **Zone placement** (item 3): the zone abbreviation under each time on the hero, always (drawn), or only when the two airports' zones differ. The big fact and lists carry no zone.
3. **Parking and visit colours** (item 4): parking `#d9d8e0` (a light neutral; today's lime `#9be15d` sits next to the green "Confirmed" the way the old stay teal did) and visit `#8f8e98` (the label grey; today it is the muted grey). Both are tokens, so #880 or a follow-up changes them only on the owner's say.
4. **Action row in the opened booking** (item 6): above the rows (drawn) or at the bottom of the sheet; none of its buttons is blue.
5. **"Show this at the gate."** (item 7): new wording under the code.
6. **Desktop Upcoming** (item 8): two columns (drawn) or one centred column; the "Coming up" label is new wording. The round icon on the setup card is dropped, and "See your trips" becomes a button.
7. **The tab bar** (item 9): frosted glass as `design.md` line 116 specifies and as built (drawn, recommended) or the mockup's plain black bar; the current tab white with a blue icon, or white only; the Review count as an amber badge.
8. **The side navigation** (item 9): the current page on a black pill (drawn) or a white label only.
9. **Several travellers** (item 10): the per-traveller seat row on the hero (drawn) or seats only in the opened booking; "14A +2" or "3 seats".
10. **A connection** (item 10): whole-journey codes (drawn) or the current leg's; the amber short-connection hint under 45 minutes is a suggestion (the app has no such rule).
11. **Not drawn here**, though #883 and #884 name #878 for them: the hero when the next booking is not a flight, "Also under way", the arrival card and the offline status on Upcoming. They keep today's rendering on the new tokens until the owner says whether this issue or a follow-up draws them.
12. Still open on #876 and followed here as the mockups draw them: the bed icon for a stay (the app uses a building) and neutral grey avatars (not the six avatar tones).

Trips and the completed-trip page in this look (#879, group A): see [README-group-a.md](README-group-a.md).

People, Settings with the design specimen, and the shared pieces in this look (#879, group C): see [README-group-c.md](README-group-c.md).
