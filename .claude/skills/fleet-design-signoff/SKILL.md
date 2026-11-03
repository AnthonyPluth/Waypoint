---
# vendored from fleet v1.1.0 (plugins/fleet/skills/design-signoff/SKILL.md) by `fleet sync`; edit it in fleet, not here: `fleet drift` fails on any change
name: fleet-design-signoff
description: Use before changing anything a person sees in the frontend - layout, a flow, visual style, theme tokens or copy a design fixed. No frontend design change ships without the owner's sign-off; this says what counts, how to show the change (make verify images at phone and desktop width, beside the signed-off designs) and what to do when the work would depart from the design.
---

# Design sign-off

No frontend design change ships without the owner's sign-off. An agent may build what a signed-off design shows; it may not decide what the design should be.

## What counts as a design change

- **Layout**: where things sit on a page, at any width; what shows at phone width and what at desktop width.
- **Flow**: the steps to do something, what a button leads to, what a page asks for and in what order.
- **Visual style**: colour, type, spacing, borders, shadows, icons, motion.
- **Theme tokens**: any value in the app's theme (its colour, spacing and type tokens, wherever the app keeps them).
- **Copy the design fixed**: headings, labels, buttons and messages the signed-off design shows word for word.

A bug fix that brings a page back to its signed-off design isn't a design change. A new page or state the design doesn't show is one.

## Show it

- Run the app's `make verify` and put its images in the pull request, at phone and at desktop width, for every page or flow the change touches; never screenshots from a session of your own.
- Where the app has signed-off designs under `docs/design/`, put each image beside the design it should match, and say where they differ.
- Say in the description which issue signed the design off.

## When the work would depart from the design

Stop. Don't ship the deviation, and don't pick an alternative yourself:

1. Raise it in the pull request: what the design shows, what you would change and why (it doesn't fit at phone width, a state it doesn't cover, a conflict with another page).
2. Raise it on the issue where the design is being signed off, with the same images.
3. Keep the rest of the change to the design, or leave the pull request as a draft until the owner answers.

## Tokens

Never adjust a theme token on your own, not even to fix contrast or spacing on one page: a token changes every page that uses it. Raise it as above. Where one element looks wrong, the fix is in that element, using the tokens as they are.
