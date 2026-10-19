---
title: Reminders and calendar
description: Notifications before a flight and on the day, and a private calendar feed of your trips.
sidebar:
  order: 6
---

**Settings → Offline & notifications → Reminders and calendar** is yours alone: each member chooses their own reminders, devices and calendar feed.

## Reminders

Waypoint sends two kinds of notification, and each person chooses which they get (both are on until you choose):

- **Check-in opens**, 24 hours before a flight leaves. It names the flight, the airports and the departure time at the airport. A flight moved to another time gets a new reminder.
- **Day-of summary**, from 7:00 on Waypoint’s clock (`TZ`) on any day something starts: your flights, hotel check-ins, car pickups, trains, cruises and parking entries, each with its own local time.

Reminders cover only the trips you can see, the ones you’re on and the ones you booked. They never carry a loyalty or Known Traveler number or a confirmation code.

To get them on a phone or computer, open Settings there and choose **Register this device**; your browser asks for permission. On an iPhone or iPad, add Waypoint to the Home Screen first (iOS 16.4 or later). **Remove device** unregisters it. A person can have up to 10 devices.

Notifications go through your browser’s own push service (Google’s, Apple’s or Mozilla’s), which sees that a notification was sent to that browser, with its text encrypted so only your browser can read it.

## Calendar feed

**Make my calendar address** gives you a private address that your calendar app (Apple Calendar, Google Calendar, Outlook, …) can subscribe to. It holds the trips you can see, with each flight, stay, car, train, cruise and parking booking as an event. A flight booked on two reservations is one event, listing both confirmation codes. Calendar apps poll the address on their own schedule, often every few hours.

- Each event’s start and end carry the time zone of their own place, so a flight that leaves Auckland at 22:15 and lands in Los Angeles at 15:10 the same day shows exactly that, wherever your calendar is.
- The address is shown once. It holds a random key and Waypoint keeps only a hash of it, so it can’t show it again. Make a **new address** if you lose it; the old one stops working at once.
- Anyone who has the address can see your trips, so treat it like a password. **Turn off** ends it.
- With sign-in on, the address needs `WAYPOINT_PUBLIC_URL` set (see [Configuration](/Waypoint/reference/configuration/)), since that is what your calendar app fetches.

## When someone loses access

Devices and the feed end when their owner can no longer sign in, as browser sessions and [Gmail connections](/Waypoint/start/gmail/) do. Taken off `OIDC_ALLOWED_EMAILS`, they end within the hour or when anyone next opens Settings, and the feed stops the moment it is fetched. With `OIDC_ALLOWED_GROUPS`, which Waypoint can only check at sign-in, they end `WAYPOINT_SESSION_DAYS` after the person last signed in.

## In a backup

Your choice of reminders is part of a [backup](/Waypoint/start/docker/#moving-your-data-from-another-machine). Devices and calendar feeds aren’t: after a restore, turn notifications on again and make a new calendar address.
