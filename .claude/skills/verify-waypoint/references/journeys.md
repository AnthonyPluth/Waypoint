# Journeys

End-to-end recipes. Each assumes `tools/control doctor` passed. Run them from the repository root and look at every screenshot you take.

## 1. Reproduce a UI bug on a trip

```sh
tools/control start --viewport desktop
tools/control goto trips
tools/control snapshot --root main --text --max-lines 40          # the names to target
tools/control click 'a[href^="#trip/"]' --nth 0                    # the first trip in the list
tools/control wait-settle
tools/control snapshot --root main --text --max-lines 60           # the bookings, the people, the codes
tools/control screenshot                                           # the whole page
tools/control console --text                                       # any error is a bug
tools/control network --text                                       # any 5xx is a bug
```

Write down the steps that show the bug and the command output that proves it. Then turn it into a failing test, or into a flow in `frontend/verify/flows/`. `reset` gets you fresh data for another attempt.

## 2. Check a layout at both widths

```sh
tools/control start
tools/control goto trips
tools/control screenshot                           # phone, 440×956, the whole page
tools/control screenshot --viewport                # phone, the first screen as a person sees it
tools/control viewport desktop
tools/control screenshot                           # desktop, 1280×800
```

Open all three images. A phone layout that overflows, a clipped label or a floating bar over content shows up there. `viewport laptop`, `wide` and `zoomed` show the other sizes the flows use; for anything between, resize a real browser by hand.

## 3. Get the image make verify would write for a page

```sh
tools/control start
tools/control offline                              # a virtual passkey and Settings → Offline, as make verify does first
tools/control goto upcoming
tools/control screenshot artifacts/control/upcoming-phone.png
cmp artifacts/control/upcoming-phone.png docs/src/assets/screenshots/upcoming-phone.png && echo same
tools/control screenshot --viewport artifacts/control/upcoming-phone-hero.png
```

On the Chromium that made the committed images, `cmp` says `same`; another build can differ in anti-aliasing, and then this is a way to look, not to prove. If your change is meant to alter the page, the difference is the change. The pull request's before and after come from `make verify`, whose diff shows in Files changed; never commit anything from `artifacts/`.

## 4. Compare before and after a change to the web app

```sh
tools/control start
tools/control goto trips
tools/control screenshot artifacts/control/before-trips-phone.png
# ...edit frontend/src...
(cd frontend && npm run build)
tools/control reset                                # a new server serves the new build, on fresh data
tools/control screenshot artifacts/control/after-trips-phone.png
cmp artifacts/control/before-trips-phone.png artifacts/control/after-trips-phone.png || echo changed
```

Look at both images. They are for you.

## 5. Run one of make verify's flows step by step

```sh
tools/control flows --text                         # names, start pages, widths
tools/control flow open-trip --text                # each step ok or FAIL, with the time it took
tools/control flow offline-trip --viewport desktop
```

A failed step stops the flow, saves `artifacts/control/flows/flow-<name>-FAILED-<width>.png`, and exits 1; the answer still has every step's result. Afterwards the session is the flow's browser as it ended, so `snapshot` and `screenshot` show where it stopped. Run `reset` before a second run: a flow that changes data (`add-trip`, the review flows) doesn't pass twice on one copy of it.
