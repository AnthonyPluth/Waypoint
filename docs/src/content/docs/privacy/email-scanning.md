---
title: Email scanning
description: What Waypoint will and won’t do with your mailbox. Connecting a Gmail works today; scanning it is planned.
sidebar:
  order: 1
---

:::caution[Connecting works; scanning is planned]
Members can connect a Gmail read-only today (see [Google OAuth client for Gmail](/waypoint/start/gmail/)), but Waypoint doesn’t read any email yet. This page is the promise scanning is being designed to keep, so you can judge it, and hold it to it, before it exists.
:::

Waypoint’s main way of learning about a booking is to read the confirmation email in a Gmail account you connect. The design rules:

- **Read-only.** Waypoint asks Google for read-only access to your mailbox. It can’t send, delete, label or change anything. You can revoke the access at any time in your Google account.
- **Searched on the server.** Waypoint asks Gmail for messages that look like bookings (by sender and subject), so it never downloads your whole mailbox.
- **Bodies are read in memory and never stored.** A message’s body is fetched, parsed and thrown away. Waypoint keeps what it found (a flight number, a time, a confirmation code) and a reference to the message, not the message.
- **Your server only.** The mailbox is read by your own Waypoint, with an OAuth client you create (see [Google OAuth client for Gmail](/waypoint/start/gmail/)). Nothing goes through a service run by the project.
- **You see only your trips.** A booking is visible to the people on the trip and the person whose mailbox it came from.

## How a booking is read

Waypoint tries the cheapest, most reliable method first and falls through:

1. **schema.org markup.** Many airlines, hotels and rental companies embed structured data (`FlightReservation`, `LodgingReservation`, `RentalCarReservation`) in the email for Gmail’s own cards. Waypoint reads it directly.
2. **Per-vendor parsers.** For senders without markup, a parser written for that vendor’s email.
3. **A “Couldn’t read” review queue.** What neither method understands lands in a queue where you can fix it by hand or dismiss it. Nothing is guessed silently.

## Optional AI suggestions

Off by default. If you turn it on, Waypoint can ask a model to suggest the fields of an email the parsers couldn’t read, and you confirm or correct the suggestion in the review queue.

- **Local:** an [Ollama](https://ollama.com) on your own network. The email text never leaves it.
- **Hosted:** [OpenRouter](https://openrouter.ai), restricted to providers with zero data retention.

Either way the suggestion is a draft for you to confirm, not something Waypoint saves on its own.

## What this means for the rest of the setup

- The Google OAuth client’s ID and secret are set in `.env` (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`); each connected mailbox’s refresh token is stored encrypted with `WAYPOINT_SECRET_KEY`, and backups hold it encrypted too ([Configuration](/waypoint/reference/configuration/)).
- Each member connects their own Gmail in Settings and sees only their own connections. A connection ends when its owner can no longer sign in. Anyone you let in can still download a backup, which holds the encrypted tokens. See [SECURITY.md](https://github.com/AnthonyPluth/waypoint/blob/main/SECURITY.md).
