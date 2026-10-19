---
title: Loyalty and Known Traveler numbers
description: Where the household keeps frequent-flyer, hotel, car, cruise, TSA PreCheck and Global Entry numbers, and how Waypoint protects them.
sidebar:
  order: 4
---

Each person on the [People](/Waypoint/start/people/) page, member or guest, has a list of memberships. Every signed-in member sees and edits everyone’s, so anyone can book for anyone.

## What you can keep

A membership has a **kind**, a **program**, a **number** and optional notes. Known Traveler and redress numbers can also have an expiry date.

- **Airline**, **hotel** and **car** programs, such as American AAdvantage, Marriott Bonvoy or Hertz Gold Plus Rewards.
- **Cruise**: a cruise line’s club, such as Disney Castaway Club or Carnival Rewards. The number is kept as you type it, unchecked. On a cruise booking from that line, the trip page shows the traveller’s number, masked, under **Loyalty**.
- **Known Traveler**: TSA PreCheck, Global Entry, NEXUS or SENTRI.
- **Redress**: a DHS TRIP number.

Each kind has a fixed list of programs. Choose **Other** for one that isn’t listed and say which in the notes. A person has one membership per program, so Waypoint refuses a second; **Other** can be used more than once.

## How the numbers are protected

- A number is **encrypted** in the database with the same key as Waypoint’s other secrets (`WAYPOINT_SECRET_KEY`).
- The People page shows it **masked**, with only its last four characters. **Show** reveals it and **Copy** copies it. Revealing is its own request, so loading the page never carries your numbers.
- Numbers are never written to the log, to reports or notifications, and never sent to an AI. Waypoint keeps nothing in your browser, so a number you revealed is gone when you leave the page.
- An [AI assistant you connect](/Waypoint/start/mcp/) can’t reach them at all, not even the last four characters.

Anyone you let sign in can see every number, as with the rest of the household’s data; the page and the form say so before you save. See [SECURITY.md](https://github.com/AnthonyPluth/Waypoint/blob/main/SECURITY.md).

A program shows its company’s logo from the [bundled catalog](/Waypoint/start/logos/), without network requests. Your number is never used to look one up.

## In a backup

Memberships are part of a [backup](/Waypoint/start/docker/#moving-your-data-from-another-machine), with their numbers still encrypted. Restoring under a different key can’t read them, and the restore lists “loyalty numbers” among the secrets to enter again. Set the key the backup was made with as `WAYPOINT_SECRET_KEY_OLD` for one start and they’re re-encrypted with the current one.
