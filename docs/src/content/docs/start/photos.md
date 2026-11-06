---
title: Photos
description: How a trip's photos are read from each member's Immich library, which ones a trip shows, what waits under Needs a look, and who sees whose photos.
sidebar:
  order: 6
---

Waypoint reads each family member’s Immich library and matches photos to trips by when they were taken and then by where: a photo taken during a trip’s dates near one of its bookings belongs to that trip. The pictures stay in Immich; Waypoint keeps only when and where each photo was taken and which trip it matched. The design is in [docs/PHOTOS.md](https://github.com/AnthonyPluth/Waypoint/blob/main/docs/PHOTOS.md).

Photos need sign-in: without it (local mode) there are no libraries, and the photo settings answer as if they did not exist.

## Connecting a library

Each member connects their own Immich library under **Settings → Photos**, with the address of the Immich server and an API key made for Waypoint.

1. In Immich, open **Account Settings → API Keys** and create a key for Waypoint. Give it these permissions, and no more: `asset.read`, `asset.view`, `user.read`, `map.read` and `asset.download` (originals are shown through Waypoint, never straight from Immich). An older Immich without per-key permissions needs `all`.
2. In Waypoint, enter the Immich address (scheme, host and port, such as `https://immich.example.com` or `http://immich.local:2283`; a plain `http://` address is accepted only on your own network) and the key, and choose **Test**. Waypoint asks Immich who the key belongs to and shows the name, saving nothing.
3. Choose **Save**. Waypoint checks the address and key once more as typed, and keeps the key encrypted with `WAYPOINT_SECRET_KEY`, like a Gmail connection’s token. The key never appears in a reply, a log or an error; a backup carries it encrypted.

Each library card shows its person, its host and its status: **ok**, **refused** (Immich didn’t accept the key, or it lacks a permission), **unreachable**, or **off** (paused). The library’s own person and whoever connected it also see its last sync, its last error and how many photos it has on how many trips; everyone else sees only the person, the host and the status, so a library’s size says nothing about trips they can’t see.

- **Test** asks Immich again with the saved key and records the outcome, so a library marked refused clears once the key works.
- **Change key** replaces the key only when the new one belongs to the same Immich account as the old one. A key for a different account is refused: remove the library and connect it again, so one person’s photos can never be re-attributed by swapping keys.
- **Pause** stops reading the library until it is resumed; **Remove** deletes the library and the photo references Waypoint kept from it. Nothing changes in Immich.
- **Sync now** starts a read of the library.

### Who connects whose library

A member who signs in connects only their own libraries, so nobody else can attach a library to them. A person in People who has no sign-in of their own (a child) has one steward: the member who connected their first library connects all of them, and another member trying to is refused. When that person later signs in and links the guest entry to themselves, their libraries become their own and the former steward keeps nothing.

### When someone loses access

A library ends with its owner’s access: when the member who connected it can no longer sign in to Waypoint (taken off `OIDC_ALLOWED_EMAILS`, or past their sign-in with `OIDC_ALLOWED_GROUPS`), Waypoint’s hourly sweep deletes the library and the photo references it kept, as it does their Gmail connection.

## What Waypoint reads and keeps

Waypoint reads photos taken during the trips its person is on, and the 12 hours around them, and keeps for each only its Immich id, when and where it was taken and which trip and booking it matched, including photos that turn out not to belong to a trip; never the pictures, file names or camera data. Thumbnails and originals are fetched from Immich when shown and are never written to disk or the database. The Immich address and key never reach the browser, and nothing about a library is reachable from an AI assistant over MCP.

## On a trip

A trip page shows the photos matched to it from every connected library, in the order they were taken, each with the wall-clock time where it was taken (the time zone comes with the photo when Immich knows it, otherwise from the booking the photo is nearest to) and the booking it is nearest to. A photo with no location of its own is placed from the itinerary (the stay or rental under way when it was taken) and marked as such. A photo taken far from every booking of its trip is still shown, with a flag, until its person accepts or moves it.

For the map, the photos are grouped into clusters: photos taken within a few kilometres of each other form one pin, with its count, its first and last time, and a cover photo. A pin whose every photo was placed from the itinerary is drawn hollow. A very long trip keeps at most 400 pins by merging the smallest into their nearest neighbours.

## Needs a look

A photo Waypoint could not settle waits under **Needs a look** for the person whose library it came from: one taken during two overlapping trips that distance could not tell apart, or one taken far from every booking of the trip it matched. Each is listed with the trips it could belong to. The person picks the trip, or accepts the match as it is; a photo they have placed by hand keeps that trip through every later sync.

## Who sees what

Everyone who can see a trip sees all of its photos, from every library, the same as its bookings and costs. A trip you cannot see answers as if it did not exist. Only the person whose library a photo came from can hide it from a trip or move it to another; a hidden photo stays visible to them, marked hidden, and to nobody else. A photo can only be moved to a trip its person is on. Assistants connected over MCP never reach photos.
