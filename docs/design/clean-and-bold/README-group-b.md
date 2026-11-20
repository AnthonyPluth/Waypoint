# Clean and bold: flight status, Review and Stats (group B of #879)

These designs are for items 3, 4 and 5 of [#879](https://github.com/AnthonyPluth/Waypoint/issues/879), the other pages in the clean and bold look (epic [#875](https://github.com/AnthonyPluth/Waypoint/issues/875)). **Not signed off yet**: nothing here is built until the owner writes "Signed off" on #879 with the page's name (the live flight status view; Review; Stats). The owner may sign the pages off one at a time.

The files follow the format of the e to k frames in this folder and of group A's m files: self-contained HTML, vector only, no raster images, dark only, phone (390 px) and desktop (1280 px) with the toggle at the top; pieces drawn alone show at 608 px on desktop. Every flight, person, email, sender, mailbox, place and number is made up. They use the tokens as shipped in `frontend/src/app.css` (#880) and add none: page `#0d0c12`, black cards with no border or shadow, corners 30 px (the flight card) and 24 px, text `#ffffff`, secondary `#a9a8b2`, labels `#8f8e98`, hairline `#27262c`; blue `#3d8ef7` live, now or the one primary action, green `#4cc38a` confirmed, on time or good news, amber `#eba43b` changed or needs attention; the kind outlines (flight `#4f9dff`, stay `#38c6d9`, car `#f4d35e`, parking `#d9d8e0`, cruise `#ff8fab`); Inter, with Geist Mono for times, codes and seats (#877). The phone frames carry the frosted tab bar and the desktop frames the side navigation of [j-navigation.html](j-navigation.html).

Each screen draws what the page does today in the new look. No feature is added or taken away, and the words on screen are today's.

| Item | File | What it shows |
| --- | --- | --- |
| 3 | [n-flight-status.html](n-flight-status.html) | The live flight status view: a flight in the air (phone and desktop), before take-off and delayed, boarding, landed, cancelled, diverted, updates paused, a refresh that failed, loading and the page's errors |
| 4 | [n-review.html](n-review.html) | Review: the list with its four groups (phone and desktop), View email, the Check this suggestion sheet (phone) and split (desktop), read two ways, a booking you already have, More, ignoring a sender with Undo, nothing to review, one sender only, loading and errors |
| 5 | [n-stats.html](n-stats.html) | Stats: the page with MapKit on (phone and desktop), the map slot with no key and loading, hotels, cars, parking and cruises, the Filters sheet, nothing finished, loading and errors, and the Year in review |

## Item 3: the live flight status view

**Replaces** the look of `frontend/src/pages/FlightStatus.svelte` as built in #715 from frame b of [`docs/design/flights/`](../flights/README.md) (#666).

**Keeps** the page's parts and order: the back link to the trip, Refresh (an icon on phone, a button beside "Updated … · live status" on desktop, shown only while live status can be fetched), the flight card with the route, the headline as a polite live region with its countdown ("Landing in 2 hours 5 minutes", "Departs in …", "Boarding now at gate B14", "Landed 3 minutes early", "Cancelled", "Diverted"), the detail line in its phone and desktop wording, the progress bar, the timeline with done, now and next steps and the scheduled time under each, the facts, the seats per traveller (a line on phone, a list with cabin on desktop), "Seats and cabin come from the booking. Gate, terminal and belt come from live status and can change.", "The belt appears after landing.", "Live updates paused until …", "Couldn’t refresh. Last updated …", the toast when no status is found, and the four alerts (could not load, no such flight, no time recorded yet, with their buttons). Times are wall-clock times at the airport; on desktop they show under the codes with the zone and "scheduled", on phone in the timeline, as today.

**What of #666 stays**: the route as the headline with two large codes, the arc and the plane marking progress; times under their airports with the zone, amber with the booked time struck through when delayed; "Updated N min ago" only with live data; the eight states; the live view's headline, progress bar, timeline, arrival facts and seats per traveller; seat and cabin from the booking and gate, terminal and belt from live status; a dash for an unknown value, never a missing row; and every owner decision on the build of #714 and #715 (the headlines and lines of each state, "Updated less than a minute ago", the wording of a failed refresh). What goes is what #876 departure 2 already took from the hero: Waypoint's mark tile by the flight number, the status pill in every state, and the live or booked dot beside each fact.

**What the hero's three-fact rule changes**: the facts card always shows three facts, with the hero's labels from #878 item 2. From take-off it is Arrival term, Arrival gate and Bag claim (today Terminal, Gate and Belt); before take-off it is Terminal, Gate and Seats, where today it shows only Terminal and Gate. The `SourceDot` marks go; the sentence under the facts says once where the values come from. The status is a blue marker for boarding and in the air, green for an on-time or early landing (amber for a late one), and an amber pill only for delayed, cancelled and diverted, as on the hero.

## Item 4: Review

**Replaces** the look of `frontend/src/pages/Review.svelte`, its sheet, `MessageView.svelte` where Review uses it, and the ignore dialog.

**Keeps** everything the page does: the lede, "How Waypoint handles these emails" (closed), the jump buttons when there is more than one group, the four groups in today's order with their headings, counts and explanations; each row's subject (or "Mail from … on …"), "Sent … · to …" or "in Tomas’s mailbox, shared with the household", the reason, how it was read ("Read from the email", "AI suggestion", "Read two ways", "read automatically"), a suggestion error and "N emails about the same reservation"; Check suggestion, Check N suggestions or Add by hand, View email and More (Add by hand instead, Dismiss or Dismiss all, and "Not travel: ignore this sender" only for your own mailbox); Match bookings with its candidates, "It’s a new booking" and Dismiss, or "The bookings it could be aren’t yours to see."; Match people with the chooser and "A new guest…"; the sheet's titles, Email and Booking switch on phone, the split from its breakpoint, every field per kind with "from “…”" beside a value read from the email, legs, Add another leg or booking, the two-readings switch, "This looks like a booking you already have" with its three choices, the discard guard; the ignore dialog with the known-sender warning and the count; the toast with Undo; the filter line with Show everything; nothing to review; loading and errors.

**Privacy (counts only)**: the Review tab's badge and the line on Upcoming show counts only, as today. The list shows what Waypoint knows about each email (subject, sender's domain, when it was sent, which mailbox) and what it read from it, never the email's text. The kept email shows only where the app shows it today: under its row after View email, and in the sheet. Another person's mailbox shows only when they share it, as today, and its rows have no "ignore this sender". No Ask AI is drawn, per the owner's decision of 2026-11-19.

## Item 5: Stats

**Replaces** the look of `frontend/src/pages/Stats.svelte`, `stats/TopList.svelte`, `YearChips.svelte` and `TravellerAvatars.svelte` where Stats uses them, and `YearInReview.svelte`.

**Keeps** the summary line, the filters (a row with Filters and its in-use dot and the sheet on phone, the year chips and travellers on desktop), "See your YEAR in review" for a past year or the current one in December, the headline numbers, Where you’ve been (Countries and States, the map, the Countries list), Flights (five tiles with the distance comparisons, Routes, Airports, Airlines, Flight records, Seats with Cabin, Where you sit and Top seat), Hotels, Cars, Parking and Cruises, each only when there is something to count; lists of five with "Show all N"; the empty state's two texts and buttons; loading and the error with Try again. The Year in review keeps its cards, order, Back and Next, Close, the arrow keys and Escape, and Save as image with its result line.

**The map and the image are not drawn here**: the Apple map is drawn live by MapKit in the browser, so `n-stats.html` draws its slot only; with no MapKit key, offline, with nothing to place or after a failure the page has no map slot, as built in #835 to #839 under [`docs/design/mapkit-only/`](../mapkit-only/README.md). The Year in review's map card and saved image are drawn on the device from the year's numbers (`mapSvg` and `cardSvg` in `frontend/src/lib/review.ts`) and are drawn here as slots.

## Open for the owner

Drawn as the recommendation; each needs the owner's answer before it is built.

1. **Seats before take-off** (n2): Seats as the third departure fact (drawn), with the phone "Seats:" line hidden until take-off and the desktop list kept for names and cabin; or two facts before take-off as built.
2. **"The belt appears after landing."** (n1) under a fact now labelled Bag claim: keep "belt" (drawn) or "Bag claim appears after landing."
3. **Cancelled** (n3): amber as drawn or grey, the question already open as #878's point 1 for the hero; this page follows that answer.
4. **No blue on the Review list** (r1): every row's buttons are plain, so blue keeps meaning the one primary action ("Add to my trips" in the sheet, or "Add the email to that booking"); or keep today's primary Check suggestion and Add by hand.
5. **The ring on a field read from the email** (r3): blue as today's primary ring (drawn) or white.
6. **"Ignore"** (r5) as a plain button, not red, as #876 allows only blue, green and amber; or keep today's destructive red. The same question as group A's point 8.
7. **Bars in Stats** (s1): one colour, white on the hairline track (drawn), or today's four chart colours.
8. **The headline numbers** (s1): kept as Stats' top row of tiles, without today's blue border (drawn), or folded into the summary line.
9. **The Year in review's label** (s5): grey (drawn) instead of today's amber signal ink; and whether the saved image and map card keep their own look (drawn as slots) or a follow-up redraws them, since they are shared outside Waypoint.
10. Followed from #876, #878 and group A as drawn there: neutral grey avatars, the chosen year as a white chip and the chosen person with a blue ring, the bed icon for a stay, and group C's look for alerts, buttons, inputs, sheets, dialogs and menus; where group C's signed-off pieces differ, theirs win.
