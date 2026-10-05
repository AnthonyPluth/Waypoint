---
title: Trips
description: How Waypoint keeps your flights, hotels, rental cars and trains, who sees a trip, and why times are shown where they happen.
sidebar:
  order: 4
---

A **trip** is a journey. It holds **segments**: one flight leg, hotel stay, car rental or train each. You can add them by hand, and Waypoint adds them from the booking emails in a connected Gmail (see [Scanning](/waypoint/start/gmail/#scanning)).

## Who sees a trip

You see a trip when you are travelling on any of its segments, or when you booked it (the trip, or any of its segments). Nobody else sees it, however they ask: its address answers “not found”, the same as a trip that doesn’t exist. A solo work trip stays its traveller’s. If you book a trip for a guest (a child, a grandparent), you see it because you booked it. Add someone as a traveller on a segment and the whole trip is shared with them.

Without sign-in, on your own machine, everyone is the one local household, which sees every trip.

## Segments

Each segment has a kind (flight, hotel, car or train), a status (confirmed, changed or cancelled), a confirmation code, the provider, a start and an end, where it starts and ends, a link to manage the booking, and details: flight number, terminal, seat, cabin, room, car class, address and phone. The **travellers** are people from [People](/waypoint/start/people/), or, until a name on a booking is matched to a person, the name as printed.

A segment is added to a trip you name, or without one: Waypoint puts it in the trip it belongs to (see below) or makes a new trip.

## Times are where they happen

A segment’s times are the wall-clock times at its places, stored with the place’s time zone (an IANA name such as `Pacific/Auckland`). Waypoint never converts them to the server’s time zone or to UTC: a 22:15 departure from Auckland is 22:15 in Auckland, and the arrival that is the same day in Los Angeles is shown at its own local time. Type a time as it appears on the booking, like `2026-03-01T22:15`, without an offset. A flight’s zones come from its airports (Waypoint knows the airports by their three-letter code); name the zone yourself for a place that isn’t on the list. Waypoint refuses a segment that ends before it starts, comparing the two at their own zones, so a flight across the date line, whose arrival is earlier on the clock than its departure, is fine.

A trip’s dates are the local dates of its first and last segments.

## How segments are grouped

Without a trip named, a new segment joins an existing grouped trip when it is within two days of it, the trip hasn’t already got back to where it began before the segment starts, and everyone the segment involves (its travellers and whoever booked it) is already on the trip. Otherwise it starts a trip of its own, so one person’s solo trip never takes in another person’s booking. You can **rename** a trip, **merge** two of yours into one and **split** some segments off into a new one; a trip you merged or split is yours from then on, and grouping leaves it alone. A merge is refused unless the same people are on both trips, so nobody is shown a segment of a trip they aren’t on.

## What your edits keep

When you change a field of a segment, Waypoint remembers it was you and a later email never overwrites it. An email about a booking Waypoint already has updates that segment instead of adding another, and marks it *changed* when its times or places moved, or *cancelled* when the airline says so.

## In a backup

Trips, segments and their travellers are part of a [backup](/waypoint/start/docker/#moving-your-data-from-another-machine) and come back exactly as they were, times and zones included. The airport list isn’t: every Waypoint has it already.
