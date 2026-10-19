---
title: AI suggestions
description: The optional AI that suggests the booking in mail Waypoint couldn’t read. Off by default, and local or zero-data-retention only.
sidebar:
  order: 6
---

**Settings → Mail & review → AI** is off until you turn it on. When it’s on, you can choose **Ask AI** on an item in [Review](/Waypoint/start/review/) (under Check suggestions or Add missing details) and a model suggests the booking. A booking Waypoint could already read is never sent. Nothing is sent until someone chooses **Ask AI**, unless you also turn on the second switch below.

## Choosing where it runs

- **Off.** Email never goes to an AI.
- **Local (Ollama).** An [Ollama](https://ollama.com) server on your own network: enter its address and a model. The email text goes to it exactly as written and never leaves your network.
- **OpenRouter.** [OpenRouter](https://openrouter.ai) with a model and your key. Every request sets `provider.data_collection: "deny"` and `provider.zdr: true`, so only providers that keep no prompts and don’t train on them can answer. If none can for your model, nothing is sent and the item says so: choose another model.

The OpenRouter key is saved encrypted with `WAYPOINT_SECRET_KEY` (in backups too), or read from the `OPENROUTER_API_KEY` environment variable, which wins. It never shows again once saved and is never logged.

Complete results are added to trips automatically; partial ones stay in Review. A result is complete when it has a confirmation code, places, local departure or check-in and arrival or check-out dates and times, and resolvable time zones (flights also need a flight number). No facts are invented to complete a booking.

## Reading unreadable mail automatically

**Read unreadable mail with AI automatically** is a second, separate switch below the choice of where the AI runs. It is off until you turn it on and offered only while the AI is set to Local or OpenRouter. Turning it on shows a warning: “Waypoint will send the text of travel emails it couldn’t read to the AI you chose, without asking each time.” Choosing **Off** for the AI turns the switch off with it.

Both switches are needed: with either off, a scan sends no email text anywhere, though **Ask AI** on an item works either way. With both on, a scan asks the AI about a message by itself only when all of these hold:

- It passed Waypoint’s check for travel mail with a strong travel signal: it is from a travel sender Waypoint knows, is in a label you picked, carries structured booking data, or has two or more travel words in its subject and snippet. Shopping, codes, newsletters and replies are never sent.
- No reader made a booking from it.
- It isn’t a follow-up of a booking you can see (a receipt, check-in notice or reminder that Waypoint attaches to the booking).

A message a reader did turn into a booking is also sent when that booking lacks a detail the AI can read, such as a flight’s cabin, a hotel’s address or phone, a cruise’s ship, or the total. The AI only fills in what is missing: it never changes a time, place or code a reader found, and never adds a booking. Messages with nothing missing aren’t sent. Filling gaps this way needs the consent in the warning as it now reads: a household that turned the switch on under its earlier wording keeps the narrower behaviour (unreadable mail only) until someone turns the switch off and on again.

There is no limit on how many messages a scan asks about. A request that fails leaves the item as it was, with a note that the AI couldn’t be asked, and is tried again on the next scans, at most twice more. Each mailbox’s last-scan line in Settings says how many messages the AI was asked about, a count only.

What is sent, whether it is redacted and where it goes are exactly as for **Ask AI**. The item in Review shows the suggestion with a **read automatically** label, and a complete result is added to your trips by itself.

## What is sent

The setting is the household’s: any member can change it, and once the automatic switch is on, qualifying mail from every connected mailbox is sent. Whoever sets the Ollama address chooses where that mail goes, so use a server you trust.

Only the message’s plain text goes out, for an item in Check suggestions or Add missing details. The sender, subject, images and markup are not sent, and prompts and replies are never logged. Only one part of Waypoint sends email text anywhere.

- **Local (Ollama): unredacted and untrimmed.** Quoted replies, signatures, email addresses and loyalty, Known Traveler, account and card numbers go as written, including the numbers saved under [Loyalty](/Waypoint/start/loyalty/). Those numbers do reach your Ollama server, so use one you trust and don’t point it at a hosted address.
- **OpenRouter: redacted first.** Waypoint cuts quoted replies, signatures and footer lines (unsubscribe, privacy notices), replaces every email address, wherever written, with `[email]`, and replaces numbers labelled as a loyalty, Known Traveler, account or card number, long digit runs, letter-prefixed IDs of eight or more characters (such as `TT12345678`) and every number saved under Loyalty. Names and anything else in the body are sent, so a traveller’s name goes to the model.

### Who can ask

Anyone who can see an unread item in Review can choose **Ask AI** on it, or **Ask AI about all**: the mailbox’s owner, and every other member for a mailbox its owner [shared with the household](/Waypoint/start/review/#sharing-a-mailboxs-items-with-the-household). Someone who can’t see the item gets “No such item”, and an AI assistant connected over MCP can’t ask. The text goes through the same setting whoever asks, and the suggestion is saved on the item for everyone who sees it.

### The destination button on a trip

The sparkle button beside a trip’s destination ([Trips](/Waypoint/start/trips/#the-destination-under-a-trips-dates)) is the one other thing this setting sends, and only when someone presses it while the AI is set to Local or OpenRouter. It sends:

- the trip’s name with its month and year taken off (and email addresses and long numbers replaced, in case the name holds one);
- for each booking that isn’t cancelled, in trip order, its kind and its place: the city and state or country of a flight’s arrival, or the state or country of a stay’s or rental’s address.

It never sends email text, a date, a confirmation code, a traveller’s or person’s name, an email address, a street address, a hotel’s name, a provider, a link, a note or a loyalty number. It goes to the same place as mail does. The reply must be a plain phrase of at most 60 characters on one line, and the answer isn’t saved until you save the field.

## What comes back

The reply must be JSON with the fields of a booking: kind, provider, confirmation code, origin, destination, start and end times, and zones for hotels, cars, trains and cruises. A reply with a bad time, an unknown kind, a missing place, a confirmation code that isn’t in the email or text that isn’t JSON is thrown away whole, and the item says so.

It may also hold these details:

- the **total** and currency. The model is asked for it only when the email labels the amount as the total, grand total, amount charged or amount paid, and Waypoint keeps it as a suggested cost only if the amount and its currency code or symbol are printed in the text that was sent. Otherwise the total is left out and the rest is kept;
- for a hotel, car, train or cruise, the **address**; for a hotel, car or cruise, the **phone number** (so **Call** works); for a cruise, the **cabin**, **ship** and **deck**; for a flight, the **flight number** and **cabin**, and with Local only each traveller’s **seat** (below).

Each of these must appear in the text that was sent, or it is left empty without losing the rest. The model is told to give the property’s address, never the guest’s or booker’s, and Waypoint drops an address or phone printed in a block labelled booker, booked by, guest, billing, cardholder or customer. An address with no such label can’t be told apart, so check it. Waypoint keeps the suggestion’s fields with the review item, never the email or the model’s reply.

**Check suggestion** opens the same form as **Add by hand**, filled in, with the details the AI read outlined so you check them first. Several flights in one email become one suggestion each, with **Dismiss** for any you don’t want and one **Add 2 flights** that adds them together. A flight that leaves and arrives at the same airport, or lasts longer than 30 hours, is left out with a reason.

With Local (Ollama), Waypoint first asks the model not to think. When that answer looks wrong (not a usable booking, or flights or bookings left out), it asks once more with thinking on and keeps the better answer; your Ollama server sees that as another request with the same text. OpenRouter is not asked a second time.

## Seats on a flight (Local only)

With Local (Ollama) the model is also asked which traveller has which seat, when the email prints a seat for each passenger by name. With OpenRouter nothing about seats is asked and a seat in the reply is ignored, so a traveller’s name and seat never leave your network.

Waypoint keeps a seat for a traveller only when the name and the seat both appear in the text that was sent and the seat is printed right beside the name; anything else, including a name given twice or two travellers given one seat, is dropped. It never chooses or books a seat. In the form the seats show under the flight, outlined so you check them first, and a name that matches one person in [People](/Waypoint/start/people/) is put on the flight as that person. Seats are saved with the suggestion in Review, never the email, and aren’t carried over when an assistant adopts a suggestion over [MCP](/Waypoint/start/mcp/). Only flights take seats.

## Turning it off

Choosing **Off**, or turning the automatic switch off, stops the sending at once, including a scan under way: the settings are read again before each message.
