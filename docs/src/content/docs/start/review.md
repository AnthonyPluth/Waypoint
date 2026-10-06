---
title: Review
description: What Waypoint does when it can’t read a booking email, and how to match the names on bookings to people.
sidebar:
  order: 5
---

**Review** is where Waypoint asks for help, in two lists. A number on its tab says how much is waiting.

## Couldn’t read

When a message looks like a booking (it’s from an airline, hotel, rental company, railway or booking site, and it has a confirmation word in it) but Waypoint can’t get a booking out of it, the message lands here instead of being guessed at or dropped. Each item shows who it came from, the day it was sent and why (not its subject: that is email content, which Waypoint doesn’t keep):

- **No booking details found**: the email carries no machine-readable booking, and Waypoint doesn’t have a parser for that sender yet.
- **Some details missing**: it has booking markup, but not enough to make a segment (no arrival time, an airport Waypoint doesn’t know, a hotel whose time zone Waypoint can’t work out, or times marked as UTC that could be the local clock: see [Scanning](/waypoint/start/gmail/#scanning)).
- **Couldn’t be opened**: the message itself was damaged.

For each one you can:

- **Open in Gmail**, to see the message yourself.
- **Ask AI** (when the optional [AI suggestions](/waypoint/start/ai/) are on): asks the model about this one message now, the same way a scan does for a new item, and offers what it read as a suggestion to check. When two or more items have no suggestion yet, **Ask AI about all** above the list asks about each of them in turn; it stops at the first failure and says how many it got through.
- **Add by hand**: a form for the booking, with the sender’s name filled in as the provider and the message’s text as plain text beside it, so you can read the details and type them in one place. Waypoint fetches the text from Gmail when you ask, shows it only to you, and keeps none of it: it isn’t stored or logged, and it’s gone when you leave the page. No pictures, links or scripts in it are loaded; long messages are cut at 30,000 characters. Saving it adds the booking to your trips and takes the item off the list.
- **Ignore this sender**: later scans skip that sender’s mail for this mailbox, and its other items leave the list.
- **Dismiss**: it isn’t a booking, so take it off. Waypoint remembers it has read the message, so it doesn’t come back.

Items are private to the member whose mailbox they came from: nobody else sees them, or even that they exist, until that member chooses to share the mailbox. Waypoint keeps the sender’s domain and the day, never the message’s subject or text.

### Sharing a mailbox’s items with the household

In **Settings → Gmail**, each mailbox has a box, **Show this mailbox’s unread mail to the household**, off until its owner ticks it (only the owner can, and unticking it hides the items again at once). While it’s on, every member sees that mailbox’s items in Review, marked with whose mailbox they’re in, and the number on the Review tab counts them. They see the same things the owner does (who it came from, the day, why it couldn’t be read, and what the optional AI read from it) and can **Add by hand** (without the message’s text beside the form, which only its owner’s Gmail can give) or **Dismiss** an item, so anyone can clear the queue. **Open in Gmail**, **Ask AI**, the text beside the form and **Ignore this sender** stay with the mailbox’s owner. A mailbox, and what it shares, ends with its owner’s access.

After each scan, Waypoint’s log says how many messages it read and what stopped the others, as counts of fixed phrases (“12 × no structured booking data”, “3 × unknown airport”, “2 × arrival time”), never which messages or anything they said. Most senders put no machine-readable booking in their emails; those are the ones to add by hand, or to ignore.

## Who is this?

A booking prints each traveller’s name its own way (`DOE/JANE MS`). Waypoint matches a name to a person by the loyalty number on the booking first, then by the person’s display name, legal name or aliases on [People](/waypoint/start/people/); it never picks between two people with the same name. A name nobody matches stays as printed, and the booking is then visible only to whoever’s mailbox it came from.

Each such name is listed here with the segment it’s on. Choose the person it is, or add a guest. Every traveller with that printed name on your trips becomes that person, and the printed name is kept as one of their aliases, so the next booking with it matches by itself.

## When a scan has a problem

A scan that stops halfway (Google couldn’t be reached, or refused a request) keeps everything it had already read and says what failed under the mailbox in Settings; the next scan carries on where it stopped. A scan that can’t start at all, because the mailbox needs reconnecting, is shown as **Reconnect**, not as a failed scan.
