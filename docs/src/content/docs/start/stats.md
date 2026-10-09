---
title: Travel stats
description: What Waypoint counts for a person or the household (flights, distance, airlines, hotel nights, rental days, cruises, places), and what it leaves out.
sidebar:
  order: 6
---

Waypoint adds up what you have flown, stayed and driven. The numbers come from `GET /api/stats?person=<id|all>&year=<yyyy|all>`; the Stats page (`#stats`) shows them, and so does the [map](#the-map).

## The Stats page

Pick **who** (you by default, any member or guest, or Everyone) and **when** (All time, or a year that has something to count); the choice is kept in the address, so you can link it. The page is in sections: **Where you’ve been** (the map and the countries), then **Flights**, **Hotels**, **Cars** and **Cruises**, each with its own big numbers and top five lists (Show all lists the rest), and, for flights and hotels, records. Flights also show how far that is around the Earth and toward the Moon, and your cabin and seat split. A section you have nothing finished for isn’t shown. A person or year with nothing finished says so, with links to add a trip or import past flights.

Miles or kilometres is a household setting, under **Settings → Travel → Distances** (`GET` and `POST /api/distance-unit`).

## Who and when

- **Person**: one person’s stats (a member or a guest) count the segments they are a traveller on. `all` is the whole household: each segment counts once, however many of you were on it.
- **Only trips you can see.** Stats are worked out from the trips you can see (see [Trips](/Waypoint/start/trips/)), so your partner’s view of your stats never includes your solo work trips, and a person’s stats include a trip they share with a guest.
- **Year**: a calendar year in the places themselves (a flight belongs to the year it departs, by the departure airport’s clock), or `all` for a lifetime.
- **Finished and not cancelled.** A segment counts once its end, at its own place’s clock, has passed. Cancelled segments never count.

## What is counted

- **Flights**: how many, the distance (great-circle between the airports), and the time in the air (booked departure to booked arrival, each at its own zone, so a flight over the date line or overnight is right). Airports visited (the times you were there: its arrivals or its departures, whichever are more, so a round trip is one visit to each end, and a connection is one), airlines flown, countries, top routes (A–B and B–A are one route), cabins (grouped by the words in the fare: “Basic Economy”, “Main Basic” and “Tango Plus” are Economy; Premium Economy, Business and First are kept apart; a name with none of those words shows as written), your most flown seat, and the share of window, aisle and middle seats; the longest and shortest flights, the most-visited airport and the busiest month; and the distance as times around the Earth (40,075 km) and as a fraction of the way to the Moon (384,400 km). An airport Waypoint doesn’t have still counts as a flight, but adds no distance or country.
- **Seats**: a seat’s position comes from the best evidence Waypoint has. First the word the airline’s email prints with the seat (“Window”, “Aisle” or “Middle”), which applies to the seat entered on the booking. Otherwise the aircraft’s layout: when the booking knows its aircraft (from the email, an import, or the live flight status) and the cabin is economy (or not known), the seat letter is looked up for the Airbus A320 family and A350 and the Boeing 737, 757, 777 and 787, so 12F is a window on a 737 and a middle seat on a 777. Seat A is a window on every layout. Anything else is “unknown”: other aircraft, premium cabins (airlines letter them differently) and letters a layout doesn’t have. Aircraft types are used only for this and for the small text beside the flight number. Each traveller’s own seat is counted: your stats count your seat on a flight, and Everyone’s count every traveller’s (a flight itself is still counted once). A flight none of whose travellers has a seat uses the seat entered on the booking, once, and one with none at all is “unknown”.
- **Hotels**: nights away (each night once, however many stays overlap it), the chains (the hotel’s brand when its name says one: a Westin counts for Marriott and a Grand Hyatt for Hyatt, whoever sold the stay; otherwise the booking’s provider, unless that is a booking site such as Expedia or Capital One Travel, or only the hotel’s own name, and then there is none), and the cities and countries stayed in when the booking names a place Waypoint can find.
- **Stays**: how many stays had at least one night (a same-day stay isn’t counted), the average stay in nights, and how many different hotels. The **Hotels** and **Cities stayed in** lists rank them by nights, with the number of stays; hotels and cities are matched by name ignoring case and extra spaces, shown as first written, and a stay with no name or no city is left out of that list. The records add the longest stay, the most-visited hotel and city (most stays, then most nights) and the month with the most nights away. A year counts the nights that fall in it, so a stay over New Year counts in both.
- **Rental cars**: days with a car out, each day once, and the companies (a booking site and number an email put in brackets after the name, like “Hertz (booked via Hotwire 1234567890)”, is dropped).
- **Cruises**: how many, the nights aboard (each night once, however many cruises overlap it), the **sea days** and the ports of call, and the cruise lines. A sea day is a date strictly between embarking and disembarking on which the ship has no port arrival, so a day in port (from the date it arrives to the date it leaves) isn’t one, and neither are the days of embarking and disembarking. A port with no times is counted as a port but takes no day out of the sea days. A cruise counts in the year its nights fall in, once it has finished.
- **Places**: the countries and cities from flights and hotels together, with the date of the first visit and the number of visits: each time you arrived from somewhere else (or left, for a place you only ever flew out of), so a round trip is one visit and hops inside a country aren’t visits to it; hotel stays in a city back to back (or overlapping) are one visit.

Distances are worked out in kilometres. The household’s display unit is a setting (`distance_unit`, miles unless it is `km`), which the reply carries for the page to apply.

## Airline names

A flight’s airline comes from the two-character code its flight number starts with, named from [OpenFlights](/Waypoint/reference/data-sources/); a code that isn’t in the list shows as the code.

## The map

The Stats page draws a world map of everywhere you have flown and stayed, for the same person and year as the rest of the page: an arc for each route (thicker for more flights), a dot for each airport (bigger for more visits), a small diamond for each city you stayed in, and the countries that hold one of those shaded. The United States is shaded state by state: a state is filled when one of your airports or hotel cities is in it, and the rest of the country is not.

Tap or hover a dot, an arc or a diamond for its name and count. Tap an arc or a diamond and the trips on it are listed under the map, each with its name (a link to the trip) and when it happened: a flight’s dates for a route, check-in to check-out for a stay. A stay is placed at the city, roughly where that city’s airports are, never at the hotel’s address; a city with no airport Waypoint knows isn’t plotted, and neither is an airport Waypoint doesn’t have coordinates for. The map opens zoomed to just the places you have been (the whole world when they span it), and follows the person and year you pick; drag, pinch or use the buttons to zoom, **Reset** to go back to that view and **World** to see the whole world.

The map is drawn on your device from outlines bundled with the app: countries from [Natural Earth](https://www.naturalearthdata.com/) (public domain, through the `world-atlas` package) and US states from the Census Bureau (public domain, through `us-atlas`). It loads no tiles and calls no map service, so no one outside learns where the household goes. Its code and outlines are downloaded only when you open the Stats page.

## Year in review

Pick a person and a year and the Stats page offers **See your year in review**: a short run of full-screen cards (distance and how it compares, flights and time in the air, countries and the ones new that year, the top route and airport, nights away, the map) and a last card to share. It is offered from December 1 for the current year, and any time for past years.

The picture to share is made on your device, drawn to an image in the browser, and handed to your phone’s share sheet (or saved to your downloads where the browser can’t share a file). Nothing is uploaded. It shows the year, the totals, the top route as airport codes, the countries and the map, and leaves out names, confirmation codes, loyalty numbers, exact dates and hotel names. The first name of the person whose year it is appears on it only if you tick **Show the first name**.
