---
title: Email scanning
description: What Waypoint reads in your mailbox, what leaves your server, and what it keeps. A message is kept, encrypted with its images and layout, only while a review item or a booking needs it.
sidebar:
  order: 1
---

Waypoint learns about bookings mainly by reading confirmation emails in a Gmail account you connect ([Google OAuth client for Gmail](/Waypoint/start/gmail/)). This page says what it reads, what leaves your server and what it keeps. How a scan works is under [Scanning](/Waypoint/start/gmail/#scanning), and what it couldn’t read waits in [Review](/Waypoint/start/review/).

## What a scan reads

- **Read-only.** Waypoint asks Google for read-only access. It can’t send, delete, label or change anything, and you can revoke the access in your Google account at any time.
- **Your server only.** Your own Waypoint reads the mailbox, with an OAuth client you create. Nothing goes through a service run by the project.
- **Triage first.** Waypoint asks Google for only each message’s subject, sender and a short snippet, and downloads only the messages those say are worth reading. One-time codes, newsletters, auto-replies, replies and shopping mail are never downloaded, and nothing of a skipped message is kept.
- **Labels you pick.** Messages in Gmail labels you choose are read in full. Only you can see or change your picks, and no AI assistant can reach them.
- **Forwards.** A forwarded message is read as the original. The original’s sender is whatever the forward’s header says, so anyone who can email you could write a forward claiming to be a sender you trust; that only ever files a booking into your own mailbox’s trips.
- **Counts only.** Settings shows each scan’s counts and nothing else, which is also all that is logged: no subject, sender or text.

## What is kept

A message’s body is fetched and parsed in memory. Waypoint keeps what it found (a flight number, a time, a confirmation code) and a reference to the message, its Gmail id.

- **The connection.** The Gmail address, a refresh token, and where its scans had got to (the point in Gmail’s history, and when the last one finished or what stopped it). The refresh token is encrypted with `WAYPOINT_SECRET_KEY` (in backups too), decrypted only to refresh or revoke it, and never appears in logs or error pages. Access tokens aren’t kept. Restoring a backup needs the same key; otherwise the connections turn to **Reconnect** ([Configuration](/Waypoint/reference/configuration/)).
- **Messages already read.** Their Gmail ids, so none is read twice. For a message from a sender you ignored, that record also keeps the sender’s domain, and stopping the ignore deletes it.
- **The message itself, only while something needs it.** That is a [Review](/Waypoint/start/review/) item waiting for it, or a booking made from it. Mail that made no booking and wasn’t queued for review is never kept.
  - It keeps the subject, who it was from and the day, its text and, for an HTML message, its layout and images. The layout is markup rebuilt on the server from a safe subset (colours, fonts, sizes, spacing, alignment, tables) with nothing that runs or loads: no scripts, event handlers, style blocks, forms or remote pictures.
  - A long message is kept in full up to 300,000 characters of text and 900,000 of markup, past which Waypoint says “This email was cut short”.
  - It is stored as one encrypted value under the same key as the Gmail connection, so a copy of the database or a backup doesn’t show it, images included, without that key.
  - It is deleted, images with it, when its item is dismissed (unless a booking was made from it, which keeps it), when the last booking made from it is removed, when its mailbox is disconnected, and when a member taps **Done** on a trip that ended at least 7 days ago, for that trip’s bookings ([Done with a trip](/Waypoint/start/trips/#done-with-a-trip)).
- **An email for a booking you already have** is kept with that booking, shown beside the others, newest first, for as long as the booking exists. When it is the same booking as one the mailbox’s owner can see ([Merging into your trips](/Waypoint/start/gmail/#merging-into-your-trips)), Waypoint makes no second booking. A booking the owner can’t see is never matched.
- **Follow-up mail is recognised, not kept.** A later email about a booking Waypoint already has (a receipt, a check-in notice, a reminder) is matched to it by the confirmation code in its text, against the bookings the mailbox’s owner can see. It is attached only when the visible bookings with that code from the same company are one reservation, never from dates or names alone, and an email that says a booking has been cancelled, changed or rescheduled is left for a person. Only the Gmail id and the booking’s id are recorded: no text, subject or code.
  - One exception: a follow-up about a parking booking that holds a picture that looks like the gate’s QR code (a small, near-square PNG or JPEG not repeated in the message) keeps that picture alone with the booking, encrypted like a message’s images and shown only to those who can see the booking ([The gate code of a parking booking](/Waypoint/start/trips/#the-gate-code-of-a-parking-booking)).
  - Review items that name the same code show as one row. For that, each keeps a keyed hash of its code, never the code, deleted with the item.
- **Your own device.** If you set up [offline access](/Waypoint/start/offline/), the messages kept for the bookings on the trips saved there (text and formatting, not images) are part of the copy Waypoint saves on the device, encrypted, for you only. It is cleared when you sign out, when you turn offline off and three days after each trip ends.

The message is never logged, reported or sent to any service other than Gmail’s own API and, if you turn it on, the optional AI ([below](#optional-ai-suggestions)). No AI assistant connected over MCP can read its text and kept markup (never images) unless you switched on **Read email text** for that one connection in Settings, which is off by default ([AI assistants](/Waypoint/start/mcp/#reading-email-text-optional)). The project’s tests hold the code to this: they run made-up emails through a scan while watching the database for the text in the clear, the log and every request.

## Who can see it

- **Trips.** A booking is visible to the people on the trip, the person who booked it, and whoever got its confirmation in their own mailbox (the same email in two members’ mailboxes is one booking, shown to both). Anyone who can see a booking can read the email it was made from and see its images; no one else can.
- **Review items.** Mail Waypoint couldn’t read is the mailbox owner’s alone unless they [share the mailbox’s items with the household](/Waypoint/start/review/#sharing-a-mailboxs-items-with-the-household). Then the household sees each one’s subject, sender and day and can read the message beside the Add by hand form.
- **Connections.** Each member connects their own Gmail and sees only their own. A connection ends when its owner can no longer sign in. Anyone you let in can still download a backup, which holds the encrypted tokens ([SECURITY.md](https://github.com/AnthonyPluth/Waypoint/blob/main/SECURITY.md)).

## What the sender can learn

Opening an email in Waypoint never contacts the sender. The email is shown inline in the page, inside an isolated container that can run no script and may load only images Waypoint itself gives it, so a tracking pixel can’t tell anyone that you looked.

The one thing that changes is when the message is kept (a booking was made from it, or it went to Review). Then your server downloads the images the message names, once, so they are still there if the sender removes them. To the sender that is a request from your server’s address for each image address in the message, which may carry whatever the sender put in that address, such as a code that identifies the message. The request has no cookies and nothing about you or Waypoint beyond a generic browser name, and happens once, not each time someone opens the email. Images attached to the message need no download.

- Only `https` addresses that resolve to public internet addresses are fetched. Private, loopback and link-local addresses are refused, including after a redirect or a changed DNS answer, and no proxy is used.
- Images are limited to 1 MB each, 6 MB and 40 per message, and a few seconds each and 30 per message. An image that fails or is refused is left out, and the message still opens.
- Only PNG, JPEG, GIF and WebP, decided by the file’s contents. SVG is refused, since it can carry script.
- Images are kept encrypted with the message and deleted with it. They are shown only to those who can see the booking or review item, through Waypoint’s own sign-in-protected addresses, and are never reachable by an AI assistant over MCP or sent to the optional AI. A parking booking’s gate-code picture is sealed the same way, goes with the booking and the mailbox, is never decoded and is never in the offline copy.

## How a booking is read

Waypoint tries the most reliable method first, and the first that yields a complete booking wins:

1. **schema.org markup.** Many airlines, hotels, rental companies and railways embed structured data (`FlightReservation`, `LodgingReservation`, `RentalCarReservation`, `TrainReservation`) in the email. Waypoint reads it directly.
2. **Per-vendor parsers** for senders without markup: Southwest Airlines and Disney Cruise Line. A parser sees the text in memory only. Disney’s reads the sailing, ship, stateroom, deck, each guest’s name (never their Castaway Club number) and the ports of call at each port’s own zone. A re-sent confirmation updates the same booking; its change and cancellation emails aren’t read.
3. **A calendar attachment** (`.ics`), read in memory and never stored. A booking is made only when the event names a kind: a flight number with two known airports, a hotel or stay, a car rental, a train or a cruise, with start and end times in a named zone. An event without a kind is ignored, and PDF attachments are not read.
4. **Generic readers** for a message with neither markup nor a vendor parser. They read labelled lines, table rows or two columns. Times are the place’s own, as the email gives them and never converted, and dates in cancellation, refund or “booked on” text are ignored.

| Reader | Needs | Limits |
| --- | --- | --- |
| Lodging | The place and both dates (or a start date and a number of nights) | Check-out after check-in, at most 60 nights. Times are the property’s, in the zone worked out from its address |
| Flights | A flight number, two airports Waypoint knows, and both dates and times | Arrival after departure, different airports, at most 30 hours in the air. A round trip gives one booking per flight; one that can’t be completed goes to Review while the others are kept |
| Rental cars | A pick-up place and both dates, and “car”, “rental” or “vehicle” in the message | Drop-off after pick-up, within 90 days. Without times it takes noon and marks the booking as having no time recorded |
| Trains | Both stations, dates and times, in a message about a train and not a flight | Arrival after departure, within 96 hours. An outbound and a return give two bookings |
| Cruises | The ship or the line, both ports and both dates | Disembarkation after embarkation, within 200 days. Without times it takes noon to embark and 8:00 to disembark. Ports of call aren’t read |

Whatever no method understands goes to Review, with the reason it couldn’t be read. Nothing is guessed silently.

### Languages the generic readers understand

| Reader | English | French | German | Spanish | Japanese |
| --- | --- | --- | --- | --- | --- |
| Lodging | yes | no | no | no | yes |
| Flights, rental cars, trains, cruises, calendar attachments | yes | yes | yes | yes | yes |

That covers the field labels, the words that say what kind of booking a message is about, the confirmation words, and the words that mark a cancellation or “booked on” line. Dates can be written “Nov 21, 2026”, “21 novembre 2026”, “21. November 2026”, “21 de noviembre de 2026”, “21.11.2026”, “2026-11-21” or “2026年11月21日”; a date such as 04/05/2026 that could be read two ways is not guessed.

A place’s time zone comes from an airport code written with it or from a city in Waypoint’s airport table. A US city needs its state or country beside it (“Galveston, TX”), and a name shared by cities in different zones is not guessed. A station is placed by the city in its name (“Zurich HB”). A place Waypoint can’t place is left for you to add by hand, with the reason, rather than given a zone that might be wrong.

Whether a message is read at all still depends on its subject, sender and snippet, whose booking words are mostly English and Japanese. A message in another language is read only when its subject or snippet also has one of them, or its sender is a known travel one.

## The total on a confirmation or receipt

When a message is read for a booking, Waypoint also looks for the booking’s total. If it finds a clearly labelled one, it stores three things on the booking: the amount in the currency’s smallest unit, the currency code, and whether it came from an email or was entered by hand. Nothing else about it is kept, not the line it was on, the label or the rest of the message. A follow-up to a booking you can see (one that names its confirmation code) can add a missing total the same way. Amounts are never converted and nothing is sent anywhere to read them. The cost is visible to exactly the people who see the booking ([Cost](/Waypoint/start/trips/#cost)).

## Optional AI suggestions

Off by default (**Settings → Mail & review → AI**; see [AI suggestions](/Waypoint/start/ai/)). Email text goes to a model only when you press **Ask AI** on a Review item, unless you also turn on the separate **Read unreadable mail with AI automatically** switch, which has its own warning: then a scan also sends the text of travel mail that no reader could read or that a reader left missing a detail. With either switch off, a scan sends no email text anywhere.

- **Local (Ollama)** on your own network. The text goes unredacted and untrimmed and never leaves your network, so loyalty and Known Traveler numbers in it reach your own server.
- **OpenRouter**, restricted to providers with zero data retention. The text goes with every email address replaced by `[email]`, quoted replies and footers removed, and labelled or number-shaped loyalty, Known Traveler and card numbers removed, as well as the numbers saved under Loyalty.

Only plain text goes out, never images or markup, and prompts and replies are never logged. What is sent, and what comes back, is under [AI suggestions](/Waypoint/start/ai/).

The same setting powers one small button that involves no email: the sparkle beside a trip’s destination. It sends only the trip’s name (without its dates) and the cities, states and countries of its bookings with their kinds, and only when you press it ([the destination button](/Waypoint/start/ai/#the-destination-button-on-a-trip)).

## Addresses are looked up on your server

A booking’s address or place is turned into a rough point on the map (the centre of its ZIP or postal code, an airport or a city) when the booking is saved, so the Stats map can show where you stayed. This happens entirely on your server from lists that ship with Waypoint ([Data sources](/Waypoint/reference/data-sources/)). No geocoding or map service is asked and the address is not sent anywhere ([Where a booking is on the map](/Waypoint/start/trips/#where-a-booking-is-on-the-map)).

## Live flight status is the one other thing that leaves the server

If you turn on [live flight status](/Waypoint/start/flight-status/), Waypoint asks AeroDataBox (through RapidAPI) about a flight by its number and date. The request carries nothing from your email or your trips beyond the flight number and date: no names, confirmation codes or loyalty numbers. It is off until you set a key.
