---
title: Data sources
description: Where the airport, airline, place and interstate data Waypoint ships with come from, and their licences.
sidebar:
  order: 2
---

Waypoint ships with four reference lists. The airports and airlines are loaded into the database by its migrations; the places list and the interstates are read from their files. They are the same for every Waypoint, and aren’t part of a [backup](/Waypoint/start/docker/#moving-your-data-from-another-machine).

## Airports

The airports (name, city, country, time zone and coordinates, by three-letter IATA code) come from [OurAirports](https://ourairports.com/data/)’ public-domain data, through the [`airportsdata`](https://pypi.org/project/airportsdata/) package, which adds each airport’s time zone. `tools/airports.py` writes `waypoint/storage/airports.tsv.gz`. It also writes `waypoint/storage/regions.tsv.gz` from the same data: the state of each US airport and the English name of each country, which name the places in a trip’s destination (country names come from the system’s ISO 3166 list, with a few shortened).

## Airlines

The airlines (name, IATA and ICAO code, country) come from [OpenFlights](https://openflights.org/data.html)’ `airlines.dat`, which is made available under the [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/); its contents are under the [Database Contents License](https://opendatacommons.org/licenses/dbcl/1-0/). `tools/airlines.py` writes `waypoint/storage/airlines.tsv.gz`, one airline per IATA code. That derived file is itself a database made from OpenFlights’ and is kept open, in this public repository, under the same ODbL, as the licence asks. See also the `NOTICE` file.

## Places

The places list turns a booking’s address into a rough point on the map without asking any outside service ([Where a booking is on the map](/Waypoint/start/trips/#where-a-booking-is-on-the-map)). It holds the centre of each US ZIP code, of each Canadian postal-code area (the first three characters) and of each British postcode district (the part before the space), and the centre, state, country and population of each city of 15,000 people or more, for finding a city by its name. `tools/places.py` writes `waypoint/storage/places.tsv.gz` from these downloads, which are not fetched by the app:

- US ZIP codes: the Census Bureau’s [2023 Gazetteer ZIP Code Tabulation Areas](https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html) file (US government data, public domain). A ZCTA is the Bureau’s approximation of a ZIP code, so a few ZIP codes (some PO boxes and single-building codes) have none.
- Canadian and British postal codes, and the cities: [GeoNames](https://www.geonames.org/) (`GB.zip`, `CA.zip` and `cities15000.zip` from its download server), licensed under [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/). The derived file keeps GeoNames’ names and coordinates, rounded to four decimals, with the British and Canadian codes averaged where GeoNames lists several places for one code, and is credited in the `NOTICE` file.

## Interstates

The interstates let a road trip’s route follow the real highway network instead of a curve ([Replaying a past trip’s route](/Waypoint/start/trips/#replaying-a-past-trips-route)), without asking any outside service or fetching map tiles. The list is the Interstate Highway System as the Federal Highway Administration (US Department of Transportation) publishes it in its National Highway System shapefile, version 2025-08-08, from the [NHS Maps](https://www.fhwa.dot.gov/planning/national_highway_system/nhs_maps/) page (`nhs_2025-08-08.zip`, about 110 MB, not fetched by the app). It is US government data, and its metadata says the database or any portion of it “can be freely distributed as long as this metadata entry is included”, which the `NOTICE` file does. Only the features signed as an Interstate (`SIGNT1` = `I`) and classed as one (`FCLASS` = 1) are kept, 73,431 of the file’s 492,005; business routes, proposed routes and other highways are left out.

`tools/roads.py` writes `waypoint/storage/roads.tsv.gz` (about 470 KB) from that download; run it with the path of the zip and commit the result. Its steps are the same every time, so the output is reproducible:

- Each route’s name comes from the sign (`I80` becomes `I-80`, `IH1` becomes `I-H1`).
- Pieces that meet are one junction: a piece’s end joins the other pieces of the same route that end within 0.0005 degrees (about 50 metres), and the nearest point of any other route within 0.004 degrees (about 400 metres), which is how two routes that cross at an interchange get a junction; a route passing through a junction is cut there.
- Pieces that only join each other, with nothing else at the junction, are merged into one.
- Each piece is simplified to within 0.001 degrees (about 100 metres) and its coordinates are rounded to four decimals, written as the first point and the steps from each point to the next.

The file has one row per piece: the route, its two junction numbers and its points. The app loads it once, the first time a trip’s map needs it, and keeps it in memory; finding a route is a shortest-path search over about 30,000 pieces that takes a fraction of a second. What the trip map receives is only the roads: the points and names of the interstates a drive follows and of the ones near it (coarsened again to about a kilometre), never anything about who travels or what was booked. Because the network is the interstates only and is coarse, a route can be a few miles off the road, can skip a short link that is not an interstate, and does not know about closures, tolls or traffic.
