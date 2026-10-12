---
title: Data sources
description: Where the airport, airline and place lists Waypoint ships with come from, and their licences.
sidebar:
  order: 2
---

Waypoint ships with three reference lists. The airports and airlines are loaded into the database by its migrations; the places list is read from its file. They are the same for every Waypoint, and aren’t part of a [backup](/Waypoint/start/docker/#moving-your-data-from-another-machine).

## Airports

The airports (name, city, country, time zone and coordinates, by three-letter IATA code) come from [OurAirports](https://ourairports.com/data/)’ public-domain data, through the [`airportsdata`](https://pypi.org/project/airportsdata/) package, which adds each airport’s time zone. `tools/airports.py` writes `waypoint/storage/airports.tsv.gz`.

## Airlines

The airlines (name, IATA and ICAO code, country) come from [OpenFlights](https://openflights.org/data.html)’ `airlines.dat`, which is made available under the [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/); its contents are under the [Database Contents License](https://opendatacommons.org/licenses/dbcl/1-0/). `tools/airlines.py` writes `waypoint/storage/airlines.tsv.gz`, one airline per IATA code. That derived file is itself a database made from OpenFlights’ and is kept open, in this public repository, under the same ODbL, as the licence asks. See also the `NOTICE` file.

## Places

The places list turns a booking’s address into a rough point on the map without asking any outside service ([Where a booking is on the map](/Waypoint/start/trips/#where-a-booking-is-on-the-map)). It holds the centre of each US ZIP code, of each Canadian postal-code area (the first three characters) and of each British postcode district (the part before the space), and the centre, state, country and population of each city of 15,000 people or more, for finding a city by its name. `tools/places.py` writes `waypoint/storage/places.tsv.gz` from these downloads, which are not fetched by the app:

- US ZIP codes: the Census Bureau’s [2023 Gazetteer ZIP Code Tabulation Areas](https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html) file (US government data, public domain). A ZCTA is the Bureau’s approximation of a ZIP code, so a few ZIP codes (some PO boxes and single-building codes) have none.
- Canadian and British postal codes, and the cities: [GeoNames](https://www.geonames.org/) (`GB.zip`, `CA.zip` and `cities15000.zip` from its download server), licensed under [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/). The derived file keeps GeoNames’ names and coordinates, rounded to four decimals, with the British and Canadian codes averaged where GeoNames lists several places for one code, and is credited in the `NOTICE` file.
