---
title: Trips
description: How Waypoint keeps your flights, hotels, rental cars and trains, who sees a trip, and why times are shown where they happen.
sidebar:
  order: 4
---

A **trip** is a journey. It holds **segments**: one flight leg, hotel stay, car rental, train or cruise each. You can add them by hand, and Waypoint adds them from the booking emails in a connected Gmail (see [Scanning](/Waypoint/start/gmail/#scanning)).

## The pages

- **Upcoming** leads with a card for what is next: a countdown, the flight number, departure time and terminal (or a hotel’s address and check-in time), and the confirmation code, which you tap to copy. A flight in the air or a rental car out counts as under way and leads until it ends; a hotel stay in progress doesn’t push the day’s flight aside. Below it, the trip that card belongs to (or the next one, when you aren’t travelling) is laid out day by day. On a day you leave, the list puts the hotel check-out first, then the car’s return, then the departure, whatever hours the bookings show (a check-out time is often the hotel’s standard hour, not when you walk out). Each booking in that list, and the card’s **Open** button, links to that booking’s card on its trip page, which scrolls to it and outlines it. Cancelled segments never lead.
  - A flight’s pass card (not yet shown on this page) has a line at the top that counts from the booked times only: “Check-in opens in …”, then from 24 hours before departure (the same 24 hours as the check-in reminder, see [Reminders](/Waypoint/start/reminders/)) “Check-in is open, departs in …”, then “Under way, arrives in …”, then “Landed”. The plane on the route line is placed the same way, from the booked departure and arrival, so a delay is never implied; live flight status, when it is on, adds only a small chip and a quiet line.
- **Trips** lists the trips you can see: the ones still to come or under way, and the past ones. Each trip shows small icons for what it holds: a plane for flights, a building for stays, a car, a train or a ship (cancelled bookings don’t count). Pick a traveller to see only their trips; the choice is kept in the address (`#trips?who=…`) so you can bookmark it.
- A **trip** page shows each segment as a card with its local times, travellers and the loyalty number each traveller would use for that airline or hotel chain, masked. Tap a number to show it and copy it; tap again to hide it. When a traveller has no number for the program a booking is with, the card says so and links to [People](/Waypoint/start/people/); a traveller known only by their printed name is marked as not matched to a person yet. On a hotel stay that is said only of the person who booked the room, since the others aren’t asked for a number (a number any of them has is still shown). Waypoint tells the program from the provider’s name (“American Airlines” is American AAdvantage), so write the provider the way the airline or chain does.

Add a booking from Trips (Waypoint puts it in the trip it belongs to, or starts one) or from a trip page (it goes in that trip), edit any segment, or remove it. **Edit** opens the form right under the booking you chose, scrolled into view wherever you are on the page, and the pencil beside a trip’s name renames it. A save that fails keeps everything you typed and says why; a page that can’t reload its trips shows an error with Try again, not the old trips as if they were current.

## Times beside yours

A segment’s time is always shown as it is at the place. When your own time zone has a different offset at that moment, your time for the same moment follows it in brackets: `7:00 PM [4:00 PM PST]`. It is only a second reading; nothing is converted or stored in your zone.

## Who sees a trip

You see a trip when you are travelling on any of its segments, when you booked it (the trip, or any of its segments), or when the confirmation of one of its bookings came to your own connected mailbox (see [One booking, one segment](#one-booking-one-segment)). Nobody else sees it, however they ask: its address answers “not found”, the same as a trip that doesn’t exist. A solo work trip stays its traveller’s. If you book a trip for a guest (a child, a grandparent), you see it because you booked it. Add someone as a traveller on a segment and the whole trip is shared with them.

Without sign-in, on your own machine, everyone is the one local household, which sees every trip.

## Segments

Each segment has a kind (flight, hotel, car, train or cruise), a status (confirmed, changed or cancelled), a confirmation code, the provider, a start and an end, where it starts and ends, a link to manage the booking, and details: flight number, terminal, seat, cabin, room, car class, address and phone. The **travellers** are people from [People](/Waypoint/start/people/), or, until a name on a booking is matched to a person, the name as printed.

A segment is added to a trip you name, or without one: Waypoint puts it in the trip it belongs to (see below) or makes a new trip. Flights from before Waypoint can be [imported from another app’s CSV export](/Waypoint/start/import/).

## Seats

On a flight or train, each traveller has a seat of their own: tick them in the booking’s edit form and a **Seat** field appears under their name (up to 10 characters, as it reads on the boarding pass). The card shows it beside their name, and the calendar event lists the seats by traveller. A seat counts as an edit of the travellers, so a later email won’t change it. Leaving a seat out when changing who is on a booking keeps it. A seat entered on a booking before this (one for all of them) stays on the booking, and moves to the traveller when the booking has only one and is edited.

## Actions on a booking

Each booking card has buttons for what you'd do next:

- **Open in app**: the booking's manage link (from the email, or one you entered). It's a link on the provider's own website; on an iPhone or Android phone it says **Open in app** and the provider's app opens it if installed; on a computer it says **Manage booking** and opens the provider's website. Only https links are offered. A cancelled booking keeps this one (you may need it for a refund) and loses the others. Waypoint doesn't build prefilled manage links for any provider yet, because it only adds one once its URL is confirmed from the provider's public site.
- **Address**: a hotel's or rental's address shows under its times, as written (up to 300 characters, over several lines if you like). Tap it to copy. With none, the card says **Add address**, which opens the edit form at that field. Editing a booking's details (address, room, phone and the rest) keeps them as a set: a later email won't replace them, but it fills the address while you haven't edited any of them. An address over 300 characters in an email is shortened to fit. Waypoint never looks addresses up; it has only what an email or you gave it, and the calendar feed carries it as the event's location.
- **Ports of call**: a cruise keeps the ports the ship calls at, in order, each with its name, its own time zone and the local times the ship arrives and leaves (either, both or neither). Add, move and remove them in the booking’s edit form; the card lists them with their times where they happen. The list is checked as you save: a departure can’t be before the arrival, and the ports must follow one another between embarking and disembarking. Editing the list keeps it like any other edit: a later email won’t replace it, and fills it only while it is empty. The terminal’s address works like a hotel’s, and the calendar feed carries the sailing as one event with the itinerary in its description.
- **Directions**: an Apple Maps link to a hotel's or rental's address (or its place name when there's no address). Your device hands the text to Apple Maps when you tap it; nothing is sent from the server.
- **Call**: dials the phone number on the booking, when it has one.

## Times are where they happen

A segment’s times are the wall-clock times at its places, stored with the place’s time zone (an IANA name such as `Pacific/Auckland`). Waypoint never converts them to the server’s time zone or to UTC: a 22:15 departure from Auckland is 22:15 in Auckland, and the arrival that is the same day in Los Angeles is shown at its own local time. Type a time as it appears on the booking, like `2026-03-01T22:15`, without an offset. A flight’s zones come from its airports (Waypoint knows the airports by their three-letter code); name the zone yourself for a place that isn’t on the list. A hotel stay is in one place, so it has **one time zone** for check-in and check-out: type it, or leave it empty and Waypoint works it out from the address. It reads the address text itself, offline (nothing is looked up or sent anywhere): a US state with its ZIP code, or a state in an address that says it is in the US (a bare “DE” or “CO” is never taken for Delaware or Colorado, since it may be Germany or Colombia), down to the ZIP prefix in states that span zones, such as Florida’s panhandle or El Paso), a Canadian province with a Canadian postal code or Canada named (for Alberta, Saskatchewan, Manitoba and the Atlantic provinces; British Columbia, Ontario, Quebec and Newfoundland have parts in another zone, so there a postal code outside those parts, or a city Waypoint knows, decides), a country with a single zone, or a city it knows. A state and ZIP code with no country named are taken only when they agree (so “Berlin, DE 10115” is never Delaware), and a province or ZIP prefix that mixes zones (northern Ontario, the East Kootenay, a few Kentucky and Tennessee ZIP prefixes) is left to a city Waypoint knows. When the address doesn’t settle it, Waypoint says so and you type the zone. The stay’s card shows the zone it uses, so a wrong guess is easy to spot and fix; an older stay saved with two different zones takes its start zone for both the next time it is edited. Confirmation emails get the same treatment when they give an address but no city it knows. Waypoint refuses a segment that ends before it starts, comparing the two at their own zones, so a flight across the date line, whose arrival is earlier on the clock than its departure, is fine.

A trip’s dates are the local dates of its first and last segments.

## How segments are grouped

Without a trip named, a new segment joins an existing grouped trip when it is within two days of it, the trip hasn’t already got back to where it began before the segment starts, and everyone the segment involves (its travellers and whoever booked it) is already on the trip. Otherwise it starts a trip of its own, so one person’s solo trip never takes in another person’s booking. You can **rename** a trip, **merge** two of yours into one and **split** some segments off into a new one; a trip you merged or split is yours from then on, and grouping leaves it alone. A merge is refused unless the same people are on both trips, so nobody is shown a segment of a trip they aren’t on.

## One flight, one card

When the same flight is booked on two reservations (a family split across two confirmation codes), each booking stays its own segment, so its change and cancellation emails, its manage link and your edits land on the right one. Waypoint shows them together: **one card per flight** (the same flight number, local departure date and airports) with the route, times and live status once, then a **Bookings** section with a block for each confirmation code: the code to tap and copy, its travellers with their loyalty numbers, and its own Edit and Remove. If the bookings disagree on the times (one was changed and the other not yet), the card says **Times differ between bookings** and shows each booking’s times in its block instead of picking one. Upcoming shows the flight once, with every code. The calendar feed has one event for the flight, listing every booking’s code, and the check-in and day-of reminders and the flight-status check count it once. Hotels and rental cars are never grouped.

## One booking, one segment

A confirmation email that arrives twice (in one mailbox, or in two household members’ mailboxes) makes one segment, not two. Waypoint matches a booking across the whole household by its kind, confirmation code (ignoring case and spaces), places and date, and its flight number however it is written (`AA 4001`, `AA4001` and `AA04001` are one flight) and the provider after tidying its name (“American Airlines Inc.” and “American Airlines” are the same). A different confirmation code on the same flight is another booking. When the email came to someone who isn’t on the booking’s trip, they are noted as having received its confirmation and see that trip: the email is already in their own mailbox, but they then see the whole trip it belongs to (every segment and traveller on it), and the same match lets their email update or cancel that booking. Nobody else gains access.

## What your edits keep

When you change a field of a segment, Waypoint remembers it was you and a later email never overwrites it. An email about a booking Waypoint already has updates that segment instead of adding another, and marks it *changed* when its times or places moved, or *cancelled* when the airline says so.

## Live status

With a RapidAPI key set, a flight’s card also shows its live status (delays, gate, terminal) beside the booked times, which it never changes. See [Live flight status](/Waypoint/start/flight-status/).

With a Logo.dev key saved in Settings, each booking also shows its airline’s, hotel’s, rental company’s or cruise line’s logo. See [Brand logos](/Waypoint/start/logos/).

## In a backup

Trips, segments and their travellers are part of a [backup](/Waypoint/start/docker/#moving-your-data-from-another-machine) and come back exactly as they were, times and zones included. The airport list isn’t: every Waypoint has it already.
