---
title: AI suggestions
description: The optional AI that suggests the booking in mail Waypoint couldn’t read. Off by default, local or zero-data-retention only, and always confirmed by you.
sidebar:
  order: 6
---

**Settings → AI** is off until you turn it on. When it’s on, the mail in [Review](/waypoint/start/review/)’s “Couldn’t read” list is also offered to an AI, which suggests the booking in it. A booking Waypoint could already read is never sent.

## Choosing where it runs

- **Off.** Email never goes to an AI.
- **Local (Ollama).** An [Ollama](https://ollama.com) server on your own network: enter its address and a model. The email text never leaves your network.
- **OpenRouter.** [OpenRouter](https://openrouter.ai) with a model and your key. Every request sets `provider.data_collection: "deny"` and `provider.zdr: true`, so only providers that keep no prompts and don’t train on them can answer. If none can for your model, nothing is sent and the item says so: choose another model.

The OpenRouter key is saved encrypted with `WAYPOINT_SECRET_KEY` (and encrypted in backups), or read from the `OPENROUTER_API_KEY` environment variable, which wins. It never shows again once saved, and is never logged.

## What is sent

Only the message’s plain text, and only for an item in “Couldn’t read”. Before it goes, Waypoint cuts quoted replies, everything under a reply header or a `-- ` signature, and footer lines (unsubscribe, privacy notices), and replaces anything that looks like a loyalty, Known Traveler or card number, plus every number saved under [Loyalty](/waypoint/start/loyalty/), wherever it’s written. The sender, subject and your name are not sent. Prompts and replies are never logged. Only `domain/mail/ai.py` sends email text anywhere, and a lint rule keeps AI addresses out of the rest of the code.

## What comes back

The reply must be JSON with exactly the fields of a booking (kind, provider, confirmation code, origin, destination, start and end times, and zones for hotels, cars and trains). Anything else (an extra field, a time that isn’t a date and time, a confirmation code that isn’t in the email, a reply that isn’t JSON) is thrown away, and the item shows a short note saying so. Waypoint keeps the suggestion’s fields with the review item, never the email or the AI’s reply.

A suggestion is a draft. **Check suggestion** opens the same form as **Add by hand**, filled in; you change what’s off and add it. Nothing is saved as a booking until you do.

## Turning it off

Choosing **Off** stops the sending at once, including a scan that’s under way: the setting is read again before each message.
