---
title: Review
description: What Waypoint does when it can’t read a booking email, and how to match the names on bookings to people.
sidebar:
  order: 5
---

**Review** is where Waypoint asks for help, in two lists. A number on its tab says how much is waiting.

## Couldn’t read

When a message looks like a booking (it’s from an airline, hotel, rental company, railway or booking site, and it has a confirmation word in it) but Waypoint can’t get a booking out of it, the message lands here instead of being guessed at or dropped. Each item shows who it came from, its subject and the day it was sent, and why:

- **No booking details found**: the email carries no machine-readable booking, and Waypoint doesn’t have a parser for that sender yet.
- **Some details missing**: it has booking markup, but not enough to make a segment (no arrival time, an airport Waypoint doesn’t know, a hotel whose time zone Waypoint can’t work out).
- **Couldn’t be opened**: the message itself was damaged.

For each one you can:

- **Open in Gmail**, to see the message yourself. Waypoint never shows an email’s text.
- **Add by hand**: a form for the booking, with the sender’s name filled in as the provider. Saving it adds the booking to your trips and takes the item off the list.
- **Ignore this sender**: later scans skip that sender’s mail for this mailbox, and its other items leave the list.
- **Dismiss**: it isn’t a booking, so take it off. Waypoint remembers it has read the message, so it doesn’t come back.

Items are private to the member whose mailbox they came from: nobody else sees them, or even that they exist. Waypoint keeps the sender’s domain, the day, and the subject (encrypted with `WAYPOINT_SECRET_KEY`, like a mailbox’s token), never the message’s text.

## Who is this?

A booking prints each traveller’s name its own way (`DOE/JANE MS`). Waypoint matches a name to a person by the loyalty number on the booking first, then by the person’s display name, legal name or aliases on [People](/waypoint/start/people/); it never picks between two people with the same name. A name nobody matches stays as printed, and the booking is then visible only to whoever’s mailbox it came from.

Each such name is listed here with the segment it’s on. Choose the person it is, or add a guest. Every traveller with that printed name on your trips becomes that person, and the printed name is kept as one of their aliases, so the next booking with it matches by itself.

## When a scan has a problem

A scan that stops halfway (Google couldn’t be reached, or refused a request) keeps everything it had already read and says what failed under the mailbox in Settings; the next scan carries on where it stopped. A scan that can’t start at all, because the mailbox needs reconnecting, is shown as **Reconnect**, not as a failed scan.
