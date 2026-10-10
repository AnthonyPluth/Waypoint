---
title: Email scanning
description: What Waypoint does and doesn’t do with your mailbox. It’s read-only, searched on your server, and a message is kept, with its images and layout, encrypted, only while a review item or a booking needs it.
sidebar:
  order: 1
---

:::note[What’s built]
Members connect a Gmail read-only (see [Google OAuth client for Gmail](/Waypoint/start/gmail/)), and Waypoint scans it for bookings in schema.org markup, falling back to a parser for senders without it (Southwest and Disney Cruise Line so far), and queuing what it can’t read in [Review](/Waypoint/start/review/). The optional AI suggestions below are built.
:::

Waypoint’s main way of learning about a booking is to read the confirmation email in a Gmail account you connect. The rules it keeps:

- **Read-only.** Waypoint asks Google for read-only access to your mailbox. It can’t send, delete, label or change anything. You can revoke the access at any time in your Google account.
- **Searched on the server.** Waypoint asks Gmail for messages that look like bookings (by sender and subject), so it never downloads your whole mailbox.
- **Bodies are read in memory, and a message is kept only while it’s needed.** A message’s body is fetched and parsed in memory, and Waypoint keeps what it found (a flight number, a time, a confirmation code) and a reference to the message (its Gmail id). It also keeps the message itself, but only while something needs it: a [Review](/Waypoint/start/review/) item waiting for it, or a booking made from it. What is kept is its subject, who it was from and the day, its text and, for an HTML message, its layout and its images: markup rebuilt on the server from a list of safe tags with a safe subset of inline formatting (colours, fonts, sizes, spacing, alignment, tables), and nothing that runs or loads (no scripts, event handlers, style blocks, forms or remote pictures), plus the images it shows (see [What the sender can learn](#what-the-sender-can-learn)). A long message is kept in full up to a hard limit of 300,000 characters of text and 900,000 characters of markup, and Waypoint says “This email was cut short” only past it. It is stored as one encrypted value, under the same key as the Gmail connection, so a copy of the database or a backup doesn’t show it, images included, without that key. It is deleted, images with it, when its item is dismissed (unless a booking was made from it, which keeps it), when the last booking made from it is removed, and when its mailbox is disconnected. Mail that made no booking and wasn’t queued for review, and mail from a sender you stopped reviewing, is never kept. The message is never logged, reported or sent to any service other than Gmail’s own API (and the optional AI below, if you turn it on), no AI assistant connected over MCP can reach it, and the project’s checks hold the code to that: only one module looks inside a message, decryption stays in the storage layer, and the tests scan made-up emails while watching the database (for the text in the clear), the log and every request. The one other place the message can be is your own device: if you set up [offline access](/Waypoint/start/offline/), the messages kept for the bookings on your current trip (their text and formatting, not their images) are part of the copy Waypoint saves there, encrypted, for you only, and cleared when you sign out, when you turn it off and three days after the trip ends.
- **Your server only.** The mailbox is read by your own Waypoint, with an OAuth client you create (see [Google OAuth client for Gmail](/Waypoint/start/gmail/)). Nothing goes through a service run by the project.
- **You see only your trips.** A booking is visible to the people on the trip, the person who booked it, and whoever got its confirmation in their own mailbox (the same email in two household members’ mailboxes is one booking, shown to both). Mail Waypoint couldn’t read is the mailbox owner’s alone unless they choose to [share that mailbox’s items with the household](/Waypoint/start/review/#sharing-a-mailboxs-items-with-the-household): then the household sees each one’s subject, who it is from and its day, and can read the message beside the Add by hand form. Anyone who can see a booking can read the email it was made from, and see its images; no one else can.

## What the sender can learn

Opening an email in Waypoint never contacts the sender: the email is shown in a sandboxed frame that can run no script and may load only images Waypoint itself gives it, so a tracking pixel in a message can’t tell anyone that you looked.

The one thing that changes is when the message is kept (a booking was made from it, or it went to Review). Then your Waypoint server downloads the images the message names, once, so they are there when you open it and still there if the sender removes them. To the sender that is a request from your server’s address for each image address in the message, which may carry whatever the sender put in that address, such as a code that identifies the message. The request has no cookies and nothing about you or Waypoint beyond a generic browser name, and it happens once, not each time someone opens the email. Images attached to the message itself need no download.

What the download will and won’t do:

- Only `https` addresses that resolve to public internet addresses: private, loopback and link-local addresses are refused, including after a redirect or a changed DNS answer, and no proxy is used.
- At most 1 MB for an image, 6 MB and 40 images for a message, and a few seconds for an image and 30 for a message. An image that fails or is refused is left out, and the message still opens.
- Only PNG, JPEG, GIF and WebP, decided by the file’s contents. SVG is refused, since it can carry script.
- The images are kept encrypted with the message and deleted with it. They are shown only to those who can see the booking or review item, through Waypoint’s own sign-in-protected addresses, and are never reachable by an AI assistant over MCP or sent to the optional AI below.

Messages kept before this was added show as before (their text and simple formatting), with a line saying the original can’t be shown; Waypoint doesn’t fetch them again on its own.

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
