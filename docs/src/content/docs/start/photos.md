---
title: Photos
description: How a trip's photos are read from each member's Immich library, which ones a trip shows, what waits under Needs a look, and who sees whose photos.
sidebar:
  order: 6
---

Waypoint reads each family member’s Immich library and matches photos to trips by when they were taken and then by where: a photo taken during a trip’s dates near one of its bookings belongs to that trip. The pictures stay in Immich; Waypoint keeps only when and where each photo was taken and which trip it matched. The design is in [docs/PHOTOS.md](https://github.com/AnthonyPluth/Waypoint/blob/main/docs/PHOTOS.md).

## On a trip

A trip page shows the photos matched to it from every connected library, in the order they were taken, each with the wall-clock time where it was taken (the time zone comes with the photo when Immich knows it, otherwise from the booking the photo is nearest to) and the booking it is nearest to. A photo with no location of its own is placed from the itinerary (the stay or rental under way when it was taken) and marked as such. A photo taken far from every booking of its trip is still shown, with a flag, until its person accepts or moves it.

For the map, the photos are grouped into clusters: photos taken within a few kilometres of each other form one pin, with its count, its first and last time, and a cover photo. A pin whose every photo was placed from the itinerary is drawn hollow. A very long trip keeps at most 400 pins by merging the smallest into their nearest neighbours.

## Needs a look

A photo Waypoint could not settle waits under **Needs a look** for the person whose library it came from: one taken during two overlapping trips that distance could not tell apart, or one taken far from every booking of the trip it matched. Each is listed with the trips it could belong to. The person picks the trip, or accepts the match as it is; a photo they have placed by hand keeps that trip through every later sync.

## Who sees what

Everyone who can see a trip sees all of its photos, from every library, the same as its bookings and costs. A trip you cannot see answers as if it did not exist. Only the person whose library a photo came from can hide it from a trip or move it to another; a hidden photo stays visible to them, marked hidden, and to nobody else. A photo can only be moved to a trip its person is on. Assistants connected over MCP never reach photos.
