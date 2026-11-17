---
title: AI suggestions
description: The optional AI that fills in what Waypoint couldn’t read in a booking email. Off until you save an Ollama address; the Settings card says where the text goes.
sidebar:
  order: 6
---

**Settings → Mail & review → AI** is off until you save an Ollama address. That is the whole choice: there is no mode to pick, no hosted provider and no second setting for reading mail automatically. Leave the address empty and nothing is ever sent. Once an address is saved, Waypoint sends the text of booking emails it couldn’t read fully to that [Ollama](https://ollama.com) server to fill the gaps, and you can choose **Ask AI** on an item in [Review](/Waypoint/start/review/) (under Check suggestions or Add missing details) to ask about one message yourself. A booking Waypoint read completely is never sent.

## Your Ollama server

Enter its address and a model, both or neither. It is a server on your own network: the email text goes to it exactly as written and never leaves your network, and Waypoint sends nothing to any other AI service. Whoever sets the address chooses where that mail goes, so use a server you trust.

Owner decisions of 2026-11-17 (issue #811): “use AI whenever a booking email has gaps, no additional toggle” and “kill OpenRouter support, force local AI, no option to disable AI: leave the Ollama address empty to not use AI”.

### Upgrading from an earlier version

Earlier versions had a mode (Off, Local, OpenRouter), an OpenRouter key and a “Read unreadable mail with AI automatically” switch. The upgrade (migration 0049) removes the mode, the OpenRouter model and key and the switch, and clears a saved Ollama address when the mode was anything but Local, so no household starts sending mail to a server it had switched off. A household that was on Local keeps its address and model, and now has gap filling and automatic reading with them. Restoring an older backup does the same. The `OPENROUTER_API_KEY` environment variable is no longer read.

Complete results are added to trips automatically; partial ones stay in Review. A result is complete when it has a confirmation code, places, local departure or check-in and arrival or check-out dates and times, and resolvable time zones (flights also need a flight number). No facts are invented to complete a booking.

## What a scan sends by itself

With an Ollama address saved, a scan asks the AI about a message by itself only when all of these hold:

- It passed Waypoint’s check for travel mail with a strong travel signal: it is from a travel sender Waypoint knows, is in a label you picked, carries structured booking data, or has two or more travel words in its subject and snippet. Shopping, codes, newsletters and replies are never sent.
- No reader made a complete booking from it: either no reader made one, or what a reader found has a gap (such as a hotel name that was really a price, a missing confirmation code, address or time zone), so it waits in Review.
- It isn’t a follow-up of a booking you can see (a receipt, check-in notice or reminder that Waypoint attaches to the booking).

A message a reader did turn into a booking is also sent when that booking lacks a detail the AI can read, such as a flight’s cabin, a hotel’s address or phone, a cruise’s ship, or the total. The AI only fills in what is missing: it never changes a time, place or code a reader found, and never adds a booking. Messages with nothing missing aren’t sent.

There is no limit on how many messages a scan asks about. A request that fails leaves the item as it was, with a note that the AI couldn’t be asked, and is tried again on the next scans, at most twice more. Each mailbox’s last-scan line in Settings says how many messages the AI was asked about and how many emails it attached to their bookings as nothing new, counts only.

What is sent and where it goes are exactly as for **Ask AI**. The item in Review shows the suggestion with a **read automatically** label, and a complete result is added to your trips by itself.

## Emails that aren’t bookings

When the AI finds no booking in a message, the item stays in Review with a note that no booking was found, whatever the message is: a promotion, a loyalty or account statement, a newsletter, a receipt or anything else. This applies to **Ask AI** and to a scan’s reading alike. Waypoint never dismisses an item because the AI thinks an email isn’t about a booking, and the model isn’t asked to say so (an answer that does is ignored): any pattern Waypoint could check an email against would miss some cancellation, change or booking, and a miss would delete the only copy. You dismiss the item yourself, which deletes the stored copy of the email.

- The AI’s answer, an error, a timeout or an answer Waypoint can’t read never takes an item off the list or deletes a stored email. A result with a booking in it is filed as before.
- A scan counts the emails the AI was asked about and the ones it attached as nothing new ([below](#emails-that-add-nothing-new)) in the mailbox’s last-scan line in Settings, never with a subject, sender or text.

An AI assistant connected over [MCP](/Waypoint/start/mcp/) still asks you before every change.

## Emails that add nothing new

When the AI reads a message automatically during a scan, Waypoint attaches it to a booking you can already see, instead of asking you in Review, in two narrow cases where the email adds nothing to that booking. The model only reads the email. Waypoint makes the decision by comparing the fields the model found with the saved booking, and never takes the model’s own word that nothing is new. Nothing is deleted: the email is kept with the booking, which shows it among its emails, and nothing on the booking changes. Any doubt leaves the email in Review, as before.

A complete reading of a booking you already have is never dismissed this way. It is filed as before: the email is kept with that booking and the item leaves Review, so nothing in it is lost and its date still counts when a later email is compared with it ([updated from a newer email](/Waypoint/start/trips/#updated-from-a-newer-email)).

The order of the emails decides, never the model. When the reading is of an email dated before the newest one kept for that booking (even one that says the booking changed), it never overwrites what the booking holds: the booking’s times, airports and details stay as they are. If everything it states is already on the booking, it is attached and leaves Review. If it says anything different (another time, a total the booking lacks, a traveller who isn’t on it), it stays in Review as a suggestion for you to check, and nothing is changed until you decide. The same holds for a booking that was cancelled, and an email with no date can add details the booking lacks but never replaces a time. A newer email, or one dated the same day as the newest, still updates the booking as before.

**Already known.** A flight reading the model couldn’t complete (a reminder or a check-in notice without the confirmation code, say), which would otherwise wait in Review, is attached only when all of these hold:

- It matches exactly one flight in the household on its flight number, its date and at least one airport, that flight is one you can see, and it is still confirmed. Two flights that both fit, or one that fits and that you can’t see, leaves the email in Review.
- Every field the email states is already saved on the booking, the same: times, airports, flight number, company, cabin, price, and each traveller on their own seat.

**Older copy.** A complete reading dated before the newest email already kept for the same reservation, which is still confirmed, is attached to it as an older copy, whatever times, airports and seats it states. Nothing on the booking changes, and because it is older, the newest email kept for the booking stays the one later emails are compared with. Everything else it states (a total, a company, a cabin, an address, a traveller) must already be on the booking, or it is filed as before.

For both, also:

- The email comes from someone the booking already trusts: its text carries the booking’s own confirmation code, or the message itself was sent from the same domain as an email already kept with that booking, or from a subdomain of it (never from the domain above it), and that kept email’s domain is one of the airlines, hotel groups, car rental companies, railways, booking sites and cruise lines Waypoint knows. The sender is the one on the message as it reached the mailbox, never one written in its text, so a forwarded email (with a forward line in its text or “Fwd:” in its subject) never counts as sent by the original sender, and a mail service or provider such as gmail.com, outlook.com, hotmail.fr or orange.fr, or any other domain Waypoint doesn’t know as a travel sender, never vouches for its users, whatever its address. A sender whose domain only names the airline, a booking made through a sender Waypoint doesn’t know, or any other sender without the code, leaves the email in Review.
- Neither the email’s text nor its subject has a word about a cancellation, change, refund, delay, gate, terminal, seat or boarding (cancellations and refunds in every language Waypoint reads), and the reader that looks for changes in mail found none. The subject is checked by Waypoint only and is not sent to the model.
- Every passenger the text names after a “Passenger”, “Traveller” or “Guest” label is already on the booking, seat or no seat.
- Every seat (such as 22A) and every time of day the text prints, in any layout, is one the booking already holds (for an older copy, also one the reading itself returned). A check-in deadline or a seat the booking doesn’t have keeps the email.
- The text holds nothing Waypoint can’t compare: no ticket, loyalty or member number, baggage, meal, price, total or rate, room, suite, bed, breakfast or vehicle, link, itinerary or note, no flight number the model didn’t return (however it is written: `EX102`, `EX 102`, `EX-102`, in lower case or after a “Flight” label), no day other than the days the model returned (a second date for the same flight number keeps it), and no confirmation code other than the booking’s own. Times, totals and passenger labels are recognised in the same formats Waypoint’s own readers accept, in any currency it knows. Any of these keeps the email in Review.
- The email isn’t about parking, the model answered without an error and could be reached, and AI reading is on. With no address saved, with the service down or for **Ask AI** by hand, nothing is dismissed this way.

An email’s date is the day its own `Date` line gives, but never later than the day it reached the mailbox (Gmail’s own record of when it arrived), so an email dated in the future can’t make a booking’s real later changes look older.

The mailbox’s last-scan line in Settings counts these with the reason, “already known” or “older than a saved copy” (“AI attached 3 emails that add nothing new to their bookings (2 already known, 1 older than a saved copy)”), and the log carries the same counts. Never a subject, sender or text.

## What is sent

The setting is the household’s: any member can change it, and once an address is saved, qualifying mail from every connected mailbox is sent.

Only the message’s plain text goes out, for an item in Check suggestions or Add missing details and for a message a scan found with gaps. It goes unredacted and untrimmed: quoted replies, signatures, email addresses and loyalty, Known Traveler, account and card numbers go as written, including the numbers saved under [Loyalty](/Waypoint/start/loyalty/). Those numbers do reach your Ollama server, so use one you trust and don’t point it at a hosted address. The sender, subject and markup are not sent, and prompts and replies are never logged. Pictures are not sent with the text either; the one case where they are sent is [the gate code of a parking booking](#picking-a-parking-gate-code), below. Only one part of Waypoint sends email text anywhere, and only to your Ollama server.

### Who can ask

Anyone who can see an unread item in Review can choose **Ask AI** on it, or **Ask AI about all**: the mailbox’s owner, and every other member for a mailbox its owner [shared with the household](/Waypoint/start/review/#sharing-a-mailboxs-items-with-the-household). Someone who can’t see the item gets “No such item”, and an AI assistant connected over MCP can’t ask. The text goes through the same setting whoever asks, and the suggestion is saved on the item for everyone who sees it.

### The destination button on a trip

The sparkle button beside a trip’s destination ([Trips](/Waypoint/start/trips/#the-destination-under-a-trips-dates)) is the one other thing this setting sends that involves no email, and only when someone presses it while an Ollama address is saved. It never involves email. It sends:

- the trip’s name with its month and year taken off (and email addresses and long numbers replaced, in case the name holds one);
- for each booking that isn’t cancelled, in trip order, its kind and its place: the city and state or country of a flight’s arrival, or the state or country of a stay’s or rental’s address.

It never sends email text, a date, a confirmation code, a traveller’s or person’s name, an email address, a street address, a hotel’s name, a provider, a link, a note or a loyalty number. It goes to your Ollama server. The reply must be a plain phrase of at most 60 characters on one line, and the answer isn’t saved until you save the field.

## What comes back

The reply must be JSON with the fields of a booking: kind, provider, confirmation code, origin, destination, start and end times, and zones for hotels, cars, trains and cruises. A reply with a bad time, an unknown kind, a missing place, a confirmation code that isn’t in the email or text that isn’t JSON is thrown away whole, and the item says so.

It may also hold these details:

- the **total** and currency. The model is asked for it only when the email labels the amount as the total, grand total, amount charged or amount paid, and Waypoint keeps it as a suggested cost only if the amount and its currency code or symbol are printed in the text that was sent. Otherwise the total is left out and the rest is kept;
- for a hotel, car, train or cruise, the **address**; for a hotel, car or cruise, the **phone number** (so **Call** works); for a cruise, the **cabin**, **ship** and **deck**; for a flight, the **flight number** and **cabin**, and each traveller’s **seat** (below).

Each of these must appear in the text that was sent, or it is left empty without losing the rest. The model is told to give the property’s address, never the guest’s or booker’s, and Waypoint drops an address or phone printed in a block labelled booker, booked by, guest, billing, cardholder or customer. An address with no such label can’t be told apart, so check it. Waypoint keeps the suggestion’s fields with the review item, never the email or the model’s reply.

**Check suggestion** opens the same form as **Add by hand**, filled in, with the details the AI read outlined so you check them first. Several flights in one email become one suggestion each, with **Dismiss** for any you don’t want and one **Add 2 flights** that adds them together. A flight that leaves and arrives at the same airport, or lasts longer than 30 hours, is left out with a reason.

Waypoint first asks the model not to think. When that answer looks wrong (not a usable booking, or flights or bookings left out), it asks once more with thinking on and keeps the better answer; your Ollama server sees that as another request with the same text.

## Seats on a flight

The model is also asked which traveller has which seat, when the email prints a seat for each passenger by name. Both go only to your Ollama server.

Waypoint keeps a seat for a traveller only when the name and the seat both appear in the text that was sent and the seat is printed right beside the name; anything else, including a name given twice or two travellers given one seat, is dropped. It never chooses or books a seat. In the form the seats show under the flight, outlined so you check them first, and a name that matches one person in [People](/Waypoint/start/people/) is put on the flight as that person. Seats are saved with the suggestion in Review, never the email, and aren’t carried over when an assistant adopts a suggestion over [MCP](/Waypoint/start/mcp/). Only flights take seats.

## Turning it off

Clearing the address stops the sending at once, including a scan under way: the settings are read again before each message.

## Picking a parking gate code

A parking booking’s email can hold several pictures that could be the QR code that opens the gate. Waypoint already picks by a fixed rule (a near-square PNG or JPEG, 100 to 1,000 pixels a side, not repeated in the message). When that rule leaves more than one and an Ollama address is saved, Waypoint sends those candidate pictures, and nothing else of the email (no text, subject or sender), to your own Ollama server and asks which one is the gate’s QR code. If it names one, that picture becomes the code with nothing for you to do.

- There is no separate switch; it applies only with an address saved, and only for a parking booking with more than one candidate (at most eight are sent), taken from the one message that brought the choice up, never from other emails of the booking.
- A message that holds more than one parking booking stays on **Choose the code**, because the model can’t tell which booking a picture belongs to. That count is the most the message was found to hold when it was read, so it still applies when one of them couldn’t be filed or you dropped it from the item; an item made before Waypoint kept the count is counted from what it still holds.
- It is asked when a scan files the booking and also when you resolve a Review item that links such a message to a parking booking: matching it to a booking, adding it as a booking, or adding it to one (asked when you finish the item, not at the attach), or finishing it with the booking it made, in the app or through an AI assistant. Your action is saved first, and the reply can take up to 30 seconds longer while the model answers; the question never fails or undoes the action, is asked once per action, and is asked only about the message that opened the choice, or the newest one to reopen it, whatever the dates of the others; a choice that was already waiting before this was recorded sends nothing until a later email reopens it. If it can’t pick, **Choose the code** stays as it was.
- During a scan the question is skipped when little of the scan’s time is left, and waits no longer than that time allows; the choice then stays with you.
- Waypoint never decodes the code itself; the model only chooses between the pictures.
- With no address saved, no picture is sent anywhere; pictures go only to your own Ollama server.
- A model that can’t read pictures, an error, a timeout or an answer that doesn’t clearly name one picture leaves **Choose the code** exactly as it was, with no message.
- The pictures stay on your network, and neither they nor the prompt or the reply are ever logged.
