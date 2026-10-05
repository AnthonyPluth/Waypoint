---
title: Travel stats
description: What Waypoint counts for a person or the household (flights, distance, airlines, hotel nights, rental days, places), and what it leaves out.
sidebar:
  order: 6
---

Waypoint adds up what you have flown, stayed and driven. The numbers come from `GET /api/stats?person=<id|all>&year=<yyyy|all>`; the Stats page shows them, starting with the map.

## Who and when

- **Person**: one person’s stats (a member or a guest) count the segments they are a traveller on. `all` is the whole household: each segment counts once, however many of you were on it.
- **Only trips you can see.** Stats are worked out from the trips you can see (see [Trips](/waypoint/start/trips/)), so your partner’s view of your stats never includes your solo work trips, and a person’s stats include a trip they share with a guest.
- **Year**: a calendar year in the places themselves (a flight belongs to the year it departs, by the departure airport’s clock), or `all` for a lifetime.
- **Finished and not cancelled.** A segment counts once its end, at its own place’s clock, has passed. Cancelled segments never count.

## What is counted

- **Flights**: how many, the distance (great-circle between the airports), and the time in the air (booked departure to booked arrival, each at its own zone, so a flight over the date line or overnight is right). Airports visited (each departure and arrival), airlines flown, countries, top routes (A–B and B–A are one route), cabins, your most flown seat, and the share of window, aisle and middle seats; the longest and shortest flights, the most-visited airport and the busiest month; and the distance as times around the Earth (40,075 km) and as a fraction of the way to the Moon (384,400 km). An airport Waypoint doesn’t have still counts as a flight, but adds no distance or country.
- **Seats**: the letter places a seat on the common layouts: A, F and K are by the window, C, D, G and H are aisle seats, B, E and J are in the middle. Any seat that rule can’t place is “unknown”.
- **Hotels**: nights away (each night once, however many stays overlap it), the chains (the booking’s provider), and the cities and countries stayed in when the booking names a place Waypoint can find.
- **Rental cars**: days with a car out, each day once, and the companies.
- **Places**: the countries and cities from flights and hotels together, with the date of the first visit.

Distances are worked out in kilometres. The household’s display unit is a setting (`distance_unit`, miles unless it is `km`), which the reply carries for the page to apply.

## Airline names

A flight’s airline comes from the two-character code its flight number starts with, named from [OpenFlights](/waypoint/reference/data-sources/); a code that isn’t in the list shows as the code.

## The map

The Stats page draws a world map of everywhere you have flown: an arc for each route (thicker for more flights), a dot for each airport (bigger for more visits), and the countries that hold one of your airports shaded. Tap or hover a dot or an arc for its name and count; drag, pinch or use the buttons to zoom, and Reset to see the whole world again. Hotel cities without an airport aren’t plotted, and neither is an airport Waypoint doesn’t have coordinates for.

The map is drawn on your device from country outlines bundled with the app ([Natural Earth](https://www.naturalearthdata.com/), public domain, through the `world-atlas` package). It loads no tiles and calls no map service, so no one outside learns where the household goes. Its code and outlines are downloaded only when you open the Stats page.
