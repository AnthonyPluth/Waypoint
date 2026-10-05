---
title: Trips
description: How Waypoint keeps your flights, hotels, rental cars and trains, who sees a trip, and why times are shown where they happen.
sidebar:
  order: 4
---

A **trip** is a journey. It holds **segments**: one flight leg, hotel stay, car rental or train each. You can add them by hand, and Waypoint adds them from the booking emails in a connected Gmail (see [Scanning](/waypoint/start/gmail/#scanning)).

## The pages

- **Upcoming** leads with a card for what is next: a countdown, the flight number, departure time and terminal (or a hotel’s address and check-in time), and the confirmation code, which you tap to copy. A flight in the air or a rental car out counts as under way and leads until it ends; a hotel stay in progress doesn’t push the day’s flight aside. Below it, the trip that card belongs to (or the next one, when you aren’t travelling) is laid out day by day. Cancelled segments never lead.
- **Trips** lists the trips you can see: the ones still to come or under way, and the past ones. Pick a traveller to see only their trips; the choice is kept in the address (`#trips?who=…`) so you can bookmark it.
- A **trip** page shows each segment as a card with its local times, travellers and the loyalty number each traveller would use for that airline or hotel chain, masked. Tap a number to show it and copy it; tap again to hide it. When a traveller has no number for the program a booking is with, the card says so and links to [People](/waypoint/start/people/); a traveller known only by their printed name is marked as not matched to a person yet. Waypoint tells the program from the provider’s name (“American Airlines” is American AAdvantage), so write the provider the way the airline or chain does.

Add a booking from Trips (Waypoint puts it in the trip it belongs to, or starts one) or from a trip page (it goes in that trip), edit any segment, or remove it. A save that fails keeps everything you typed and says why; a page that can’t reload its trips shows an error with Try again, not the old trips as if they were current.

## Times beside yours

A segment’s time is always shown as it is at the place. When your own time zone has a different offset at that moment, your time for the same moment follows it in brackets: `7:00 PM [4:00 PM PST]`. It is only a second reading; nothing is converted or stored in your zone.

## Who sees a trip

You see a trip when you are travelling on any of its segments, when you booked it (the trip, or any of its segments), or when the confirmation of one of its bookings came to your own connected mailbox (see [One booking, one segment](#one-booking-one-segment)). Nobody else sees it, however they ask: its address answers “not found”, the same as a trip that doesn’t exist. A solo work trip stays its traveller’s. If you book a trip for a guest (a child, a grandparent), you see it because you booked it. Add someone as a traveller on a segment and the whole trip is shared with them.

Without sign-in, on your own machine, everyone is the one local household, which sees every trip.

## Segments

Each segment has a kind (flight, hotel, car or train), a status (confirmed, changed or cancelled), a confirmation code, the provider, a start and an end, where it starts and ends, a link to manage the booking, and details: flight number, terminal, seat, cabin, room, car class, address and phone. The **travellers** are people from [People](/waypoint/start/people/), or, until a name on a booking is matched to a person, the name as printed.

A segment is added to a trip you name, or without one: Waypoint puts it in the trip it belongs to (see below) or makes a new trip.

## Actions on a booking

Each booking card has buttons for what you'd do next:

- **Open in app**: the booking's manage link (from the email, or one you entered). It's a link on the provider's own website; on an iPhone or Android phone it says **Open in app** and the provider's app opens it if installed; on a computer it says **Manage booking** and opens the provider's website. Only https links are offered. A cancelled booking keeps this one (you may need it for a refund) and loses the others. Waypoint doesn't build prefilled manage links for any provider yet, because it only adds one once its URL is confirmed from the provider's public site.
- **Wallet**: on an iPhone or iPad only. It opens the Wallet app itself; no link opens one pass.
- **Directions**: an Apple Maps link to a hotel's or rental's address (or its place name when there's no address).
- **Call**: dials the phone number on the booking, when it has one.

## Times are where they happen

A segment’s times are the wall-clock times at its places, stored with the place’s time zone (an IANA name such as `Pacific/Auckland`). Waypoint never converts them to the server’s time zone or to UTC: a 22:15 departure from Auckland is 22:15 in Auckland, and the arrival that is the same day in Los Angeles is shown at its own local time. Type a time as it appears on the booking, like `2026-03-01T22:15`, without an offset. A flight’s zones come from its airports (Waypoint knows the airports by their three-letter code); name the zone yourself for a place that isn’t on the list. Waypoint refuses a segment that ends before it starts, comparing the two at their own zones, so a flight across the date line, whose arrival is earlier on the clock than its departure, is fine.

A trip’s dates are the local dates of its first and last segments.

## How segments are grouped

Without a trip named, a new segment joins an existing grouped trip when it is within two days of it, the trip hasn’t already got back to where it began before the segment starts, and everyone the segment involves (its travellers and whoever booked it) is already on the trip. Otherwise it starts a trip of its own, so one person’s solo trip never takes in another person’s booking. You can **rename** a trip, **merge** two of yours into one and **split** some segments off into a new one; a trip you merged or split is yours from then on, and grouping leaves it alone. A merge is refused unless the same people are on both trips, so nobody is shown a segment of a trip they aren’t on.

## One flight, one card

When the same flight is booked on two reservations (a family split across two confirmation codes), each booking stays its own segment, so its change and cancellation emails, its manage link and your edits land on the right one. Waypoint shows them together: **one card per flight** (the same flight number, local departure date and airports) with the route, times and live status once, then a **Bookings** section with a block for each confirmation code: the code to tap and copy, its travellers with their loyalty numbers, and its own Edit and Remove. If the bookings disagree on the times (one was changed and the other not yet), the card says **Times differ between bookings** and shows each booking’s times in its block instead of picking one. Upcoming shows the flight once, with every code. The calendar feed has one event for the flight, listing every booking’s code, and the check-in and day-of reminders and the flight-status check count it once. Hotels and rental cars are never grouped.

## One booking, one segment

A confirmation email that arrives twice (in one mailbox, or in two household members’ mailboxes) makes one segment, not two. Waypoint matches a booking across the whole household by its kind, confirmation code (ignoring case and spaces), places and date, and its flight number however it is written (`AA 4001`, `AA4001` and `AA04001` are one flight) and the provider after tidying its name (“American Airlines Inc.” and “American Airlines” are the same). A different confirmation code on the same flight is another booking. When the email came to someone who isn’t on the booking’s trip, they are noted as having received its confirmation and see that trip: the email is already in their own mailbox, so this shows them nothing new, and nobody else gains access.

## What your edits keep

When you change a field of a segment, Waypoint remembers it was you and a later email never overwrites it. A segment you have edited is marked **Edited by you** on its card. An email about a booking Waypoint already has updates that segment instead of adding another, and marks it *changed* when its times or places moved, or *cancelled* when the airline says so.

## Live status

With a RapidAPI key set, a flight’s card also shows its live status (delays, gate, terminal) beside the booked times, which it never changes. See [Live flight status](/waypoint/start/flight-status/).

## In a backup

Trips, segments and their travellers are part of a [backup](/waypoint/start/docker/#moving-your-data-from-another-machine) and come back exactly as they were, times and zones included. The airport list isn’t: every Waypoint has it already.
