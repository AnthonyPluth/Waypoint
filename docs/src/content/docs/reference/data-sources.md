---
title: Data sources
description: Where the airport and airline lists Waypoint ships with come from, and their licences.
sidebar:
  order: 2
---

Waypoint ships with two reference lists, loaded into the database by its migrations. They are the same for every Waypoint, and aren’t part of a [backup](/waypoint/start/docker/#moving-your-data-from-another-machine).

## Airports

The airports (name, city, country, time zone and coordinates, by three-letter IATA code) come from [OurAirports](https://ourairports.com/data/)’ public-domain data, through the [`airportsdata`](https://pypi.org/project/airportsdata/) package, which adds each airport’s time zone. `tools/airports.py` writes `waypoint/storage/airports.tsv.gz`.

## Airlines

The airlines (name, IATA and ICAO code, country) come from [OpenFlights](https://openflights.org/data.html)’ `airlines.dat`, which is made available under the [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/); its contents are under the [Database Contents License](https://opendatacommons.org/licenses/dbcl/1-0/). `tools/airlines.py` writes `waypoint/storage/airlines.tsv.gz`, one airline per IATA code. That derived file is itself a database made from OpenFlights’ and is kept open, in this public repository, under the same ODbL, as the licence asks. See also the `NOTICE` file.
