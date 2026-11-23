# Clean and bold: trip detail, Upcoming and the states the first mockups do not draw

This folder holds the designs of the clean and bold redesign ([#875](https://github.com/AnthonyPluth/Waypoint/issues/875)). Screens a to d are for [#876](https://github.com/AnthonyPluth/Waypoint/issues/876): trip detail, Upcoming, the cards and the colour rules. They are **reconstructed** from the written spec and the shipped app, because the owner's approved mockups live only on a private design canvas (see "Screens a to d: reconstructed" below); they wait for the owner to write "Signed off" on #876. Screens e to k are for [#878](https://github.com/AnthonyPluth/Waypoint/issues/878), a sub-issue of #875, and draw what the build issues ([#881](https://github.com/AnthonyPluth/Waypoint/issues/881) to [#884](https://github.com/AnthonyPluth/Waypoint/issues/884)) needed beyond the first mockups; the owner signed them off on #878 on 2026-11-20, and they are built (#902, #904, #905, #906).

Screens e to k were drawn before a to d were in the repository, from the tokens in [#880](https://github.com/AnthonyPluth/Waypoint/issues/880); a to d use the same tokens and add none:

- Page `#0d0c12`, cards `#1a1922` (raised slate, [owner decision 2026-11-21](#owner-decision-2026-11-21-option-a-raised-slate); first drawn `#000000`) with no border, gradient or shadow; corners 30 px on the flight hero card and 24 px on booking cards.
- Text `#ffffff`, secondary `#a9a8b2`, small uppercase labels `#8f8e98` (11 px, weight 600, 0.09em), one hairline `#2e2d38` per card (first drawn `#27262c`).
- Blue `#3d8ef7` is live, now or the one primary action; green `#4cc38a` is confirmed, on time or good news; amber `#eba43b` is changed or needs attention. Nothing else is coloured.
- Kind icons are coloured outlines with no chip: flight `#4f9dff`, stay `#38c6d9`, car `#f4d35e`, train `#c79bff`, cruise `#ff8fab`; parking and visit are proposed here (item 4).
- Type: Inter for everything, with Geist Mono kept for confirmation codes, times and seats, as `docs/src/content/docs/contributing/design.md` documents; the owner chose this on [#877](https://github.com/AnthonyPluth/Waypoint/issues/877) on 2026-11-20.

Each file is a self-contained HTML page (vector only, no raster images, dark only) for one screen group. Open it in a browser and use the toggle at the top for phone (390 px) or desktop (1280 px). Cards drawn alone show at desktop width at 576 px, the width of a column of the desktop trip page; full screens show the whole 1280 px. Every name, place, flight, seat, code, price and date is made up, and the QR pattern is random. The pages load Inter and Geist Mono from Google Fonts for viewing only; the app bundles its own fonts and loads nothing from outside.

| Item | File | What it shows |
| --- | --- | --- |
| #876 a | [a-trip-detail.html](a-trip-detail.html) | Trip detail of a trip still to come, phone and desktop (reconstructed) |
| #876 b | [b-upcoming.html](b-upcoming.html) | Upcoming with a flight next, phone and desktop (reconstructed) |
| #876 c | [c-cards.html](c-cards.html) | The flight hero card on time, delayed, in the air and landed; the stay, car and train cards, and the compact card of a flight that is not the hero (reconstructed) |
| #876 d | [d-colour-rules.html](d-colour-rules.html) | Surfaces and greys, the three colour rules, the kind icon colours, and the three colour options with option C (blue and green) marked (reconstructed) |
| #878 1, 2, 3 | [e-flight-states.html](e-flight-states.html) | The flight hero card boarding, cancelled, diverted and scheduled with no live data; the three facts and the colours of all eight states; where a time's zone shows and the struck-through original time when delayed |
| #878 4, 5 | [f-booking-kinds.html](f-booking-kinds.html) | Booking cards for a cruise, a parking booking (with Show code) and a past visit; a changed and a cancelled booking |
| #878 6 | [g-booking-detail.html](g-booking-detail.html) | The opened booking: `BookingDetail.svelte` restyled, as a phone sheet and a desktop panel, for a flight and a stay on a trip still to come and the same flight on a completed trip |
| #878 7 | [h-show-code.html](h-show-code.html) | The gate code dialog opened, phone and desktop |
| #878 8 | [i-upcoming.html](i-upcoming.html) | Upcoming at desktop width; the empty states (no trips, with and without Gmail to connect; nothing next) at phone and desktop |
| #878 9 | [j-navigation.html](j-navigation.html) | The phone tab bar, frosted (recommended) and plain black, More opened; the side navigation from `lg` |
| #878 10 | [k-travellers-connection.html](k-travellers-connection.html) | The hero with three travellers' seats, and a connection before the first leg and at the stop (the connection was removed on the owner's request: each flight is its own hero) |

## Owner decision 2026-11-21: option A, raised slate

The black cards faded into the near-black page, so the owner chose "Option A, Raised slate" for the surface colours on 2026-11-21 (design sign-off given in chat; the options were shown on an artifact page; [#919](https://github.com/AnthonyPluth/Waypoint/issues/919)). It replaces the card and hairline values the files here were first drawn with; text, accents and kind colours do not change.

| Token | Was | Now |
| --- | --- | --- |
| Page (`--background`) | `#0d0c12` | `#0d0c12` (unchanged) |
| Card (`--card`) | `#000000` | `#1a1922` |
| Hairline and edge (`--border`) | `#27262c` | `#2e2d38` |
| Card header strip (`--card-header`, the "Next up" band of the pass card) | none | `#201f2a` |
| Secondary buttons and fills inside cards (`--secondary`, `--muted`, `--accent`, `--surface-3`) | `#1a1e29`, `#1f2433` | `#262531` |

Text `#ffffff`, secondary `#a9a8b2` and labels `#8f8e98` keep at least 4.5:1 on the card (17.4, 7.4 and 5.4), the header strip and the secondary fill. [d-colour-rules.html](d-colour-rules.html) draws the new values. The other files in this folder keep the pixels they were drawn with, which show the first black card; the app and `design.md` follow this decision (shipped in #920).

## Owner decisions on #878 (2026-11-20)

Given in chat on 2026-11-20 and recorded in [a comment on #878](https://github.com/AnthonyPluth/Waypoint/issues/878#issuecomment-7043311182):

1. **Item 6: the opened state is `BookingDetail.svelte` (#712) restyled**, one component for completed and upcoming trips. It keeps its sheet and panel, header, More menu (Move, Remove) and rows; a trip not yet over adds the action row (email, directions, call, the airline app) the old booking card had, and a completed trip shows none, as today.
2. **The mockup labels Nights, Days, Return and From are adopted**, beside the words `frontend/src/lib/trips.ts` uses today (`START_WORD`, `END_WORD`): a card's middle fact is Nights or Days, and the cruise, parking and visit cards use today's Embarks and Disembarks, Entry and Exit, From and To.

## Decisions the designs of #878 propose

These follow from the issue, #876's colour rules and how the app works today; they stand unless the owner says otherwise in review.

- **Item 1.** Boarding reads like on time with a blue "Boarding" marker; the gate stays a fact, not the big fact (the card never repeats itself, #714). Cancelled has no plane, grey struck codes and times, and the quiet line "Contact Aurora Air about rebooking."; diverted shows the new airport with the booked one struck above it and the arrival facts as dashes; scheduled with no live data has no green "on time" and says "Times from your booking. Live status starts 1 day before."
- **Item 2.** Departure side (Terminal, Gate, Seats) before take-off, arrival side (Arrival term, Arrival gate, Bag claim) from take-off; an unknown value is a grey dash. The fourth fact (Cabin; Seat on arrival) moves to the opened booking. The live and booked marks of #666 go: the quiet line says once where the card's values come from ("Updated 9 minutes ago" or "Times from your booking"). A late landing is amber.
- **Item 4.** Cruise `#ff8fab`; a single-day visit keeps From and To.
- **Item 5.** The status word replaces the green "Confirmed" at the end of the grey line; a changed booking marks the changed values amber when the app knows which; a cancelled one is greyed with struck facts, keeps its place and loses Show code.
- **Item 7.** The existing gate code dialog, restyled; "Choose another picture" stays where it is offered today.
- **Item 8.** Desktop Upcoming has the side navigation, the 64 px title, the review line and two columns (hero, day list). The empty states keep today's titles, texts, buttons and order of cases; the first button is the page's one blue action.
- **Item 10.** Codes for the whole journey with the stop on the arc and "1 stop, JFK"; facts and seats for the leg you are on; a "Then" line for the next leg, "Earlier" during the connection.
- Nothing here changes what a page shows a person: travellers appear only where the app shows them today, price only when costs are shown, and a confirmation code only in the opened booking. Every time is a wall-clock time at its place.

## Open for the owner on #878

Drawn as the recommendation. Answered on 2026-11-20: the owner's sign-off accepts the recommendation drawn for each of the twelve points ([comment on #878](https://github.com/AnthonyPluth/Waypoint/issues/878#issuecomment-7044163401)); for point 11, today's rendering stays on the new tokens until a follow-up draws it.

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
12. Still open on #876 and followed here as the mockups draw them: neutral grey avatars (not the six avatar tones). The bed icon for a stay was decided on 2026-11-21 and shipped in #913 (the app draws a bed); see "Screens a to d: reconstructed".

## Screens a to d: reconstructed

#876 asked for the owner's approved mockups (screens a to d) to be put in this folder. They are on the owner's private design canvas, which the agents working on this repository cannot open, so the files here are **reconstructions, not copies of the canvas**. Each is drawn from the decisions written in #876 and #875, the tokens of #880 and the components as built (`FlightHero.svelte` in #902, `BookingCard.svelte` in #904, `Upcoming.svelte` in #905 and #907, `Trip.svelte` in #906, the tokens in `frontend/src/app.css` from #899), so it shows what the app now shows, except four points the owner decided on 2026-11-21 (listed below), which are drawn as decided; the `make verify` images in `docs/src/assets/screenshots` were a reference and none is copied here. Each file says so in a banner at the top. The owner signed the look off in chat on 2026-11-20; "Signed off" on #876 after reviewing these files confirms that they match it.

| Screen | File | What it shows |
| --- | --- | --- |
| a | [a-trip-detail.html](a-trip-detail.html) | A trip still to come: back link, Edit and Trip options, the trip name at 40 px (64 px desktop), dates, summary, neutral avatars, the total; the next flight as the hero with the travellers' seats and "Confirmation, travellers and price"; Then: stay, car, train and the return flight as compact cards; the footer line. Desktop: side navigation, Next up and Then in two columns. |
| b | [b-upcoming.html](b-upcoming.html) | Upcoming with a flight next: date, title, offline status and Add a booking; the one review line; the hero under "Next up" with its footer; the day-by-day list with the blue Next marker; Later. Desktop: hero and "Coming up" in two columns. #876 asked for phone only; desktop is drawn as built (frame i is its design). |
| c | [c-cards.html](c-cards.html) | The flight hero on time, delayed, in the air and landed (the other four states are frame e); the stay, car and train cards and the compact flight card. |
| d | [d-colour-rules.html](d-colour-rules.html) | Page, card, greys and hairline; blue, green and amber with what each means; the kind icon colours; the three colour options with option C (blue and green) marked. |

### Colour options A and B

#875 says only that the owner chose "option C of the colour options board", blue and green with amber for change. Neither issue nor any comment describes options A and B, so frame d shows them as empty, labelled "not drawn", and draws the chosen rule only. Inventing them would misstate what the owner saw.

### The decisions #876 fixes

As approved by the owner in the design session, and as drawn in a to d:

1. Page `#0d0c12`, true-black `#000000` cards (now `#1a1922`, see "Owner decision 2026-11-21: option A, raised slate"), no borders, gradients or shadows; corners 30 px (flight card) and 24 px (booking cards).
2. Big heavy white type for codes, times and facts; grey `#a9a8b2` for secondary text and `#8f8e98` for small uppercase labels; one hairline per card (`#27262c`, now `#2e2d38`).
3. Blue `#3d8ef7` is live, now, or the one primary action; green `#4cc38a` is confirmed, on time, or good news; amber `#eba43b` is changed or needs attention. Nothing else is coloured.
4. Booking-type icons are coloured outlines with no tinted chip: flight `#4f9dff`, stay `#38c6d9`, car `#f4d35e`, train `#c79bff`, cruise `#ff8fab`.
5. Confirmation code, cost, address and travellers are behind a tap; "Show code" stays visible on a booking with a QR code.
6. Upcoming has no stat tiles and no banners; emails to review are one quiet line.

### Departures from recorded decisions, and the owner's answers

The six #876 lists:

| # | Departure | Owner's answer |
| --- | --- | --- |
| 1 | `docs/design/trips/README.md` (#712, decision 2): a trip still to come keeps its cards; the new trip detail replaces them (frame a). | Drawn in the mockups the owner approved and signed off in chat on 2026-11-20; built in #906. No answer to this point on its own was found: recorded in the build, not separately confirmed. |
| 2 | `docs/design/flights/README.md` (#666): pill in every state, four facts, live or booked marks, mark tile. The new hero has three facts, no marks, no mark tile, a pill only when delayed, cancelled or diverted (frames c and e). | Item 2 of #878 (the fourth fact moves to the opened booking, one quiet line replaces the marks) was signed off on #878 on 2026-11-20; built in #902. The removal itself has no separate answer: recorded in the build, not separately confirmed. |
| 3a | `design.md`: kind icons "on its tint". The cards use the outline (frames a to c). | Recorded in the build (#904: outline on the cards and the opened booking, tinted tiles elsewhere until #879), not separately confirmed. |
| 3b | `design.md`: times, codes and seats in Geist Mono; the mockups set them in the sans face. | Confirmed on #877, 2026-11-20: Inter for the sans face, Geist Mono kept as documented for times, airport codes, confirmation codes and seats. The build of #902 set the hero's airport codes in Inter at weight 800. **Owner decision 2026-11-21** ([#876](https://github.com/AnthonyPluth/Waypoint/issues/876#issuecomment-7053836714)) puts the hero's airport codes, times and seats in Geist Mono: shipped in #913. Frames a to c draw the codes in Geist Mono. |
| 3c | `design.md`: the frosted tab bar; the mockup draws a plain black bar. | Confirmed: frosted, point 7 of #878 accepted as drawn on 2026-11-20 (frames a and b draw it frosted). |
| 4 | Times in the mockups show no zone. | Confirmed: point 2 of #878 accepted as drawn, the zone abbreviation under each time on the hero; the big fact and lists carry none (frames b and c). |
| 5 | The stay icon in the mockups is a bed; the app uses a building. | A bed, everywhere `KindTile` shows a stay: **Owner decision 2026-11-21** ([#876](https://github.com/AnthonyPluth/Waypoint/issues/876#issuecomment-7053836714)): shipped in #913. The build of #904 kept the building. Frames a to d draw the bed. |
| 6 | Traveller avatars are neutral grey, not the six avatar tones. | Confirmed: point 12 of #878 accepted; built in #906 (`AvatarStack` `neutral`). |

Departures found in the build that #876 does not list, drawn as built:

| Departure | Owner's answer |
| --- | --- |
| A flight that is not the hero is a compact card with Departs, Flight and Arrives (frames a and c). | Owner decision on #883, recorded in #906. |
| A stay card and the Upcoming day rows keep the booking's brand logo (frames a to c). | Owner's wish, recorded in #904 and #905. |
| When the next booking is not a flight, Upcoming and the trip page keep today's card on the new tokens, and Also under way, the arrival card and the offline status are unchanged. Not drawn here. | Confirmed: point 11 of #878. |
| Connections (frame k) are not built. | Deferred by the owner to #903. |
| The Later dates on Upcoming are amber, though amber otherwise means changed (frame b). | Owner decision, #907. |
| The flight hero as built in #902 keeps a 1 px `#27262c` edge and the card shadow (`border border-border shadow-card`), against decision 1. | No edge and no shadow, like the booking cards: **Owner decision 2026-11-21** ([#876](https://github.com/AnthonyPluth/Waypoint/issues/876#issuecomment-7053836714)): shipped in #913. Frames a to d draw the hero without them. |
| On Upcoming the flight hero as built in #905 keeps the confirmation code, the travellers and the cost in its footer, against decision 5. | They move behind a tap (the opened booking), as on the trip page: **Owner decision 2026-11-21** ([#876](https://github.com/AnthonyPluth/Waypoint/issues/876#issuecomment-7053836714)): shipped in #914. Frame b draws the hero with the “Confirmation, travellers and price” row and only the airline action and Open trip below it. |
| The airline action ("Check in", "Open in app") is the existing action blue `#3563e0` (`--action`), not the status blue (frame b). | Recorded in the build, not separately confirmed. |
| Amber text (a late time, "45 min late") uses the light ink `#ffd58a` (`--signal-ink`) for contrast; pills and dots use `#eba43b` (frames c and d). | Recorded in the build, not separately confirmed. |
| Upcoming keeps the small date over the title, the green saved-for-offline status and Add a booking in the header (frame b). | Recorded in the build (#905), not separately confirmed. |
| The trip page keeps the trip total under the title (frame a). Costs follow the "show costs" setting, as before. | Recorded in the build (#906), not separately confirmed. |

### Open questions

- The rows still marked "recorded in the build, not separately confirmed" (departures 1, 2 and 3a, the action blue, the amber ink, Upcoming's header extras and the trip total): the owner's "Signed off" on #876 accepts them as built, or names the ones to change.
- The four owner decisions of 2026-11-21 are drawn as decided and shipped (#913 for the hero's type, edge and shadow and the bed; #914 for Upcoming's tap); the app matches frames a to d in those four points.
- The typeface is decided (#877). Screens not drawn in a to d (the other pages, the states of #878) are in e to k and in their own sub-issues of #875.

Trips and the completed-trip page in this look (#879, group A): see [README-group-a.md](README-group-a.md).

People, Settings with the design specimen, and the shared pieces in this look (#879, group C): see [README-group-c.md](README-group-c.md).

The live flight status view, Review and Stats in this look (#879, group B): see [README-group-b.md](README-group-b.md).
