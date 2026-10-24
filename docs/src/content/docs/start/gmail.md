---
title: Google OAuth client for Gmail
description: Create the Google Cloud OAuth client Waypoint uses to connect each member’s Gmail, read-only, and see how it scans.
sidebar:
  order: 3
---

Waypoint reads bookings from Gmail with a Google OAuth client that **you** create in your own Google Cloud project, so no one else’s app sits between your mailbox and your server. You set that up once for the household; after that, each member connects their own Gmail under **Settings → Mail & review → Gmail**.

What a scan reads and keeps is on [Email scanning](/Waypoint/privacy/email-scanning/). What it can’t turn into a booking waits in [Review](/Waypoint/start/review/).

## Create the client

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project (any name, such as “Waypoint”).
2. **APIs & Services → Library**: enable the **Gmail API**.
3. **APIs & Services → OAuth consent screen**: choose **External**, give it a name and your email, and add one scope, `https://www.googleapis.com/auth/gmail.readonly`. Waypoint asks for nothing else, so it can’t send, delete, label or change anything.
4. Set the publishing status to **In production** (**Publish app**). Leave it unverified: Google doesn’t need to review an app only your household uses, and each member clicks through its “Google hasn’t verified this app” warning once.

   :::caution[Don’t leave it in “Testing”]
   While an app is in **Testing**, Google expires its refresh tokens after 7 days, so every Gmail would turn to “Reconnect” weekly.
   :::
5. **APIs & Services → Credentials → Create credentials → OAuth client ID**: choose **Web application** and add this **authorized redirect URI**, using the address you open Waypoint at (`WAYPOINT_PUBLIC_URL`):

   ```
   https://waypoint.example.com/api/mailboxes/callback
   ```

   Without sign-in, on your own machine, use the address you open Waypoint at instead, such as `http://localhost:8765/api/mailboxes/callback`.
6. Copy the client ID and secret into `.env` and restart Waypoint:

   ```
   GOOGLE_CLIENT_ID=1234567890-example.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=GOCSPX-example
   ```

Until both are set, Settings says Gmail isn’t set up and shows no Connect button.

## Connect a Gmail

Each member chooses **Connect Gmail** under **Settings → Mail & review → Gmail**, picks the Google account and agrees to read-only access. A member can connect more than one address, and sees only their own connections.

- **Reconnect.** If Google stops honouring a connection (you removed Waypoint at [myaccount.google.com/permissions](https://myaccount.google.com/permissions), the grant expired, or Waypoint’s secret key changed), its row says **Reconnect**. Choosing it connects the same address again.
- **Disconnect.** Waypoint tells Google to revoke its access, then deletes the connection. If Google can’t be reached it keeps the connection and says so; try again, or remove Waypoint at the Google permissions page.
- **When someone loses access.** A connection ends when its owner can no longer sign in to Waypoint (taken off `OIDC_ALLOWED_EMAILS`, or past their sign-in with `OIDC_ALLOWED_GROUPS`). Waypoint checks before every use and once an hour, revokes the token at Google and deletes it.

## Scanning

Waypoint scans each connected mailbox in the background every few hours (by the server’s own clock, `TZ`) and when you choose **Scan now** under the mailbox. Complete bookings are added automatically, even from a sender Waypoint hasn’t seen before; incomplete ones and ambiguous matches go to Review.

A scan lists your mail newest first (everything except spam, trash and ignored senders, Promotions included) with no word search, so a trip email that never says “confirmation” is still found. The first scan looks back 18 months; later ones ask Gmail’s history what arrived since the last. For each message it asks Google for only the subject, sender and a short snippet, downloads the ones worth reading, reads them in memory ([how](/Waypoint/privacy/email-scanning/#how-a-booking-is-read)) and merges the bookings into your trips.

A scan works for up to 20 minutes. If a big mailbox isn’t finished, the next one starts straight away, up to 12 in a row (about four hours), and Settings says how many messages it has looked at so far. If Google asks Waypoint to slow down, it waits and tries again.

### Which messages are read

A message is read when its sender is a travel company or booking site Waypoint knows, or its subject or snippet has a travel word (flight, itinerary, boarding pass, check-in, hotel, cruise, rental car, train, 宿泊 and the like), or it has a general booking word (confirmation, booking, reservation, 予約, 確認) while the sender’s name has a travel word. A booking word alone isn’t enough. An unknown sender whose mail Gmail files under Purchases or Reservations is read only with a booking word, no travel word and nothing retail about it; if it can’t become a booking it goes to Review, so a restaurant or appointment confirmation can show up there. Dismiss it, or choose **Not travel**.

Skipped, with nothing kept but the message’s Gmail id so it isn’t looked at again:

- shopping mail (order, shipped, receipt, invoice, refund) with no travel word, and anything from a short list of online stores and parcel carriers. A known travel sender is never skipped for this;
- one-time and sign-in codes and auto-replies;
- from an unknown sender, newsletters, offers and replies (*Re:*), unless they say they change or cancel a booking;
- bank mail (Chase, Capital One, American Express) unless its subject is about travel.

A message that was read but can’t become a booking goes to Review when its sender is known, it is in a label you picked, it has booking markup or it has two or more travel words. With only one travel word from an unknown sender, it is dropped like a skipped one.

### Merging into your trips

An email is the same reservation as a booking you can see when it has the same kind and confirmation code and starts within three days of it or overlaps its dates (for a flight, also the same airports and flight number; for a train, the same stations). Spelling isn’t a difference.

- **Nothing new:** the email is added to that booking, which shows both emails, newest first. Only what the booking lacked is filled in, a traveller the email names is added, and nothing you edited or locked changes.
- **Something changed:** the segment updates and is marked *changed* or *cancelled*. A field you edited by hand is never overwritten.
- **Something contradicts** (the company, hotel or ship differs): an item in [Review](/Waypoint/start/review/#match-bookings) asks whether it is that booking or a new one.
- **A booking you added by hand without a code** is filled in by an email that gives one, when it is the only such segment you can see that fits (a stay: the same check-in and check-out days, zone and name; a flight: the same number, day and airports). When several fit, Review asks which.
- **No code, or dates more than three days off:** the email becomes a segment of its own. You can merge or delete it.

A cancelled booking, a different flight number, airport or kind, and a booking you can’t see are never taken for the same booking. The booking is yours: you see its trip, and so does anyone it names whom Waypoint can match to a person.

### Times marked UTC

Some airlines write a flight’s times as UTC (`…T09:00:00Z`) when they mean the airport’s own clock. Waypoint settles which from the times of day the email shows, in memory. If the answer is unclear, it keeps the conversion and the booking’s card says **Check the times** until you edit or confirm them. A time with a real offset (`-06:00`) is never second-guessed. When both readings of a short flight fit, or it is a stay, rental or train, the booking goes to Review rather than being filed with a time that may be hours off. A stay or rental needs a time zone, worked out from its city and country; when Waypoint can’t, it goes to Review too.

### Looking back and picking labels

**Look back through all mail** (under the mailbox) searches the whole mailbox with no date limit and reads what Waypoint hasn’t read before, newest first. It asks first, because it can take hours for a large inbox; it runs in the same 20-minute scans, and choosing it again finishes a mailbox too big for one run. Bookings it finds are added as past trips, so years of travel can add many. It only fills in what a matching booking lacks, never its times, places or status, so an old email can’t undo a change or cancellation. A booking you moved by more than three days no longer matches, so its old email is added as a booking of its own, which you can delete.

**Choose labels** picks some of your own Gmail labels to read in full: every message in a picked label is read whatever its sender or subject. None are picked by default, Gmail’s own labels aren’t offered, and a label you delete in Gmail drops out. A forwarded booking is read as the original and attributed to the traveller it names; a forward with no original in it goes to Review.

### After a scan

Each mailbox in Settings shows when its last scan finished and its counts: found, read, bookings added or changed, couldn’t be read (waiting in Review), skipped, and whether more are waiting, plus how many messages the AI was asked about, and how many it dismissed as not bookings, when it reads mail automatically. Only counts are shown, kept or logged, never a subject, sender or text; the log gives counts by reason (“12 × no structured booking data”).

- A scan that **couldn’t start** (the connection needs reconnecting, or Google couldn’t be reached) says why under the mailbox until one does. That isn’t a failed scan.
- A scan that **stops halfway** keeps what it had read, leaves the last good state as it was and says what failed. The next one carries on.

### Ignored senders

**Ignored senders**, under each connected mailbox, lists the domains that mailbox ignores, with a count. It shows domains only, never a message or address, and only to the mailbox’s owner.

**Stop ignoring** a domain asks first. Confirming removes the domain and starts a scan straight away that reads the whole mailbox again, newest first, through the usual triage, so it can take a while for a large inbox. The review items and kept messages that ignoring deleted come back from Gmail, not from a backup, so only mail still in Gmail returns. Mail whose sender couldn’t be read can’t be ignored.

### Review at a glance

**Review at a glance**, under each connected mailbox, says why its mail is waiting in [Review](/Waypoint/start/review/) and who it comes from, so you can see which sender is worth a reader of its own or is simply not travel. It shows counts, sender domains and fixed phrases, never a message, subject, address or confirmation code, and only to the mailbox’s owner.

- **Why** and **What’s missing**: items waiting by reason (no booking data found, dates or place missing, couldn’t be opened, could be one of your bookings), with how many were added in the last 30 days, and what the incomplete ones lack.
- **Senders with the most waiting**: the ten domains with the most items, each with its count and commonest reason. The domain links to Review filtered to that sender (**Show everything** clears it); **Ignore this sender** asks first and can be undone.
- **Added to Review per scan**: for each of the last ten scans in the last 30 days that added any, how many of its items are still waiting.
