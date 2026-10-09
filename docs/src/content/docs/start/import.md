---
title: Import past flights
description: Add the flights you took before Waypoint from a CSV exported by Flighty, myFlightRadar24, OpenFlights or App in the Air.
sidebar:
  order: 6
---

**Settings → Travel → Import past flights** adds flights from another app’s CSV export, so they show on the [Trips](/Waypoint/start/trips/) page and count in distance and time travelled. You choose the file, see each row as a flight, say who was on them, and only then are the new ones added.

## What it reads

Waypoint recognises the export from its header row. A file whose columns match none of them is refused with a message naming the four.

| App | Where the export is | Columns Waypoint reads |
| --- | --- | --- |
| **Flighty** | Flighty’s export | Date, Airline, Flight, From, To, the gate and take-off times (actual before scheduled), Landing and Gate Arrival times, Canceled, Seat, Cabin Class |
| **myFlightRadar24** | My Flights → Export | Date, Flight number, From, To, Dep time, Arr time, Airline, Seat number, Flight class |
| **OpenFlights** | My Flights → Export | Date (with the time of day when it has one), From, To, Flight_Number, Airline, Seat, Class |
| **App in the Air** | its flight export | Date, Flight, From, To, Departure, Arrival, Airline, Seat, Class |

Only the flight itself is read: its day, flight number, airline, the two airports, the times, the seat, the cabin and the aircraft type (from Flighty’s Aircraft Type Name, myFlightRadar24’s Aircraft and OpenFlights’ Plane columns, kept when it is one Waypoint knows). Notes columns, booking references and anything else in the file are never looked at, so they can’t be kept.

:::caution
These layouts come from what each app is documented or commonly reported to export. No export file from the apps themselves was available to check them against, and for **App in the Air** in particular no published description of its export was found, so its columns are a best reading of its flights list. A column named differently from the table is read as empty: the flight is still imported, without that time or seat. If an export of yours doesn’t import as you’d expect, [open an issue](https://github.com/AnthonyPluth/Waypoint/issues) describing its header row (not its flights).
:::

Airports are read as three-letter IATA codes (or an airport’s name with its code in brackets, as myFlightRadar24 writes them). A row with an airport Waypoint doesn’t know, or with only a four-letter ICAO code, is shown as one that can’t be read, and says which airport.

## The preview

Nothing is saved when you choose the file. Each row is shown as a flight and marked:

- **New**: it will be added.
- **Already in Waypoint**: you already have a flight with the same flight number on that day, or the same route on that day (a flight repeated in the file counts once). A cancelled segment doesn’t count.
- **Can’t read**: with why (an unknown airport, a date that isn’t a day, a flight the app marks cancelled).

Then you choose **who was on these flights**: you by default, or anyone in [People](/Waypoint/start/people/). The new flights become segments from an import, booked by you, and grouped into trips by the usual [grouping](/Waypoint/start/trips/#how-segments-are-grouped). As with any trip, you and the people you chose see them, and nobody else.

Importing the same file again adds nothing.

## Times

A flight’s times are the times at its airports, as everywhere in Waypoint. A time that comes with an offset (Flighty writes ISO times with one) is put at its airport’s own zone; one without is taken to be the airport’s already. An arrival that gives only a time of day (myFlightRadar24) is put on the first day it can be after the departure.

When the file has no times for a flight, they’re left empty: the flight shows its day and “time not recorded”, and counts toward distance (it has airports) but not toward time in the air. In the calendar feed it is an all-day event, it gets no check-in reminder, the day-of summary says “Time not recorded”, and live flight status skips it.

## The file isn’t kept

The file is read in memory for the preview and dropped. Saving sends back only the flights you’re adding, a thousand at a time; the file itself is never stored or logged. A file can be up to 5 MB and 10,000 rows; past that, Waypoint says so and asks you to split it.
