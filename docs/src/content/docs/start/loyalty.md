---
title: Loyalty and Known Traveler numbers
description: Where the household keeps frequent-flyer, hotel, car, TSA PreCheck and Global Entry numbers, and how Waypoint protects them.
sidebar:
  order: 4
---

Each person on the [People](/waypoint/start/people/) page, member or guest, has a list of memberships. Every signed-in member sees and edits everyone’s, so anyone can book for anyone.

## What you can keep

A membership has a **kind**, a **program**, a **number**, and optionally a tier, an expiry date and notes.

- **Airline**, **hotel** and **car** programs, such as American AAdvantage, Marriott Bonvoy or Hertz Gold Plus Rewards.
- **Known Traveler**: TSA PreCheck, Global Entry, NEXUS or SENTRI.
- **Redress**: a DHS TRIP number.

Each kind has a fixed list of programs. Choose **Other** for one that isn’t listed, and say which in the notes.

A person has one membership in each program: once one is saved, that program is no longer offered for them under **+ ID**, and Waypoint refuses a second one (edit the first instead). **Other** can be used more than once, since it can stand for any program. A person who ended up with two numbers for one program by claiming a guest keeps both, flagged on the People page, and can still edit either.

## How the numbers are protected

- A number is **encrypted** in the database, with the same key as Waypoint’s other secrets (`WAYPOINT_SECRET_KEY`).
- The People page shows it **masked**, with only its last four characters. Choose **Show** to reveal it and **Copy** to copy it. Revealing is its own request, so loading the page never carries your numbers.
- Numbers are never written to the log, to reports or notifications, and never sent to an AI.
- Waypoint keeps nothing in your browser: a number you revealed is gone when you leave the page.
- An [AI assistant you connect](/waypoint/start/mcp/) can’t reach loyalty or Known Traveler numbers at all, not even their last four characters.

Anyone you let sign in can see every number, as with the rest of the household’s data. See [SECURITY.md](https://github.com/AnthonyPluth/waypoint/blob/main/SECURITY.md).

## In a backup

Memberships are part of a [backup](/waypoint/start/docker/#moving-your-data-from-another-machine), and their numbers stay encrypted in the file and come back exactly as they were. Restoring on a machine with a different key can’t read them: the restore lists “loyalty numbers” among the secrets to enter again. Set the key the backup was made with as `WAYPOINT_SECRET_KEY_OLD` for one start and they’re re-encrypted with the current one.
