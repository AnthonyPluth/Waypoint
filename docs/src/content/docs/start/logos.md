---
title: Brand logos
description: Bundled logos for airlines, hotels, rental companies and cruise lines, with no account, API key or network connection.
sidebar:
  order: 12
---

Waypoint includes logos for major airlines, hotel groups and brands, car rental companies and cruise lines. They appear automatically on bookings and loyalty memberships, with no Settings section to configure. No account, key or connection is needed, and neither the server nor your browser contacts a logo service.

A flight with no airline named uses its flight number’s airline code. Hotel names such as “Hyatt Place Chicago” or “Courtyard Denver” match their brand. When a hotel brand has no bundled logo, Waypoint uses its group’s logo and labels it with the brand’s name. Unlisted brands keep their name or initial.

Booking logos are served through the booking’s visibility-checked route. A person who cannot see a booking cannot fetch its logo. Loyalty logos follow the same household access as the membership itself.

The catalog lives in `waypoint/storage/logos/manifest.json`, with each asset’s source and upstream content hash. Logos ship in the application and Docker image, so a fresh installation and a restored backup get them automatically. Adding a logo requires a catalog entry and a bundled image; it never adds a runtime download.

Upgrading removes saved credentials and error settings for the retired Logo.dev service. Restoring a backup from an older release also removes them. Existing backup files are unchanged.
