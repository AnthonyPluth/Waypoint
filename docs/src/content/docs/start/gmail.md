---
title: Google OAuth client for Gmail
description: Create the Google Cloud OAuth client Waypoint uses to connect each member’s Gmail, read-only.
sidebar:
  order: 3
---

Waypoint reads bookings from Gmail with a Google OAuth client that **you** create in your own Google Cloud project, so no one else’s app sits between your mailbox and your server. This page sets that up once for the household; after that, each member connects their own Gmail from **Settings → Gmail**.

Once a Gmail is connected, Waypoint scans it for booking emails: see [Scanning](#scanning) below, and [Email scanning](/waypoint/privacy/email-scanning/) for what it will and won’t do with a mailbox.

## Create the client

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project (any name, such as “Waypoint”).
2. **APIs & Services → Library**: enable the **Gmail API**.
3. **APIs & Services → OAuth consent screen**: choose **External**, give it a name and your email, and add only one scope: `https://www.googleapis.com/auth/gmail.readonly`. Waypoint asks for nothing else, so it can’t send, delete, label or change anything.
4. Still on the consent screen, set the publishing status to **In production** (**Publish app**). Leave it unverified: Google doesn’t need to review an app that only your household uses, and each member clicks through its “Google hasn’t verified this app” warning once when connecting.

   :::caution[Don’t leave it in “Testing”]
   While an app is in **Testing**, Google expires its refresh tokens after 7 days, so every Gmail would turn to “Reconnect” weekly. Publish it **In production**.
   :::
5. **APIs & Services → Credentials → Create credentials → OAuth client ID**: choose **Web application**, and add this **authorized redirect URI**, using the address you open Waypoint at (`WAYPOINT_PUBLIC_URL`):

   ```
   https://waypoint.example.com/api/mailboxes/callback
   ```

   Without sign-in, on your own machine, it is the address you open Waypoint at instead, such as `http://localhost:8765/api/mailboxes/callback`.
6. Copy the client ID and secret into `.env` and restart Waypoint:

   ```
   GOOGLE_CLIENT_ID=1234567890-example.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=GOCSPX-example
   ```

Until both are set, Settings says Gmail isn’t set up and shows no Connect button.

## Connect a Gmail

Each member opens **Settings → Gmail** and chooses **Connect Gmail**, picks the Google account and agrees to read-only access. A member can connect more than one address (a personal and a work one, say), and sees only their own connections: nobody else’s address or status appears for them.

- **Reconnect.** If Google stops honouring a connection (you removed Waypoint at [myaccount.google.com/permissions](https://myaccount.google.com/permissions), the grant expired, or Waypoint’s secret key changed), its row says **Reconnect**. Choosing it connects the same address again.
- **Disconnect.** Waypoint tells Google to revoke its access, then deletes the connection. If Google can’t be reached it keeps the connection and says so, rather than showing it gone while it still works; try again, or remove Waypoint at the Google permissions page.
- **When someone loses access.** A connection ends when the person who made it can no longer sign in to Waypoint (taken off `OIDC_ALLOWED_EMAILS`, or past their sign-in with `OIDC_ALLOWED_GROUPS`): Waypoint checks before every use and once an hour (and whenever anyone opens Settings), revokes the token at Google and deletes it.

## Scanning

Waypoint scans each connected mailbox in the background, every few hours (by the server’s own clock, `TZ`), and when you choose **Scan now** under the mailbox in Settings. A scan:

1. **Searches on Google’s side** for mail from a list of airlines, hotel groups, rental companies, railways and booking sites that also says *confirmation*, *itinerary*, *reservation*, *e-ticket* or *booking*, leaving out Gmail’s Promotions. Mail that doesn’t match is never downloaded. The first scan looks back 18 months; later ones ask Gmail’s history what arrived since the last one ended.
2. **Reads each match in memory** for the booking markup airlines and hotels add to their emails (schema.org `FlightReservation`, `LodgingReservation`, `RentalCarReservation` and `TrainReservation`, as JSON-LD or microdata), or, for a sender with a parser of its own (Southwest Airlines so far), for the booking in its text, and throws the message away. Only the booking’s fields are kept.
3. **Merges it into your trips.** A booking is one segment. A later email updates a segment you can see when it has the same confirmation code, kind, provider and places (and flight number, when both give one) and its start is within three days of the segment’s own, marking it *changed* or *cancelled* rather than adding another; a field you edited by hand is never overwritten. An email with no confirmation code, or about a date more than three days from the segment’s, becomes a segment of its own (a cancellation without a code, say), so one booking is never rewritten into another. You can merge or delete the extra one. The booking is yours: you booked it, so you see its trip, and so does anyone it names whom Waypoint can match to a person.
4. **Sends what it can’t read to [Review](/waypoint/start/review/).**

Each mailbox in Settings shows when its last scan finished. If a scan couldn’t start (the connection needs reconnecting, Google couldn’t be reached for the sign-in, or the mailbox’s owner hasn’t signed in yet), Settings says why under the mailbox (“The scan couldn’t start: …”) until one does; that isn’t counted as a failed scan. A scan that stops halfway (Google couldn’t be reached) keeps what it had read, leaves the last good state as it was, and says what failed there; the next one carries on. Waypoint remembers each message it has read by Gmail’s id, with nothing of its content, so no message is read twice. A booking’s times are the clocks at its places. When the markup gives a time with the place’s own offset, or none, that is the time. When the offset isn’t the place’s (senders often print the local time with a UTC mark), Waypoint decides only where it can: a flight is read the one way that gives a believable flight time for the distance between its airports. If both readings fit (a short flight), or it is a stay, a rental or a train, the booking goes to [Review](/waypoint/start/review/) rather than being filed with a time that may be hours off. A stay or a rental needs a time zone: Waypoint works it out from the city and country in the booking, and when it can’t, the booking goes to Review rather than being given a guess.

### Times marked UTC

Some airlines write a flight’s times as UTC (`…T09:00:00Z`) when they mean the airport’s own clock. Waypoint settles which from the message itself, in memory: it looks for both readings of the times (as written, and moved to the airport’s zone) among the times of day the email shows (`9:00 AM`, `9:00am`, `09:00`, `9:00`). If only the as-written times appear, they are the local times; if only the moved ones appear, the markup really was UTC; the same reading applies to the departure and the arrival together. If both or neither appear, Waypoint keeps the move and the booking’s card says **Check the times** until you edit or confirm them (saving the times, even unchanged, confirms them). A time with a real offset (`-06:00`) is never second-guessed. Only the times of day are kept from the text, and only while the message is read.

### Read bookings again

**Read bookings again**, under each connected mailbox in Settings, reads once more the messages Waypoint already found that made bookings (it doesn’t search again, and it doesn’t move the last scan’s end), so bookings stored from an earlier reading, with wrong times say, are corrected. It updates the fields you haven’t edited, never adds a second copy of a booking, and doesn’t mark a corrected time as a schedule change.

What Waypoint can’t do yet: read mail with no booking markup from a sender that has no parser yet (they come one vendor at a time; the rest goes to Review), and any sender outside its list.

## What Waypoint keeps

Per connection: the Gmail address, a **refresh token** and where its scans had got to (the point in Gmail’s history, and when the last scan finished or what stopped it), plus the ids of the messages already read and the [Review](/waypoint/start/review/) items. The refresh token is encrypted with `WAYPOINT_SECRET_KEY` (in backups too), is decrypted only to refresh or revoke it, and never appears in logs or error pages. Access tokens are used for the one call that needs them and aren’t kept. A backup holds the connections, so restoring one needs the same key; otherwise the connections turn to **Reconnect**.
