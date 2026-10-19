---
title: Brand logos
description: Bundled logos for airlines, hotels, rental companies and cruise lines, with no account, API key or network connection.
sidebar:
  order: 12
---

Waypoint includes logos for major airlines, hotel groups and brands, car rental companies and cruise lines. They appear automatically on bookings and loyalty memberships, with nothing to configure. Neither the server nor your browser contacts a logo service.

- A flight with no airline named uses its flight number’s airline code.
- Hotel names such as “Hyatt Place Chicago” or “Courtyard Denver” match their brand. When a brand has no bundled logo, Waypoint uses its group’s logo and labels it with the brand’s name.
- Unlisted brands keep their name or initial.

A person who cannot see a booking cannot fetch its logo. Loyalty logos follow the same household access as the membership itself.

Logos ship in the application and Docker image, so a fresh installation and a restored backup have them.
