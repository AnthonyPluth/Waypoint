---
title: Brand logos
description: Logos for the airlines, hotels, rental companies and cruise lines in your bookings, from Logo.dev. How to set the key, what Logo.dev is told, and how the logos are kept.
sidebar:
  order: 6
---

Waypoint can show the logo of each booking’s brand (an airline, a hotel chain, a rental company, a cruise line) beside it on the trip’s cards, on Upcoming and in a trip’s day-by-day list. The logos come from [Logo.dev](https://www.logo.dev). It is off until you save a key in **Settings**, and a booking whose brand has no logo looks as it always did.

## Set it up

1. Make a free account at [logo.dev](https://www.logo.dev) and copy your **publishable key** (it starts with `pk_`).
2. In **Settings → Brand logos**, paste it and save. Waypoint starts fetching the logos of the brands already in your bookings; they fill in over the next few minutes, and **Fetch them now** asks again for any it hasn’t fetched.
3. Optionally, paste your **secret key** (`sk_`) too. Waypoint then uses Logo.dev’s Brand Search to find the right brand for a name (a hotel named “Harbour Hotels Lisbon” is matched to “Harbour Hotels”) and keeps no logo rather than a doubtful one. Without it, Logo.dev matches the name itself, which is fine for airlines and big chains and sometimes wrong for a small hotel. Brand Search may not be in a free plan.

Both keys are saved encrypted, never come back to the page and never appear in a log. Logo.dev’s dashboard lets you limit a key to certain websites: don’t, since Waypoint asks from your server, not from a web page.

## What Logo.dev is told

One request asks for one brand by its name (or, with a secret key, by the website Brand Search found) and carries your key. It carries nothing else: no traveller, no date, no confirmation code, no address, nothing from your email. Logo.dev does learn which airlines, hotels, rental companies and cruise lines your household books, because it is asked for their logos. If you would rather it didn’t, leave the key unset. Only `providers/logodev.py` talks to Logo.dev, and a lint rule keeps its addresses out of the rest of the code.

## How the logos are kept

- **Your browser never contacts Logo.dev.** Waypoint downloads each logo once, keeps it in its database and serves it itself, so the page’s content policy stays “images from Waypoint only”. Only a PNG, JPEG, WebP or GIF of 256 KB or less is kept, never an SVG.
- **A logo is shown only on a booking you can see.** It is served through its segment, so who has stayed where isn’t something anyone can find out by asking for a brand.
- **A brand is asked about once, then again after a month** in case its logo changed. A brand Logo.dev has none for is remembered as such, and a logo Waypoint already has is kept if Logo.dev later loses it.
- **If Logo.dev can’t be asked** (a refused key, no connection), the round stops, Settings says why, and the brands left are tried again in the next round (every 15 minutes), not a month from now.
- Logos are a cache, so they aren’t part of a [backup](/waypoint/start/docker/#moving-your-data-from-another-machine); the keys are, encrypted like your other settings.
- A flight with no airline named on it is shown the logo of the airline its flight number’s code belongs to.

AI assistants connected over [MCP](/waypoint/start/mcp/) can’t reach these settings.
