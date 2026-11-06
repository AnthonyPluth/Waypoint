---
title: Photos
description: How a trip's photos are read from each member's Immich library, which ones a trip shows, what waits under Needs a look, and who sees whose photos: each person shares their own, per trip, with everyone on it or with themselves alone.
sidebar:
  order: 6
---

Waypoint reads each family member’s Immich library and matches photos to trips by when they were taken and then by where: a photo taken during a trip’s dates near one of its bookings belongs to that trip. The pictures stay in Immich; Waypoint keeps only when and where each photo was taken and which trip it matched. The design is in [docs/PHOTOS.md](https://github.com/AnthonyPluth/Waypoint/blob/main/docs/PHOTOS.md).

## Sharing your photos on a trip

Nothing from your library is on a trip until you share it there. On each trip you choose who sees the photos you share: **Only me** (the default) or **Everyone on this trip** (the people on the trip; someone who merely booked it or received a confirmation for it is not one of them). You can change that choice at any time, take single photos off a trip (**Remove from this trip**) and put them back, or stop sharing on a trip altogether; each change takes effect at once, for everyone and everywhere a photo appears (the gallery, the map, the replay, the trip’s counts and summary). Photos you remove stay removed through every later sync, even after you stop and share again or connect the library anew, and are listed for you alone under **Removed from this trip** with **Put back**. Stopping sharing takes every photo of yours off the trip for everyone and keeps your removals for when you share again. Nothing changes in Immich.

**Share on all my trips** is a standing setting in Settings: while it is on, every trip you are on, including ones you join later, is shared with your default choice without asking. Turning it on shares every trip you are on now, including ones you had declined or stopped; a trip you stop while it is on stays stopped. Turning it off changes no trip.

Only you can share, remove or stop sharing your own photos. A person without a sign-in of their own (a child) is shared for by the member who connected their library, on the trips that member can see. Nobody else, the trip’s organiser included, can remove or hide someone else’s photo, and nothing on a trip tells anyone that photos they can’t see exist: counts, pins, the map’s extent and the summary only ever count the photos the viewer may see.

## On a trip

A trip page shows the photos shared on it that you may see, in the order they were taken, each with the wall-clock time where it was taken (the time zone comes with the photo when Immich knows it, otherwise from the booking the photo is nearest to) and the booking it is nearest to. A photo with no location of its own is placed from the itinerary (the stay or rental under way when it was taken) and marked as such. A photo taken far from every booking of its trip is still shown, with a flag, until its person accepts, moves or removes it.

For the map, the photos are grouped into clusters: photos taken within a few kilometres of each other form one pin, with its count, its first and last time, and a cover photo. A pin whose every photo was placed from the itinerary is drawn hollow. A very long trip keeps at most 400 pins by merging the smallest into their nearest neighbours.

## Needs a look

A photo Waypoint could not settle waits under **Needs a look** for the person whose library it came from: one taken during two overlapping trips they shared that distance could not tell apart, or one taken far from every booking of the trip it matched. Each is listed with the trips it could belong to, which are only trips its person shared and did not remove it from. The person picks the trip, accepts the match as it is, removes it from its trip, or leaves an unsettled photo off every trip it could belong to; a photo they have placed by hand keeps that trip through every later sync. A photo can only be moved to a trip its person is on and has shared their photos on.

## Who sees what

A trip you cannot see answers as if it did not exist, and so does a photo you may not see. Seeing a trip is not enough to see a photo on it: the photo’s person must have shared their photos on that trip with everyone and you must be one of the trip’s people, or you must be that person (or share for them), and the photo must not have been removed from the trip. The same photo reached through two of a person’s libraries is one photo. Two people on the same trip can therefore see different photos, different counts and different places, and neither is told of the difference. Photos are off without sign-in (local mode), and assistants connected over MCP never reach photos, grants or removals.
