---
title: Data sources
description: Where the airport, airline and place data Waypoint ships with come from, and their licences.
sidebar:
  order: 2
---

Waypoint ships with three reference lists. They are the same for every Waypoint, aren’t part of a [backup](/Waypoint/start/docker/#moving-your-data-from-another-machine), and are never looked up from an outside service: nothing about your trips leaves the server to use them. If you add a MapKit key, the route replay’s base map comes from Apple, whose script then runs in the page, instead of these lists, and your server asks Apple for the roads of finished trips’ drives overnight ([Apple’s map for the route replay](/Waypoint/start/trips/#apples-map-for-the-route-replay)); the lists themselves still never leave your server.

## Airports

Name, city, country, time zone and coordinates for each three-letter IATA code come from [OurAirports](https://ourairports.com/data/)’ public-domain data, through the [`airportsdata`](https://pypi.org/project/airportsdata/) package, which adds each airport’s time zone. The same data gives the state of each US airport and the English name of each country, which name the places in a trip’s destination.

## Airlines

Name, IATA and ICAO code and country come from [OpenFlights](https://openflights.org/data.html)’ `airlines.dat`, made available under the [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/); its contents are under the [Database Contents License](https://opendatacommons.org/licenses/dbcl/1-0/). Waypoint’s derived list keeps one airline per IATA code and is itself kept open, in this public repository, under the same ODbL, as the licence asks. See also the `NOTICE` file.

## Places

The places list turns a booking’s address into a rough point on the map ([Where a booking is on the map](/Waypoint/start/trips/#where-a-booking-is-on-the-map)). It holds the centre of each US ZIP code, Canadian postal-code area (the first three characters) and British postcode district (the part before the space), and the centre, state, country and population of each city of 15,000 people or more, for finding a city by its name. It is built from two downloads that the app never fetches:

- **US ZIP codes:** the Census Bureau’s 2023 [Gazetteer ZIP Code Tabulation Areas](https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html) (US government data, public domain). A ZCTA approximates a ZIP code, so a few ZIP codes (some PO boxes and single-building codes) have none.
- **Canadian and British postal codes, and the cities:** [GeoNames](https://www.geonames.org/), licensed under [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/). The derived list keeps GeoNames’ names and coordinates, rounded to four decimals and averaged where one code lists several places, and is credited in the `NOTICE` file.
