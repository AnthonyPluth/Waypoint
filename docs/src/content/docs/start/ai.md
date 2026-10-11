---
title: AI suggestions
description: The optional AI that suggests the booking in mail Waypoint couldn’t read. Off by default, local or zero-data-retention only, and always confirmed by you.
sidebar:
  order: 6
---

**Settings → Mail and AI → AI** is off until you turn it on. When it’s on, mail that lands in [Review](/Waypoint/start/review/)’s “Couldn’t read” list from then on is also offered to an AI, which suggests the booking in it. Items already in the list when you turn it on are not offered. A booking Waypoint could already read is never sent.

## Choosing where it runs

- **Off.** Email never goes to an AI.
- **Local (Ollama).** An [Ollama](https://ollama.com) server on your own network: enter its address and a model. The email text never leaves your network.
- **OpenRouter.** [OpenRouter](https://openrouter.ai) with a model and your key. Every request sets `provider.data_collection: "deny"` and `provider.zdr: true`, so only providers that keep no prompts and don’t train on them can answer. If none can for your model, nothing is sent and the item says so: choose another model.

The OpenRouter key is saved encrypted with `WAYPOINT_SECRET_KEY` (and encrypted in backups), or read from the `OPENROUTER_API_KEY` environment variable, which wins. It never shows again once saved, and is never logged.

## What is sent

The setting is the household’s: any member can change it, and once it’s on, new “Couldn’t read” mail from every connected mailbox is offered, not just the mailbox of whoever turned it on. Whoever sets the Ollama address chooses where that mail goes, so use a server you trust.

Only the message’s plain text, and only for an item in “Couldn’t read” (when a scan queues it, or when you choose **Ask AI** on it). Before it goes, Waypoint cuts quoted replies, everything under a reply header or a `-- ` signature, and footer lines (unsubscribe, privacy notices), and replaces numbers that are labelled as a loyalty, Known Traveler, account or card number, long digit runs, letter-prefixed IDs of eight or more characters (such as `TT12345678`), plus every number saved under [Loyalty](/Waypoint/start/loyalty/), wherever it’s written. The sender and the subject are not sent. Names and anything else written in the body are, so a traveller’s name in the email goes to the model. Prompts and replies are never logged. Only `domain/mail/ai.py` sends email text anywhere, and a lint rule keeps AI addresses out of the rest of the code.

## What comes back

The reply must be JSON with the fields of a booking: kind, provider, confirmation code, origin, destination, start and end times, and zones for hotels, cars, trains and cruises. For a hotel, car, train or cruise it may also hold the **address** (the hotel’s, the rental’s pick-up place’s, the station’s or the cruise terminal’s); for a hotel, car or cruise the **phone number** the email prints for the property or company (so **Call** works); and for a cruise the **cabin**, **ship** and **deck**. Nothing is asked for a flight beyond its airports. These are the only details it reads: Waypoint doesn’t read a seat from an email this way.

Anything the booking needs that is wrong throws the whole reply away, and the item shows a short note saying so: a time that isn’t a date and time, an unknown kind, a missing place, a confirmation code that isn’t in the email, a reply that isn’t JSON. A field the AI adds that Waypoint didn’t ask for is ignored.

The address, phone, cabin, ship and deck are held to a stricter rule that costs only the field: each must appear in the email text that was sent (ignoring spaces, case, hyphens, commas and line breaks), and an address must be one plain line of at most 200 characters with no phone number or email address in it. One that fails is left empty and the rest of the suggestion is kept, so a made-up address never reaches the form.

The AI is told to give the property’s address, never the guest’s or the booker’s, and Waypoint checks it as well: an address or phone number is dropped when it is printed in a block that is labelled booker, booked by, guest, billing, cardholder or customer (the heading or label on the lines just above it, within the same paragraph). Waypoint doesn’t keep anyone’s home address, so that label is how the booker’s own address is told apart; an address printed without such a label can’t be told apart, which is why you check it. Redaction leaves postal addresses alone (an address isn’t a loyalty number). Waypoint keeps the suggestion’s fields with the review item, never the email or the AI’s reply.

A suggestion is a draft. **Check suggestion** opens the same form as **Add by hand**, filled in, with the address and the other details the AI read outlined so you check them first; you change what’s off and add it. Nothing is saved as a booking until you do.

Several flights in one email become several suggestions. The model replies with a list of bookings, one for each flight (a round trip is an outbound and a return, each with its own airports, date, times and flight number), and each is checked on its own: a flight that leaves from and arrives at the same airport, or that lasts longer than 30 hours, is left out with a reason, and the others are kept. In Review the item shows one editable suggestion for each flight, in order, with **Dismiss** for a flight you don’t want and a single **Add 2 flights** (the count of flights) that adds them together; they land in the same trip when their dates fit one. The form also warns, without stopping you, when a flight is longer than 30 hours (“This flight is 6 days long. Check the times.”). Items made before this keep their one suggestion; **Ask again** gets the new reading.

## Turning it off

Choosing **Off** stops the sending at once, including a scan that’s under way: the setting is read again before each message.
