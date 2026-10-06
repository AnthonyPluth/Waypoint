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
- **Some details missing**: it has booking markup, but not enough to make a segment (no arrival time, an airport Waypoint doesn’t know, a hotel whose time zone Waypoint can’t work out, or times marked as UTC that could be the local clock: see [Scanning](/Waypoint/start/gmail/#scanning)).
- **Couldn’t be opened**: the message itself was damaged.

For each one you can:

- **Open in Gmail**, to see the message yourself.
- **Ask AI** (when the optional [AI suggestions](/Waypoint/start/ai/) are on): asks the model about this one message now, the same way a scan does for a new item, and offers what it read as a suggestion to check. When two or more items have no suggestion yet, **Ask AI about all** above the list asks about each of them in turn; it stops at the first failure and says how many it got through.
- **Add by hand**: a form for the booking, with the sender’s name filled in as the provider and the message beside it, so you can read the details and type them in one place. A message with an HTML part shows as it was formatted (headings, lists, tables, bold and links), and **Show as plain text** switches to its text; one without shows its text. The message is the copy Waypoint kept, so it opens without Gmail, for anyone who sees the item (an item from before messages were kept is fetched from its owner’s Gmail the first time, and kept from then on). The formatted view is rebuilt on the server from a short list of safe tags, so nothing the sender wrote runs: scripts, styles and forms are dropped, and **pictures are never loaded** (you see their description instead), so opening the message doesn’t tell the sender you did. Links open in a new tab without the page they came from, and only `https` and `mailto` ones are kept; a link goes to the sender’s own address, which may identify you, so choosing one is visiting their site. Long messages are cut at 30,000 characters. Saving it adds the booking to your trips, takes the item off the list and keeps the message with the booking (see below).
- **Ignore this sender**: later scans skip that sender’s mail for this mailbox, and its other items leave the list.
- **Dismiss**: it isn’t a booking, so take it off. Waypoint remembers it has read the message, so it doesn’t come back.

Items are private to the member whose mailbox they came from: nobody else sees them, or even that they exist, until that member chooses to share the mailbox. Each item shows its message’s **subject**, and Waypoint keeps the message itself, encrypted, for as long as it’s needed: until the item is dismissed or added, and for as long as a booking made from it exists. That includes the emails a scan turned into bookings: a booking made from an email has a **View email** button on its card in the trip, for anyone who can see the booking, so the original is there when you need to check it. Dismissing an item deletes its message (unless a booking was made from it), as does removing the last booking made from it or disconnecting the mailbox.

### Sharing a mailbox’s items with the household

In **Settings → Mail and AI → Gmail**, each mailbox has a box, **Show this mailbox’s unread mail to the household**, off until its owner ticks it (only the owner can, and unticking it hides the items again at once). While it’s on, every member sees that mailbox’s items in Review, marked with whose mailbox they’re in, and the number on the Review tab counts them. They see the same things the owner does (its subject, who it came from, the day, why it couldn’t be read, and what the optional AI read from it) and can **Add by hand** (with the message beside the form, as the owner does) or **Dismiss** an item, so anyone can clear the queue. **Open in Gmail**, **Ask AI** and **Ignore this sender** stay with the mailbox’s owner. A mailbox, and what it shares, ends with its owner’s access.

After each scan, Waypoint’s log says how many messages it read and what stopped the others, as counts of fixed phrases (“12 × no structured booking data”, “3 × unknown airport”, “2 × arrival time”), never which messages or anything they said. Most senders put no machine-readable booking in their emails; those are the ones to add by hand, or to ignore.

## Who is this?

A booking prints each traveller’s name its own way (`DOE/JANE MS`). Waypoint matches a name to a person by the loyalty number on the booking first, then by the person’s display name, legal name or aliases on [People](/Waypoint/start/people/); it never picks between two people with the same name. A name nobody matches stays as printed, and the booking is then visible only to whoever’s mailbox it came from.

Each such name is listed here with the segment it’s on. Choose the person it is, or add a guest. Every traveller with that printed name on your trips becomes that person, and the printed name is kept as one of their aliases, so the next booking with it matches by itself.

## When a scan has a problem

A scan that stops halfway (Google couldn’t be reached, or refused a request) keeps everything it had already read and says what failed under the mailbox in Settings; the next scan carries on where it stopped. A scan that can’t start at all, because the mailbox needs reconnecting, is shown as **Reconnect**, not as a failed scan.
