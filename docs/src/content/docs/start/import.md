---
title: Import past flights
description: Add the flights you took before Waypoint from a CSV exported by Flighty, myFlightRadar24, OpenFlights or App in the Air.
sidebar:
  order: 6
---

**Settings → Backup & import → Import past flights** adds flights from another app’s CSV export, so they show on the [Trips](/Waypoint/start/trips/) page and count in distance and time travelled. You choose the file, check each row, say who was on the flights, and only then are the new ones added.

## What it reads

Waypoint recognises the export from its header row. A file whose columns match none of the four is refused with a message naming them.

| App | Where the export is | Columns read |
| --- | --- | --- |
| **Flighty** | Flighty’s export | Date, Airline, Flight, From, To, take-off, landing and gate times, Canceled, Seat, Cabin Class |
| **myFlightRadar24** | My Flights → Export | Date, Flight number, From, To, Dep time, Arr time, Airline, Seat number, Flight class |
| **OpenFlights** | My Flights → Export | Date, From, To, Flight_Number, Airline, Seat, Class |
| **App in the Air** | its flight export | Date, Flight, From, To, Departure, Arrival, Airline, Seat, Class |

Only the flight itself is read: its day, flight number, airline, the two airports, the times, the seat, the cabin and, when it is one Waypoint knows, the aircraft type. Notes, booking references and anything else in the file are never looked at, so they can’t be kept.

:::caution
These layouts come from what each app is documented or commonly reported to export, not from export files checked against the apps. A column named differently is read as empty: the flight is still imported, without that time or seat. If an export doesn’t import as you’d expect, [open an issue](https://github.com/AnthonyPluth/Waypoint/issues) describing its header row (not its flights).
:::

Airports are read as three-letter IATA codes, or an airport’s name with its code in brackets, as myFlightRadar24 writes them. A row with an airport Waypoint doesn’t know, or with only a four-letter ICAO code, can’t be read, and the preview says which airport.

## The preview

Nothing is saved when you choose the file. Each row is shown as a flight and marked:

- **New**: it will be added.
- **Already in Waypoint**: you already have the same flight number on that day, or the same route on that day. A flight repeated in the file counts once, and a cancelled segment doesn’t count.
- **Can’t read**: with why, such as an unknown airport, a date that isn’t a day or a flight the app marks cancelled.

Page through every row, search by airport, flight number, airline, date or line number, or use **Problems only** to jump to the rows that can’t be read. Untick a new flight to leave it out; the button says how many will be added.

Then choose **who was on these flights**: you by default, or anyone in [People](/Waypoint/start/people/). The new flights become segments from an import, booked by you, and are grouped into trips by the usual [grouping](/Waypoint/start/trips/#how-segments-are-grouped). As with any trip, you and the people you chose see them, and nobody else.

Importing the same file again adds nothing. If saving stops part-way, the flights already added are marked **Added**, and pressing the button again sends only the rest, so a retry never duplicates a flight.

## Times

Times are the times at the airports, as everywhere in Waypoint. A time with an offset (Flighty writes one) is put at its airport’s own zone; one without is taken to be the airport’s already. An arrival that gives only a time of day (myFlightRadar24) is put on the first day it can be after the departure.

When the file has no times for a flight, they stay empty. The flight shows its day and “time not recorded”, and counts toward distance but not time in the air. In the calendar feed it is an all-day event, it gets no check-in reminder, and live flight status skips it.

## The file isn’t kept

The file is read in memory for the preview and dropped. Saving sends back only the flights you’re adding, and the file itself is never stored or logged. A file can be up to 5 MB and 10,000 rows; past that, Waypoint asks you to split it.
