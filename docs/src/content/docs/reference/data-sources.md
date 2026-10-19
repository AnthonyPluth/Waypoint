---
title: Data sources
description: Where the airport, airline, place, highway and state-line data Waypoint ships with come from, and their licences.
sidebar:
  order: 2
---

Waypoint ships with five reference lists. They are the same for every Waypoint, aren’t part of a [backup](/Waypoint/start/docker/#moving-your-data-from-another-machine), and are never looked up from an outside service: nothing about your trips leaves the server to use them.

## Airports

Name, city, country, time zone and coordinates for each three-letter IATA code come from [OurAirports](https://ourairports.com/data/)’ public-domain data, through the [`airportsdata`](https://pypi.org/project/airportsdata/) package, which adds each airport’s time zone. The same data gives the state of each US airport and the English name of each country, which name the places in a trip’s destination.

## Airlines

Name, IATA and ICAO code and country come from [OpenFlights](https://openflights.org/data.html)’ `airlines.dat`, made available under the [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/); its contents are under the [Database Contents License](https://opendatacommons.org/licenses/dbcl/1-0/). Waypoint’s derived list keeps one airline per IATA code and is itself kept open, in this public repository, under the same ODbL, as the licence asks. See also the `NOTICE` file.

## Places

The places list turns a booking’s address into a rough point on the map ([Where a booking is on the map](/Waypoint/start/trips/#where-a-booking-is-on-the-map)). It holds the centre of each US ZIP code, Canadian postal-code area (the first three characters) and British postcode district (the part before the space), and the centre, state, country and population of each city of 15,000 people or more, for finding a city by its name. It is built from two downloads that the app never fetches:

- **US ZIP codes:** the Census Bureau’s 2023 [Gazetteer ZIP Code Tabulation Areas](https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html) (US government data, public domain). A ZCTA approximates a ZIP code, so a few ZIP codes (some PO boxes and single-building codes) have none.
- **Canadian and British postal codes, and the cities:** [GeoNames](https://www.geonames.org/), licensed under [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/). The derived list keeps GeoNames’ names and coordinates, rounded to four decimals and averaged where one code lists several places, and is credited in the `NOTICE` file.

## Highways

The highways let a road trip’s route follow the real highway network instead of a curve ([Replaying a past trip’s route](/Waypoint/start/trips/#replaying-a-past-trips-route)), without map tiles. They come from the Federal Highway Administration’s National Highway System shapefile (version 2025-08-08, from its [NHS Maps](https://www.fhwa.dot.gov/planning/national_highway_system/nhs_maps/) page), US government data that “can be freely distributed as long as this metadata entry is included”, which the `NOTICE` file does.

Waypoint keeps Interstates, and US and state routes with a plain route number that are freeways, expressways or principal arterials. Alternate, business and bypass routes, proposed and county routes, and anything unsigned or classed as a minor arterial or lower are left out. The list is simplified to about 100 metres, and the app loads it the first time a trip’s map needs it.

- **What the map receives.** Only the roads: the points and names of the highways a drive follows and those near it, coarsened to about a kilometre. Never anything about who travels or what was booked.
- **How a route is chosen.** The shortest path, counting a mile on a US highway as 1.35 miles and on a state route as 1.7, so a drive stays on an interstate unless another road is much shorter.
- **Limits.** The network is coarse, so a route can be a few miles off the road or skip a short link that isn’t an interstate, US highway or numbered state route. It knows nothing of closures, tolls or traffic. The mainland, Alaska, Hawaii, Puerto Rico and a few gaps are separate networks: a drive is routed over one, and a drive between two keeps its curve.
- **Return drives.** A drive back over ground a trip already covered reuses the earlier drive’s line, so the map receives nothing new for it.

## State lines

The faint dashed borders between US states that the route replay draws once the map is close enough ([Replaying a past trip’s route](/Waypoint/start/trips/#replaying-a-past-trips-route)) come from the Census Bureau’s 2024 Cartographic Boundary File for States and Equivalent Entities, at 1:5,000,000 (from its [Cartographic Boundary Files](https://www.census.gov/geographies/mapping-files/time-series/geo/cartographic-boundary.html) page). Its metadata gives “Access constraints: None”: it is public domain, with no licence terms or required credit.

Only the lines between two states are kept. The coast, the Great Lakes shores and the borders with Canada and Mexico are left out, since the map’s land layer already draws them, and Puerto Rico has no neighbour so it has no line. The lines are simplified to about a kilometre.

- **What the map receives.** Only coordinates: the pieces of line inside the area the replay can show for that trip, at most 1,500 steps (thinned, never a whole line dropped) and rounded to about a hundred metres. Never a state’s name or anything about who travels or what was booked. A trip with no place in the United States gets none.
- **Accuracy.** The lines look right at the replay’s zoom but are not a survey, and a river border can be off by a mile or so.
