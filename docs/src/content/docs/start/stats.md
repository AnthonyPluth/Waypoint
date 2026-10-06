---
title: Travel stats
description: What Waypoint counts for a person or the household (flights, distance, airlines, hotel nights, rental days, cruises, places), and what it leaves out.
sidebar:
  order: 6
---

Waypoint adds up what you have flown, stayed and driven. The numbers come from `GET /api/stats?person=<id|all>&year=<yyyy|all>`; the Stats page (`#stats`) shows them, and so does the [map](#the-map).

## The Stats page

Pick **who** (you by default, any member or guest, or Everyone) and **when** (All time, or a year that has something to count); the choice is kept in the address, so you can link it. The page shows the big numbers, how far that is around the Earth and toward the Moon, the top five of routes, airports, airlines, countries, hotel chains and rental companies (Show all lists the rest), records, and your cabin and seat split. A person or year with nothing finished says so, with links to add a trip or import past flights.

Miles or kilometres is a household setting, under **Settings → Travel → Distances** (`GET` and `POST /api/distance-unit`).

## Who and when

- **Person**: one person’s stats (a member or a guest) count the segments they are a traveller on. `all` is the whole household: each segment counts once, however many of you were on it.
- **Only trips you can see.** Stats are worked out from the trips you can see (see [Trips](/Waypoint/start/trips/)), so your partner’s view of your stats never includes your solo work trips, and a person’s stats include a trip they share with a guest.
- **Year**: a calendar year in the places themselves (a flight belongs to the year it departs, by the departure airport’s clock), or `all` for a lifetime.
- **Finished and not cancelled.** A segment counts once its end, at its own place’s clock, has passed. Cancelled segments never count.

## What is counted

- **Flights**: how many, the distance (great-circle between the airports), and the time in the air (booked departure to booked arrival, each at its own zone, so a flight over the date line or overnight is right). Airports visited (each departure and arrival), airlines flown, countries, top routes (A–B and B–A are one route), cabins, your most flown seat, and the share of window, aisle and middle seats; the longest and shortest flights, the most-visited airport and the busiest month; and the distance as times around the Earth (40,075 km) and as a fraction of the way to the Moon (384,400 km). An airport Waypoint doesn’t have still counts as a flight, but adds no distance or country.
- **Seats**: the letter places a seat on the common layouts: A, F and K are by the window, C, D, G and H are aisle seats, B, E and J are in the middle. Any seat that rule can’t place is “unknown”. Each traveller’s own seat is counted: your stats count your seat on a flight, and Everyone’s count every traveller’s (a flight itself is still counted once). A flight none of whose travellers has a seat uses the seat entered on the booking, once, and one with none at all is “unknown”.
- **Hotels**: nights away (each night once, however many stays overlap it), the chains (the hotel’s brand when its name says one: a Westin counts for Marriott and a Grand Hyatt for Hyatt, whoever sold the stay; otherwise the booking’s provider, unless that is a booking site such as Expedia or Capital One Travel, or only the hotel’s own name, and then there is none), and the cities and countries stayed in when the booking names a place Waypoint can find.
- **Stays**: how many stays had at least one night (a same-day stay isn’t counted), the average stay in nights, and how many different hotels. The **Hotels** and **Cities stayed in** lists rank them by nights, with the number of stays; hotels and cities are matched by name ignoring case and extra spaces, shown as first written, and a stay with no name or no city is left out of that list. The records add the longest stay, the most-visited hotel and city (most stays, then most nights) and the month with the most nights away. A year counts the nights that fall in it, so a stay over New Year counts in both.
- **Rental cars**: days with a car out, each day once, and the companies (a booking site and number an email put in brackets after the name, like “Hertz (booked via Hotwire 1234567890)”, is dropped).
- **Cruises**: how many, the nights aboard (each night once, however many cruises overlap it), the **sea days** and the ports of call, and the cruise lines. A sea day is a date strictly between embarking and disembarking on which the ship has no port arrival, so a day in port (from the date it arrives to the date it leaves) isn’t one, and neither are the days of embarking and disembarking. A port with no times is counted as a port but takes no day out of the sea days. A cruise counts in the year its nights fall in, once it has finished.
- **Places**: the countries and cities from flights and hotels together, with the date of the first visit.

Distances are worked out in kilometres. The household’s display unit is a setting (`distance_unit`, miles unless it is `km`), which the reply carries for the page to apply.

## Airline names

A flight’s airline comes from the two-character code its flight number starts with, named from [OpenFlights](/Waypoint/reference/data-sources/); a code that isn’t in the list shows as the code.

## The map

The Stats page draws a world map of everywhere you have flown, for the same person and year as the rest of the page: an arc for each route (thicker for more flights), a dot for each airport (bigger for more visits), and the countries that hold one of your airports shaded. Tap or hover a dot or an arc for its name and count; The map opens zoomed to just the places you have flown (the whole world when they span it), and follows the person and year you pick; drag, pinch or use the buttons to zoom, **Reset** to go back to that view and **World** to see the whole world. Hotel cities without an airport aren’t plotted, and neither is an airport Waypoint doesn’t have coordinates for.

The map is drawn on your device from country outlines bundled with the app ([Natural Earth](https://www.naturalearthdata.com/), public domain, through the `world-atlas` package). It loads no tiles and calls no map service, so no one outside learns where the household goes. Its code and outlines are downloaded only when you open the Stats page.

## Year in review

Pick a person and a year and the Stats page offers **See your year in review**: a short run of full-screen cards (distance and how it compares, flights and time in the air, countries and the ones new that year, the top route and airport, nights away, the map) and a last card to share. It is offered from December 1 for the current year, and any time for past years.

The picture to share is made on your device, drawn to an image in the browser, and handed to your phone’s share sheet (or saved to your downloads where the browser can’t share a file). Nothing is uploaded. It shows the year, the totals, the top route as airport codes, the countries and the map, and leaves out names, confirmation codes, loyalty numbers, exact dates and hotel names. The first name of the person whose year it is appears on it only if you tick **Show the first name**.
