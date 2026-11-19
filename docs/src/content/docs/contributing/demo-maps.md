---
title: Maps in the demo
description: Why the public static demo shows no Apple maps, what that means for the docs screenshots, and what a future change would take.
sidebar:
  order: 3
---

**Decided: option C (owner, 2026-11-18).** The public static demo shows no maps. No Apple token or key is made or stored for it. The decision is recorded in [this comment on #834](https://github.com/AnthonyPluth/Waypoint/issues/834#issuecomment-6982585262). The options that were weighed are in [`docs/design/demo-maps/README.md`](https://github.com/AnthonyPluth/Waypoint/blob/main/docs/design/demo-maps/README.md).

There is nothing to set up. Don’t create an Apple Maps token, a Maps ID or a key for the demo, and don’t create a GitHub environment, secret or variable for one. No key, token or other private value goes into the repository, a pull request, an issue, an image or a log.

## What the demo and the docs show

The [MapKit-only design](https://github.com/AnthonyPluth/Waypoint/blob/main/docs/design/mapkit-only/README.md) (signed off on #833) removes the bundled renderer, so every map in Waypoint except the Year in Review card’s picture is Apple’s. Without a key, the Apple maps are hidden. Its renderer step, [#836](https://github.com/AnthonyPluth/Waypoint/issues/836), builds this behaviour into the demo and `make verify`:

- **The static demo** ([anthonypluth.github.io/Waypoint/demo/](https://anthonypluth.github.io/Waypoint/demo/)) has no map and no route replay:
  - Past trip cards without photos show their kinds tile.
  - Stats has no map.
  - A completed trip has no Replay trip.
  - The page makes no request to Apple or anyone else, and `demo/verify.mjs` checks that.
- **The docs screenshots** (`docs/src/assets/screenshots/`, made by `make verify`) keep showing the grid stand-in. That stand-in is `frontend/verify/fake-mapkit.js`, run with a throwaway key made for each run. The images stay the same from run to run, need no network and never show a real tile or carry a token. `tools/control` uses the same stand-in.

## Why no maps

A static page can’t hide anything it uses. MapKit JS needs a token to start, so a demo with maps would hand every visitor a token they could copy. That holds even with Apple’s safest kind, a static token restricted to one domain with an end date. Apple counts its free daily allowance per Apple Developer Program membership, not per token. So a copied demo token could spend the allowance the household’s own Waypoint and its nightly route warming use. The owner didn’t accept that risk.

## Privacy

The demo holds only made-up data: invented people, bookings, emails and places (`frontend/demo/data.json`, see [demo/README.md](https://github.com/AnthonyPluth/Waypoint/blob/main/demo/README.md)). With no maps, Apple sees nothing from the demo: no script, tile or directions request is made, and no token is in the page.

## If this is revisited

The design page keeps Apple’s documented facts, the options that were **not adopted**, their abuse model and what each would take. Read it before reopening the question. Any change needs a new owner decision on a new issue.
