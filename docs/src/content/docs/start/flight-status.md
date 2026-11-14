---
title: Live flight status
description: Delays, gates and cancellations on a flight’s card, from AeroDataBox through RapidAPI, within a monthly call budget.
sidebar:
  order: 5
---

Waypoint can show a flight’s live status (on time, delayed, departed, landed, cancelled or diverted), its gate and terminal, and its expected times, beside the booked times on the flight’s card. The booking stays the record: a status is shown next to what you booked and never written over it. Times are the airports’ own clocks, as everywhere in Waypoint (see [Trips](/Waypoint/start/trips/)).

The status comes from [AeroDataBox](https://rapidapi.com/aedbx-aedbx/api/aerodatabox) through [RapidAPI](https://rapidapi.com). It is off until you give Waypoint a key, and then only a flight number and a date ever leave your server.

## Set it up

1. Make an account at [rapidapi.com](https://rapidapi.com) and open the **AeroDataBox** API.
2. Subscribe to a plan. Waypoint’s budget is built around the free plan’s allowance (400 calls a month by default); a bigger plan works too.
3. Copy your key: the `X-RapidAPI-Key` value in the API’s code samples.
4. Set it in `.env` (or the environment) and restart Waypoint:

   ```sh
   RAPIDAPI_KEY=your-key-here
   # If your plan allows a different number of calls a month (the default is 400):
   # WAYPOINT_FLIGHT_STATUS_MONTHLY_LIMIT=400
   ```

The key stays in the environment: Waypoint never saves it in the database or a backup, and never writes it to its log. See [Configuration](/Waypoint/reference/configuration/).

## What a request carries

One request asks for one flight by its number and local departure date, with your key in a header. It carries nothing else: no traveller’s name, confirmation code, loyalty number or other segment. RapidAPI and AeroDataBox see that your key asked about that flight.

## The call budget

A plan allows few calls a month, so Waypoint spends them carefully:

- **One call answers for everyone on a flight.** Answers are held by flight number and date, so a family of four, or two bookings of the same flight, cost one call.
- **Scheduled checks**, about 24 hours, 3 hours, 1 hour and 20 minutes before the booked departure, then at the booked departure time and at the arrival time. An on-time flight costs six calls, so about 65 flights a month on 400 calls. Nothing is fetched for a flight more than 24 hours away, or once it has landed, been cancelled or been diverted.
- **A late flight keeps being checked.** When an answer says the flight will leave later, Waypoint also checks 1 hour and 20 minutes before the new time, and at the new arrival time instead of the booked one. Once a flight should have left (or landed) and the last answer doesn’t say it has, it is checked every 15 minutes for two hours, then every hour, until it does or until 6 hours after its arrival. A delay announced after the last check before departure is picked up at the booked departure time. A typical delayed flight costs 8 or 9 calls; one the service never reports as departed or landed costs at most about 20 (a one-hour flight) to 35 (a twelve-hour flight).
- **What the web app shows updates itself.** While a flight is within a day of departure, in the air or up to 6 hours after landing, an open trip page or Upcoming re-reads the status Waypoint holds every minute, and again when you come back to the app or the window. This reads only what Waypoint already has: the browser never asks the status service, and it costs no calls.
- **Outages cost nothing extra.** The 15-minute and hourly checks follow a good answer. Once a call fails, or when none is held (the service doesn’t know the flight, or Waypoint restarted), only the scheduled checks are made (with a known delay, the ones before the new time too) until one of them gets an answer, and the card keeps showing the last answer meanwhile. After downtime Waypoint makes up only the latest check it missed, and a failed call still uses up its check, so an outage never causes repeated retries.
- **Refresh** on a flight’s card fetches now, unless the answer it holds is under 15 minutes old or the flight’s final status is already kept. A Refresh that fetches counts against the budget.
- **A monthly counter** (reset on the 1st, in Waypoint’s time zone `TZ`) shows in **Settings** as “Flight status: N of 400 calls used this month”. At 90% of the limit, every check stops except the one-hour check (no late-flight checks either), and Refresh still works. At 100%, nothing is fetched and the card says “Live status paused until <date> (monthly limit)”.
- **A 429 from RapidAPI** (too many requests), or a key it refuses, pauses fetching for an hour, and the card says so. Fixing the key and restarting Waypoint ends a refused-key pause at once.

## What is stored

- **Final statuses only.** A flight’s final status (landed, cancelled or diverted) is written to the database and kept for good, and the flight is never asked about again. It is stored by flight number and date, with the times, gates and terminals the airline gave, and holds no personal data. It isn’t tied to a booking, so it stays after the booking is removed.
- **Anything that can still change** (scheduled, delayed, departed, or unknown to the service) is never stored. It is held in memory, with the time it was fetched (“as of 6:40 PM”), until the next answer replaces it or 6 hours after the flight’s arrival, so the card can show “Delayed 50 min”; after a restart the card shows nothing until the next check.
- **Schedule bookkeeping.** For each flight it has asked about, Waypoint stores the time it last asked, by flight number and date and nothing about the answer, until seven days after the flight. The monthly call count and any pause are stored too.
- **Aircraft model.** If an answer includes one and the booking has none, it is kept on the flight, to tell window, aisle and middle seats apart and to show beside the flight number. It never replaces an aircraft already there or a booking you have edited, and costs no extra request.

None of this is part of a [backup](/Waypoint/start/docker/#moving-your-data-from-another-machine): it is fetched again.
