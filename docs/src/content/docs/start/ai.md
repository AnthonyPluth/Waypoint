---
title: AI suggestions
description: The optional AI that suggests the booking in mail Waypoint couldn’t read. Off by default, local or zero-data-retention only, and always confirmed by you.
sidebar:
  order: 6
---

**Settings → Mail & review → AI** is off until you turn it on. When it’s on, you can choose **Ask AI** on an item in [Review](/Waypoint/start/review/) (in Check suggestions or Add missing details), and an AI suggests the booking. A booking Waypoint could already read is never sent. Nothing is sent until someone chooses **Ask AI**, unless you also turn on the second switch below.

## Choosing where it runs

- **Off.** Email never goes to an AI.
- **Local (Ollama).** An [Ollama](https://ollama.com) server on your own network: enter its address and a model. The email text goes to that server exactly as it was written, with nothing cut or replaced (see What is sent), and never leaves your network.
- **OpenRouter.** [OpenRouter](https://openrouter.ai) with a model and your key. Every request sets `provider.data_collection: "deny"` and `provider.zdr: true`, so only providers that keep no prompts and don’t train on them can answer. If none can for your model, nothing is sent and the item says so: choose another model.

The OpenRouter key is saved encrypted with `WAYPOINT_SECRET_KEY` (and encrypted in backups), or read from the `OPENROUTER_API_KEY` environment variable, which wins. It never shows again once saved, and is never logged.

Complete AI results are added to trips automatically. Partial results stay in Review. Automatic filing requires a confirmation code, places, local departure/check-in and arrival/check-out dates and times, and resolvable time zones; flights also need a flight number. No facts are invented to complete a booking. Turning on AI or its automatic-reading switch still controls whether email is sent to the chosen AI service.

## Reading unreadable mail automatically

Below the choice of where the AI runs, **Read unreadable mail with AI automatically** is a second, separate switch. It is off until you turn it on, and it is offered only while the AI is set to Local or OpenRouter. Turning it on shows a warning: “Waypoint will send the text of travel emails it couldn’t read to the AI you chose, without asking each time.” Choosing **Off** for the AI turns this switch off with it.

Both switches are needed. With the AI off, or with this switch off, a scan sends no email text anywhere; **Ask AI** on an item still works either way. With both on, a scan asks the AI about a message by itself only when all of these hold:

- It passed Waypoint’s check for travel mail with a strong travel signal: it is from a travel sender Waypoint knows, or it is in a label you picked, or it carries structured booking data, or its subject and snippet have two or more travel words. Shopping, codes, newsletters and replies are never sent.
- No reader made a booking from it.
- It isn’t a follow-up of a booking you can see (a receipt, a check-in notice or a reminder that Waypoint attaches to the booking).

A message a reader did turn into a booking is also sent when that booking lacks a detail the AI can read, such as a flight's cabin, a hotel's address or phone, a cruise's ship, or the total. The AI only fills in what is missing: it never changes a time, place or code a reader found, and it never adds a booking, because an answer is used only when it is for a booking you already have. Messages that were fully read are not sent.

There is no limit on how many messages a scan asks about. A request that fails leaves the item as it was, with a note that the AI couldn’t be asked, and is tried again on the next scans, at most twice more. Each mailbox’s last-scan line in Settings says how many messages the AI was asked about. A count only, never a subject, a sender or any text.

What is sent, whether it is redacted (it is for OpenRouter, not for Local) and where it goes are exactly the same as for **Ask AI**. The item in Review shows the suggestion as it does any AI suggestion, with a **read automatically** label so you can tell it wasn’t asked for. A result that is complete is added to your trips by itself, and one that isn’t stays in Review for you to complete.

## What is sent

The setting is the household’s: any member can change it, and once the automatic switch is on, qualifying mail from every connected mailbox is sent, not just the mailbox of whoever turned it on. Whoever sets the Ollama address chooses where that mail goes, so use a server you trust.

Only the message’s plain text, and only for an item in Review’s Check suggestions or Add missing details (when you choose **Ask AI** on it, or, with the automatic switch on, when a scan reads it by itself as above).

**With Local (Ollama), the text goes to your Ollama server unredacted and untrimmed**: quoted replies, signatures and footers stay, and email addresses, loyalty, Known Traveler, account and card numbers, long digit runs and the numbers saved under [Loyalty](/Waypoint/start/loyalty/) are sent as written. This is the household’s choice, because the model runs on your own network; it means those numbers do reach that server, so use one you trust and don’t point it at a hosted address. The sender and the subject are still not sent, and prompts and replies are never logged.

**With OpenRouter, the text is redacted first.** Before it goes, Waypoint cuts quoted replies, everything under a reply header or a `-- ` signature, and footer lines (unsubscribe, privacy notices), and replaces every email address (including the ones in a forwarded message’s From, To and Cc lines, in `<angle brackets>` and in `mailto:` links) with `[email]`, before anything else, and replaces numbers that are labelled as a loyalty, Known Traveler, account or card number, long digit runs, letter-prefixed IDs of eight or more characters (such as `TT12345678`), plus every number saved under [Loyalty](/Waypoint/start/loyalty/), wherever it’s written. The sender and the subject are not sent, and no email address is, wherever it is written in the body. Names and anything else written in the body are, so a traveller’s name in the email goes to the model. Prompts and replies are never logged. The redaction is the OpenRouter rule only; the Local rule is above. Only `domain/mail/ai.py` sends email text anywhere, and a lint rule keeps AI addresses out of the rest of the code.

### Who can ask

Anyone who can see an unread item in Review can choose **Ask AI** on it, or **Ask AI about all** (**Ask AI about these N emails** when Review is narrowed to one sender or mailbox, which asks only about those): the mailbox’s owner, and every other member for an item in a mailbox its owner [shared with the household](/Waypoint/start/review/#sharing-a-mailboxs-items-with-the-household). Someone who can’t see the item gets “No such item”, as for any other Review route, and an AI assistant connected over MCP can’t ask. For the owner, Waypoint fetches the message again from Gmail, as before. For another member it uses the message Waypoint already keeps for the item (kept text is capped per message) and, if none is kept, fetches it through the mailbox’s own connection. Either way the text goes through the same module and the same AI setting, and the suggestion is saved on the item for everyone who sees it. The AI setting must be on.

### The destination button on a trip

The one other thing this setting sends is for the sparkle button beside a trip’s destination (see [Trips](/Waypoint/start/trips/#the-destination-under-a-trips-dates)). It is there only while the AI is set to Local or OpenRouter, and only when someone presses it. It sends the trip’s name with its month and year taken off (and with email addresses and long numbers replaced, in case the name holds one) and, for each booking that isn’t cancelled, in the order of the trip, its kind and its place: the city and state or country of a flight’s arrival, or the state or country of a stay’s or rental’s address. It never sends email text, a date, a confirmation code, a traveller’s or a person’s name, an email address, a street address, a hotel’s name, a provider, a link, a note or a loyalty number. The same rules as for mail apply to where it goes: your own Ollama, or OpenRouter with `provider.data_collection: "deny"` and `provider.zdr: true`. The reply must be a plain phrase of at most 60 characters on one line; anything else is thrown away with a message. Nothing is logged but counts, and the answer is not saved until you save the field.

## What comes back

The reply must be JSON with the fields of a booking: kind, provider, confirmation code, origin, destination, start and end times, and zones for hotels, cars, trains and cruises. It may also give the booking’s **total** and its currency: the instructions to the model ask for it only when the email labels the amount as the total, grand total, amount charged or amount paid, and Waypoint checks it against the text that was sent (the amount must be printed there, and its currency’s code or symbol must be too) and keeps it as a suggested cost in the form, where you can correct or clear it. A total that doesn’t check out is left out and the rest of the suggestion is kept. What is sent is unchanged by this; only the reply has two more fields. For a hotel, car, train or cruise it may also hold the **address** (the hotel’s, the rental’s pick-up place’s, the station’s or the cruise terminal’s); for a hotel, car or cruise the **phone number** the email prints for the property or company (so **Call** works); and for a cruise the **cabin**, **ship** and **deck**. For a flight it may also hold the **flight number** and **cabin**, and, only with **Local (Ollama)**, each traveller’s **seat** (below). These are the only details it reads.

Anything the booking needs that is wrong throws the whole reply away, and the item shows a short note saying so: a time that isn’t a date and time, an unknown kind, a missing place, a confirmation code that isn’t in the email, a reply that isn’t JSON. A field the AI adds that Waypoint didn’t ask for is ignored.

The address, phone, cabin, ship and deck are held to a stricter rule that costs only the field: each must appear in the email text that was sent (ignoring spaces, case, hyphens, commas and line breaks), and an address must be one plain line of at most 200 characters with no phone number or email address in it. One that fails is left empty and the rest of the suggestion is kept, so a made-up address never reaches the form.

The AI is told to give the property’s address, never the guest’s or the booker’s, and Waypoint checks it as well: an address or phone number is dropped when it is printed in a block that is labelled booker, booked by, guest, billing, cardholder or customer (the heading or label on the lines just above it, within the same paragraph). Waypoint doesn’t keep anyone’s home address, so that label is how the booker’s own address is told apart; an address printed without such a label can’t be told apart, which is why you check it. Redaction leaves postal addresses alone (an address isn’t a loyalty number). Waypoint keeps the suggestion’s fields with the review item, never the email or the AI’s reply.

A suggestion is a draft. **Check suggestion** opens the same form as **Add by hand**, filled in, with the address and the other details the AI read outlined so you check them first; you change what’s off and add it. Nothing is saved as a booking until you do.

Several flights in one email become several suggestions. The model replies with a list of bookings, one for each flight (a round trip is an outbound and a return, each with its own airports, date, times and flight number), and each is checked on its own: a flight that leaves from and arrives at the same airport, or that lasts longer than 30 hours, is left out with a reason, and the others are kept. In Review the item shows one editable suggestion for each flight, in order, with **Dismiss** for a flight you don’t want and a single **Add 2 flights** (the count of flights) that adds them together; they land in the same trip when their dates fit one. The form also warns, without stopping you, when a flight is longer than 30 hours (“This flight is 6 days long. Check the times.”). Items made before this keep their one suggestion; **Ask again** gets the new reading.

With **Local (Ollama)**, Waypoint asks the model not to think first, which keeps replies short and quick. When that first answer looks wrong, it asks once more with thinking turned on and keeps whichever answer holds more usable bookings. The answer looks wrong when it isn’t a booking Waypoint can use, when a flight was left out for being impossible, when some of the bookings in it were left out, or when the email prints more flight numbers than the answer has flights. The second request is as slow as a thinking model is, so it is made only then, and your Ollama server sees it as another request with the same text. If it fails or is no better, the first answer stands. OpenRouter is not asked a second time.

## Seats on a flight (Local only)

With **Local (Ollama)** the model is also asked, for a flight, which traveller has which seat when the email prints a seat for each passenger by name. With **OpenRouter** nothing about seats is asked and a seat in the reply is ignored, so a traveller’s name and seat never leave your network. There is no separate switch: it follows the AI setting. What is sent is unchanged; only the instructions and the reply have more in them.

Waypoint matches seats from the email’s text. It never chooses or assigns a seat, and it can’t book one. A seat is kept for a traveller only when both the traveller’s name and the seat appear in the text that was sent (a seat must stand alone, such as `23A` or `23 A`, not inside a longer code), and the seat must be printed right beside the name: the first seat after the name on its line (within about 60 characters), else the last one just before it, else the first one on the next line, so two passengers’ seats swapped by the model are dropped. One that fails is dropped and the rest of the suggestion is kept. A name given twice, or two travellers given the same seat, are dropped too, as ambiguous. Flights only: a hotel, car, train, cruise or parking suggestion never takes seats.

In the form the seats show under the flight, one per traveller by name as printed, outlined like the other details the AI read so you check them first. When you add the flight, a name that matches one person in [People](/Waypoint/start/people/) (by display name, legal name or alias) is put on the flight as that person, and any other name stays as printed; you can change a seat before adding. Seats are saved with the suggestion in Review, never the email. This applies to the suggestion in Review only: when an assistant adopts a suggestion over [MCP](/Waypoint/start/mcp/), the seats are not carried over.

## Turning it off

Choosing **Off**, or turning the automatic switch off, stops the sending at once, including a scan that’s under way: the settings are read again before each message.
