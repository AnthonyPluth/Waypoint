---
title: Email scanning
description: What Waypoint does and doesn’t do with your mailbox. It’s read-only, searched on your server, and a message is kept, encrypted, only while a review item or a booking needs it.
sidebar:
  order: 1
---

:::note[What’s built]
Members connect a Gmail read-only (see [Google OAuth client for Gmail](/Waypoint/start/gmail/)), and Waypoint scans it for bookings in schema.org markup, falling back to a parser for senders without it (Southwest and Disney Cruise Line so far), and queuing what it can’t read in [Review](/Waypoint/start/review/). The optional AI suggestions below are built.
:::

Waypoint’s main way of learning about a booking is to read the confirmation email in a Gmail account you connect. The rules it keeps:

- **Read-only.** Waypoint asks Google for read-only access to your mailbox. It can’t send, delete, label or change anything. You can revoke the access at any time in your Google account.
- **Searched on the server.** Waypoint asks Gmail for messages that look like bookings (by sender and subject), so it never downloads your whole mailbox.
- **Bodies are read in memory, and a message is kept only while it’s needed.** A message’s body is fetched and parsed in memory, and Waypoint keeps what it found (a flight number, a time, a confirmation code) and a reference to the message (its Gmail id). It also keeps the message itself, but only while something needs it: a [Review](/Waypoint/start/review/) item waiting for it, or a booking made from it. What is kept is its subject, who it was from and the day, its text and, for an HTML message, the message as it was sent: its layout (colours, fonts, sizes, spacing, alignment, tables and their widths) rebuilt on the server from a short list of safe tags and styles, and its pictures (see below). It is stored as one encrypted value, under the same key as the Gmail connection, so a copy of the database or a backup doesn’t show it without that key. It is deleted when its item is dismissed (unless a booking was made from it, which keeps it), when the last booking made from it is removed, and when its mailbox is disconnected. Mail that made no booking and wasn’t queued for review, and mail from a sender you stopped reviewing, is never kept. The message is never logged, reported or sent to any service other than Gmail’s own API (and the optional AI below, if you turn it on), no AI assistant connected over MCP can reach it, and the project’s checks hold the code to that: only one module looks inside a message, decryption stays in the storage layer, and the tests scan made-up emails while watching the database (for the text in the clear), the log and every request. The one other place the message can be is your own device: if you set up [offline access](/Waypoint/start/offline/), the messages kept for the bookings on your current trip are part of the copy Waypoint saves there, encrypted, for you only, and cleared when you sign out, when you turn it off and three days after the trip ends.
- **Your server only.** The mailbox is read by your own Waypoint, with an OAuth client you create (see [Google OAuth client for Gmail](/Waypoint/start/gmail/)). Nothing goes through a service run by the project.
- **You see only your trips.** A booking is visible to the people on the trip, the person who booked it, and whoever got its confirmation in their own mailbox (the same email in two household members’ mailboxes is one booking, shown to both). Mail Waypoint couldn’t read is the mailbox owner’s alone unless they choose to [share that mailbox’s items with the household](/Waypoint/start/review/#sharing-a-mailboxs-items-with-the-household): then the household sees each one’s subject, who it is from and its day, and can read the message beside the Add by hand form. Anyone who can see a booking can read the email it was made from; no one else can.

## The email as it was sent

**View email** on a booking, and the message beside a review item, show the email the way it arrived: its layout, logos and pictures, and all of it up to a very generous cap (500,000 characters of text, and 2 MB of markup; past that it says “This email was cut short”). Nothing opens the sender’s site or loads from it in your browser.

- **Rebuilt, not copied.** The server rebuilds the markup from an allowlist. It keeps tags, tables and a small set of inline styles (colours, fonts, sizes, spacing, alignment, widths, borders), and drops everything else: scripts, event handlers, style sheets, forms, frames, `javascript:` and `data:` links, and every picture address. Links keep only `https` and `mailto` addresses, open in a new tab without the page they came from, and show where they go when you point at them.
- **Contained.** The email is shown in a sandboxed frame with no scripts and no access to the rest of Waypoint, under a Content-Security-Policy that allows nothing to load from the network. Its pictures are handed to the frame by Waypoint itself, so even a flaw in the allowlist could not run code or reach out. Waypoint’s screens are dark, so the email sits on a light sheet, as it was written; on a phone it scrolls inside its box.
- **Pictures are fetched once, when the message is kept.** Pictures attached to the message need no fetch. For the others, the server downloads each address the message names, once, when a scan keeps the message (a review item waiting on it, or a booking made from it), and keeps them in the same encrypted value as the message, in backups too. Opening the email later asks Waypoint only: your browser never contacts the sender, so a tracking pixel can’t fire when someone opens it, and a picture the sender later removes doesn’t break an old email. A picture is served only to someone who can see the booking or the review item (anyone else gets “not found”) and never to an AI assistant over MCP.
- **What the download is allowed to do.** One module makes it (`waypoint/providers/images.py`; the project’s checks keep it the only one). It uses `https` only, refuses private, loopback and link-local addresses (including the answers DNS gives for a name, and after every redirect, of which it follows three at most), sends no cookies, referrer or sign-in and a generic browser name, doesn’t use a proxy, skips tiny tracking pixels, and stops at 1 MB for a picture, 5 MB and 30 pictures for a message, and 8 seconds for a picture and 30 for a message. It keeps only PNG, JPEG, GIF and WebP, decided by what the bytes are rather than what the sender says; SVG is never kept, since it can carry script. A picture that is refused or fails is simply left out (you see its description), and the message still opens.
- **What the sender can and can’t learn.** The sender’s server (or its picture host) sees one request for each picture address in the message, from your Waypoint server’s internet address, at about the time a scan kept the message. An address made just for you therefore tells them that this message was picked up by something that loads pictures. They don’t learn whether, when or by whom the email is opened in Waypoint, which device you use, or anything in your trips. Nothing from the booking is in the request.
- **Mail kept before this.** A message kept earlier shows as it did, with a line saying the original can’t be shown. Waypoint doesn’t fetch it from Gmail again unless you ask: a review item you open that was never kept is read from its owner’s Gmail once, as before, and kept in full from then on.
- **Never kept.** Attachments other than the pictures shown in the email (a PDF boarding pass, say), the message’s other headers, and anything the allowlist drops. The optional AI below still gets only plain text, never markup or pictures.

## How a booking is read

Waypoint tries the cheapest, most reliable method first and falls through:

1. **schema.org markup** (built). Many airlines, hotels, rental companies and railways embed structured data (`FlightReservation`, `LodgingReservation`, `RentalCarReservation`, `TrainReservation`) in the email for Gmail’s own cards. Waypoint reads it directly.
2. **Per-vendor parsers** (started: Southwest Airlines and Disney Cruise Line). For senders without markup, a parser written for that vendor’s email reads its text for the same fields, and for its change and cancellation emails. A parser only ever sees the message’s text in memory, and keeps nothing of it. Disney Cruise Line’s parser reads the booking confirmation: the sailing, its ship, stateroom and deck, each guest’s name (never their Castaway Club number) and the ports of call with their times at each port’s own zone; a re-sent confirmation updates the same booking, a port it doesn’t know goes to review, and its change and cancellation emails aren’t read yet. More vendors come one at a time.
3. **A “Couldn’t read” review queue** (built). What neither method understands lands in a queue where you can open it in Gmail, add the booking by hand, ignore the sender or dismiss it. Nothing is guessed silently.

## Optional AI suggestions

Off by default (Settings → Mail and AI → AI; see [AI suggestions](/Waypoint/start/ai/)). If you turn it on, Waypoint can ask a model to suggest the fields of an email that newly lands in the “Couldn’t read” queue, and you confirm or correct the suggestion there.

- **Local:** an [Ollama](https://ollama.com) on your own network. The email text never leaves it.
- **Hosted:** [OpenRouter](https://openrouter.ai), restricted to providers with zero data retention (every request denies data collection and requires zero retention).

Only the plain text goes out, with quoted replies, footers and labelled or number-shaped loyalty, Known Traveler and card numbers removed (as well as the numbers saved under Loyalty). Either way the suggestion is a draft for you to confirm, not something Waypoint saves on its own, and prompts and replies are never logged.

## What this means for the rest of the setup

- The Google OAuth client’s ID and secret are set in `.env` (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`); each connected mailbox’s refresh token is stored encrypted with `WAYPOINT_SECRET_KEY`, and backups hold it encrypted too ([Configuration](/Waypoint/reference/configuration/)).
- Each member connects their own Gmail in Settings and sees only their own connections. A connection ends when its owner can no longer sign in (Waypoint checks hourly, and before every use). Anyone you let in can still download a backup, which holds the encrypted tokens. See [SECURITY.md](https://github.com/AnthonyPluth/waypoint/blob/main/SECURITY.md).

## Live flight status is the one other thing that leaves the server

If you turn on [live flight status](/Waypoint/start/flight-status/), Waypoint asks AeroDataBox (through RapidAPI) about a flight by its number and date. That request carries nothing from your email or your trips beyond the flight number and date: no names, confirmation codes or loyalty numbers. It is off until you set a key.
