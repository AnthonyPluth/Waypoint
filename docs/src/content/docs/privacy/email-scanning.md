---
title: Email scanning
description: What Waypoint does and doesn’t do with your mailbox. It’s read-only, searched on your server, and bodies are never stored.
sidebar:
  order: 1
---

:::note[What’s built]
Members connect a Gmail read-only (see [Google OAuth client for Gmail](/waypoint/start/gmail/)), and Waypoint scans it for bookings in schema.org markup, falling back to a parser for senders without it (Southwest so far), and queuing what it can’t read in [Review](/waypoint/start/review/). The optional AI suggestions below are built.
:::

Waypoint’s main way of learning about a booking is to read the confirmation email in a Gmail account you connect. The rules it keeps:

- **Read-only.** Waypoint asks Google for read-only access to your mailbox. It can’t send, delete, label or change anything. You can revoke the access at any time in your Google account.
- **Searched on the server.** Waypoint asks Gmail for messages that look like bookings (by sender and subject), so it never downloads your whole mailbox.
- **Bodies are read in memory and never stored.** A message’s body is fetched, parsed and thrown away. Waypoint keeps what it found (a flight number, a time, a confirmation code) and a reference to the message (its Gmail id), not the message. For mail it couldn’t read it keeps only the sender’s domain and the day, not its subject. The message text is never logged, reported or sent to any service other than Gmail’s own API, and the project’s checks hold the code to that: only one module looks inside a message, and its tests scan made-up emails while watching the database, the log and every request for any of their text.
- **Your server only.** The mailbox is read by your own Waypoint, with an OAuth client you create (see [Google OAuth client for Gmail](/waypoint/start/gmail/)). Nothing goes through a service run by the project.
- **You see only your trips.** A booking is visible to the people on the trip and the person whose mailbox it came from.

## How a booking is read

Waypoint tries the cheapest, most reliable method first and falls through:

1. **schema.org markup** (built). Many airlines, hotels, rental companies and railways embed structured data (`FlightReservation`, `LodgingReservation`, `RentalCarReservation`, `TrainReservation`) in the email for Gmail’s own cards. Waypoint reads it directly.
2. **Per-vendor parsers** (started: Southwest Airlines). For senders without markup, a parser written for that vendor’s email reads its text for the same fields, and for its change and cancellation emails. A parser only ever sees the message’s text in memory, and keeps nothing of it. More vendors come one at a time.
3. **A “Couldn’t read” review queue** (built). What neither method understands lands in a queue where you can open it in Gmail, add the booking by hand, ignore the sender or dismiss it. Nothing is guessed silently.

## Optional AI suggestions

Off by default (Settings → AI; see [AI suggestions](/waypoint/start/ai/)). If you turn it on, Waypoint can ask a model to suggest the fields of an email that newly lands in the “Couldn’t read” queue, and you confirm or correct the suggestion there.

- **Local:** an [Ollama](https://ollama.com) on your own network. The email text never leaves it.
- **Hosted:** [OpenRouter](https://openrouter.ai), restricted to providers with zero data retention (every request denies data collection and requires zero retention).

Only the plain text goes out, with quoted replies, footers and labelled or number-shaped loyalty, Known Traveler and card numbers removed (as well as the numbers saved under Loyalty). Either way the suggestion is a draft for you to confirm, not something Waypoint saves on its own, and prompts and replies are never logged.

## What this means for the rest of the setup

- The Google OAuth client’s ID and secret are set in `.env` (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`); each connected mailbox’s refresh token is stored encrypted with `WAYPOINT_SECRET_KEY`, and backups hold it encrypted too ([Configuration](/waypoint/reference/configuration/)).
- Each member connects their own Gmail in Settings and sees only their own connections. A connection ends when its owner can no longer sign in (Waypoint checks hourly, and before every use). Anyone you let in can still download a backup, which holds the encrypted tokens. See [SECURITY.md](https://github.com/AnthonyPluth/waypoint/blob/main/SECURITY.md).

## Live flight status is the one other thing that leaves the server

If you turn on [live flight status](/waypoint/start/flight-status/), Waypoint asks AeroDataBox (through RapidAPI) about a flight by its number and date. That request carries nothing from your email or your trips beyond the flight number and date: no names, confirmation codes or loyalty numbers. It is off until you set a key.
