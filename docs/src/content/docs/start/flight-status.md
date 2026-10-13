---
title: Live flight status
description: Delays, gates and cancellations on a flight’s card, from AeroDataBox through RapidAPI, within a monthly call budget. How to subscribe and set the key.
sidebar:
  order: 5
---

Waypoint can show a flight’s live status (on time, delayed, departed, landed, cancelled or diverted), its gate and terminal, and the times it is now expected, beside the booked times on the flight’s card. The booking stays the record: a status is shown next to what you booked and never written over it. Times are the airports’ own clocks, with the airport’s time zone, like every time in Waypoint (see [Trips](/Waypoint/start/trips/)).

The status comes from [AeroDataBox](https://rapidapi.com/aedbx-aedbx/api/aerodatabox), through [RapidAPI](https://rapidapi.com). It is off until you give Waypoint a key, and then only a flight number and a date ever leave your server.

## Set it up

1. Make an account at [rapidapi.com](https://rapidapi.com) and open the **AeroDataBox** API.
2. Subscribe to a plan. The free plan’s monthly allowance is what Waypoint’s budget is built around (400 calls a month by default); a bigger plan works too.
3. Copy your key: it’s the `X-RapidAPI-Key` value RapidAPI shows in the API’s code samples (and under your app’s **Security** settings).
4. Set it in `.env` (or the environment) and restart Waypoint:

   ```sh
   RAPIDAPI_KEY=your-key-here
   # If your plan allows a different number of calls a month (the default is 400):
   # WAYPOINT_FLIGHT_STATUS_MONTHLY_LIMIT=400
   ```

The key stays in the environment: Waypoint never saves it in the database or in a backup, and never writes it to its log. See [Configuration](/Waypoint/reference/configuration/).

## What a request carries

One request asks for one flight by its number and local departure date (`/flights/number/EX101/2026-11-20`) at `aerodatabox.p.rapidapi.com`, with your key in the `X-RapidAPI-Key` header. It carries nothing else: no traveller’s name, confirmation code, loyalty number, or any other segment. RapidAPI and AeroDataBox see that your key asked about that flight. Only `providers/flightstatus.py` talks to them, and a lint rule keeps their addresses out of the rest of the code.

## The call budget

A plan allows few calls a month, so Waypoint spends them carefully:

- **One call answers for everyone on a flight.** Answers are held by flight number and date, so a family of four on one flight costs the same as one traveller, and so do two bookings of the same flight.
- **Scheduled checks only, at fixed points:** about 24 hours, 3 hours, 1 hour and 20 minutes before the booked departure, and once at the booked arrival time. That is at most five calls a flight, so about 80 flights a month on 400 calls. Nothing is fetched for a flight more than 24 hours away, or once it has landed, been cancelled or been diverted. If Waypoint was off, it makes up only the latest check it missed. A call that fails still uses up its check, so an outage at the service costs at most one call per check, never a retry every few minutes.
- **Refresh** on a flight’s card fetches now, unless the answer it holds is under 15 minutes old (then it shows that one), or the flight’s final status is already kept. A Refresh that fetches counts against the budget too.
- **A monthly counter** (reset on the 1st, in Waypoint’s time zone, `TZ`) is shown in **Settings** as “Flight status: N of 400 calls used this month”. At 90% of the limit, scheduled checks stop except the one-hour check, and Refresh still works. At 100%, nothing is fetched and the card says “Live status paused until <date> (monthly limit)”.
- **A 429 from RapidAPI** (too many requests), or a key it refuses, pauses fetching for an hour, and the card says so. Fixing the key and restarting Waypoint ends a refused-key pause at once.

## What is stored

Only a flight’s **final** status is written to the database: landed, cancelled or diverted. It is kept for good, and the flight is never asked about again. It is stored by flight number and date, with the times, gates and terminals the airline gave, and holds no personal data. It is not tied to a booking, so it stays after the booking is removed.

A status that can still change (scheduled, delayed, departed, or one the service didn’t know) is **never stored**. Waypoint holds it in memory for 15 minutes, so the card can show “Delayed 50 min” while that is fresh. After that, or after Waypoint restarts, the card shows nothing until the next check.

To keep the schedule and the call budget across restarts, Waypoint also stores, for each flight it has asked about, the time it last asked (by flight number and date, and nothing about the answer). That time is removed seven days after the flight. The monthly call count and any pause are stored as before.

None of this is part of a backup: it is fetched again.

Push notifications for delays and gate changes aren’t part of this; they’re planned for when reminders exist.

The aircraft model in an answer Waypoint already fetched is kept on the flight when the booking has none (it is used to tell window, aisle and middle seats apart, and shown beside the flight number). It never replaces an aircraft that is already there or a booking you have edited, and it costs no extra request.
