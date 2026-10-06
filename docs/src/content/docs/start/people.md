---
title: People and guests
description: Who travels with your household, how members and guests differ, and the names Waypoint matches bookings against.
sidebar:
  order: 3
---

The **People** page lists everyone who travels with your household. Every signed-in member sees all of it, so anyone can add or fix a name.

## Members and guests

- **Members** are the people who sign in. Waypoint adds someone to People the first time they sign in, using the name their sign-in provider gives. Later sign-ins don’t change it, so a name you’ve corrected stays corrected. You can edit a member’s names, but not remove them, and their link to their login can’t be changed from the page: they’re in the household because they sign in.
- **Guests** have no login: children, grandparents, a friend who comes along. Any member can add a guest, rename them or remove them. Removing a guest asks first.

## If you were already a guest

Waypoint can add someone as a guest before they ever sign in: a booking’s passenger matches nobody, so it’s added as a guest, and a booking then points to that guest. When that person signs in for the first time they become a member of their own, and without a link between the two they would see none of those trips.

- **After you sign in**, if you have no trips and a guest’s name matches yours (their name, legal name or an alias), Upcoming asks “Are you one of these?”. **This is me** links you to that guest; **None of these** hides the question for you.
- **On the People page**, a guest has a **This is me** button too. You can only link a guest to yourself, never to someone else, and a member can’t be linked this way. Once you have linked a guest, the button is hidden on every guest for you.

Linking moves everything on the guest to you in one step: their trips and bookings (including the ones they booked), their loyalty and Known Traveler numbers, and their legal name and aliases, which are added to yours without repeats. You keep your own name and first name (a missing one is filled in from the guest), and the guest is removed. If you both had a number for the same program and they differ, both are kept and People says “Two numbers for …” so you can remove the one that’s wrong. People then shows “Linked from guest … by … on …”.

Linking can’t be undone in Waypoint; restoring a [backup](/waypoint/start/docker/#moving-your-data-from-another-machine) is the way back. Merging two members, or two guests, isn’t supported.

## Names

Each person has:

- a **name** (how Waypoint shows them) and a **first name**;
- a **legal name**, as it appears on their ID;
- **name aliases**, the ways an airline prints their name on a booking, such as `DOE/JANE MS`. Add one per line; Waypoint will match bookings against them. When a name matches both a member and a guest, the booking goes to the member; when it matches two members, or two guests, Waypoint doesn’t guess and asks in Review.

## In a backup

People are part of a [backup](/waypoint/start/docker/#moving-your-data-from-another-machine) and come back exactly as they were, with each member still linked to their sign-in.
