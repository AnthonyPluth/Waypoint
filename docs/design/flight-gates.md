# Research: where flight gate numbers can come from when the booking email has none (#635)

Status: research only; nothing is built and no follow-up issue is filed (section 8 proposes them). Facts about the current code come from reading it on `main`. Facts about other services come from their public pages (pricing, documentation, terms), fetched in this session; nothing was signed up for, paid for or called, and no household data was sent anywhere. A claim from memory rather than a page is marked **confirm**.

What was and wasn't checked against real flights is in section 9. Short version: nothing was checked against a real flight's gate. The read-only status tool answered for the household's two same-day upcoming flights with no status held, which is what the tool does when Waypoint has not asked the service (it never looks anything up), so the question "how many hours before departure does a gate appear" is **not verified against real flights**.

## 1. What the current source returns

The source is AeroDataBox through RapidAPI (`waypoint/providers/flightstatus.py`, host `aerodatabox.p.rapidapi.com`, one request, `GET /flights/number/{number}/{date}`). Off until `RAPIDAPI_KEY` is set.

What the code does with a gate:

- `_side` reads `departure.terminal`, `departure.gate`, `arrival.terminal` and `arrival.gate` from the reply, each trimmed to 10 characters (`dep_gate`, `arr_gate`, `dep_terminal`, `arr_terminal` on `Status`). A missing or non-text value is `None`. Waypoint does not invent, infer or carry over a gate: whatever the service says at that call is what is shown, and an absent field is an empty gate.
- The same four values pass through `domain/flightstatus.py` (`_out`, `StatusOut`), the API contract and `frontend/src/lib/api-types.ts` unchanged. There is nothing to add to the schema to show a gate from this source.

When a call is made (`domain/flightstatus.py`):

- `run_due` runs from a background job (`check_flights` in `server/jobs.py`) over flights starting between two days ago and three days ahead (`watching`). A flight is checked at its booked departure minus 24 hours, 3 hours, 1 hour and 20 minutes, and once at the booked arrival (`CHECKS`, `checkpoints`). After downtime only the latest missed checkpoint is made up. A failed call still uses its checkpoint.
- Refresh on a flight's card fetches now unless an answer under 15 minutes old is held (`REFRESH_AFTER`).
- A monthly counter caps calls (default 400, `WAYPOINT_FLIGHT_STATUS_MONTHLY_LIMIT`). At 90% only the one-hour check is kept; at 100% nothing is fetched until the 1st; a 429 or a refused key pauses fetching for an hour.

What is kept (`_store`):

- A final status (landed, cancelled, diverted) is written to `flight_status` with its gates and kept for good. That is the only time a gate is stored, and by then it no longer helps anyone.
- Anything else (scheduled, delayed, departed) is held in memory for 15 minutes (`hold`, `REFRESH_AFTER`) and then dropped; the docs say so on purpose ("Anything that can still change is never stored"). **Consequence for gates: a gate found by the 3-hour check is on the card for 15 minutes and then gone until the 1-hour check, because nothing keeps it.** Likewise a restart clears it. This is the most important finding in this note, because it is true whatever the source returns.
- Only checkpoints and Refresh ever fetch, so with the current cadence the card can show a gate at four moments before departure at most (the 24-hour check, 3 hours, 1 hour, 20 minutes), plus whenever someone presses Refresh.

Where the user sees it:

- `FlightStatus.svelte` (trip page and Upcoming): `Terminal X · Gate Y` for departure and `Arrival terminal … gate …` when the status has them; nothing at all when it has none, no "not yet" text. The whole block is hidden when the feature is off, or when the flight is over and has no stored status.
- `PassCard.svelte`: a "Gate" row that is always present for a flight and takes only `status.dep_gate` (empty until then). Its "Terminal" row takes the booking's own `details.terminal`, not the status's `dep_terminal`.
- Gates are not in the reminders (`domain/reminders.py` has check-in and day-of messages only) and not in `/mcp` flight status beyond what `StatusOut` carries.

What the service itself returns, from AeroDataBox's own data coverage page (fetched in this session):

- Gate and terminal come from "live feeds" and only "sometimes"; schedules sometimes carry a terminal; ADS-B never carries either.
- "Gate data is not guaranteed for any flight. It appears only when the live layer supplies it." Coverage is set by airport and region, not airline, so a flight can have a gate at one end and not the other.
- For the US it states 100% of scheduled commercial flights for schedules and 86% for live status and times; it gives no US figure for gates. Its figures are approximate and updated manually at irregular intervals, and it says it "cannot create data its sources do not provide".

So for the airlines in the household's trips (Delta and others): **what the service returns for each, and how early, is not known from anything in this session.** AeroDataBox's own page says coverage follows airports, not airlines, so the answer is a table of airports the household flies through, which only a real run can fill (section 9).

My expectation, unverified and only from general experience: US carriers at their hubs often post a departure gate many hours ahead, other airports commonly post it within the last one to three hours, and any gate can change late. If that holds, the current 24h, 3h, 1h and 20m schedule is roughly right in spirit but too sparse and too forgetful (the 15-minute hold) to show a gate reliably.

## 2. Other sources that publish gates

For each: what it is, cost and limits, whether household-scale use is allowed by its terms, whether it needs an account or key, and whether it does gates.

| Source | Gates | Cost and limits | Terms for a household's own use | Account or key |
| --- | --- | --- | --- | --- |
| AeroDataBox (current), through RapidAPI, API.Market or direct | Yes when its live feed has them (above) | Basic plan: free, 400 units a month, 1 request a second, attribution required, no commercial use. Pro: $7.50 (API.Market) or $8 (RapidAPI) for 5,000 units. Direct Starter is $19 for 40,000. A flight-status call costs 1 or 2 units depending on its tier (**confirm**), and for a mainland US flight with a flight plan found it is charged twice unless the plan includes flight plans free (Ultra, Mega and some direct plans). Standard caching 7 days. | Basic is for non-commercial use, which a household is; the issue's own budget (about 80 flights a month at 5 calls) was written for 400 calls and would halve to about 40 flights if every call is 2 units | Already in use |
| FlightAware AeroAPI | **Confirm.** Its forum says gate and terminal fields exist (`gate_origin`, `gate_destination`, `terminal_origin`, `terminal_destination`) but are sometimes missing even when its website shows them; the pricing page does not mention them | Personal tier: no monthly minimum, 10 result sets a minute, about $0.005 per flight lookup, a free allowance of up to $5 a month; Standard has a $100 a month minimum | Personal tier is licensed "for personal or academic purposes only", which fits a household; the website itself may be used only with "a human-operated interactive web browser", so scraping flightaware.com is out and only the API is allowed | Account and key, and probably a card on file (**confirm**) |
| Aviationstack (apilayer) | **Confirm** (its page says only that historical data includes terminals and gates; real-time fields were not shown in what was fetched) | Free: 100 requests a month; Basic $49.99 for 10,000 | Free is "non-commercial" | Account and key |
| Other aggregators found only in search results (FlightLabs, Aviation Edge, AirLabs, Cirium, OAG, VariFlight) | Their own pages claim gate and terminal fields; not verified here | Mostly paid, several priced for businesses | Not read | Account and key |
| An airline's own API (Delta's developer portal, American's) | Probably, for their own flights | Registration; Delta's detailed access is for approved partners; American's developer host refused an anonymous fetch (403); Delta's host was not reachable from this session's network | A partner agreement, not a household use | Account, approval, per airline |
| Airline and airport public flight-information pages | Yes, on the page | None, but there is no API: it would be scraping a page per airline or airport, whose markup changes | Terms were not assessed for any (the one airport page tried returned 404). Scraping is the case the terms usually forbid, so **not recommended** without reading each one | None, but a new fetcher per site |
| FAA SWIM | Gate names are in specific services (TBFM, tower departure events), not the TFMS flight data feed (**confirm**) | Free to approved users | Needs an FAA Data Access account and signed access agreements per data set; streaming messaging, not a request and answer | Account and agreements |
| Typing the gate in by hand | Whatever the person reads off the airline's app or the board | Free | None | None |

What this means for the household's scale: a household makes a few flights a month, so any of the paid APIs is a few dollars at most, and the free AeroDataBox plan is already enough for the calls as long as the budget is spent where the gate is (section 3). The limit that bites is not the quota but whether the source has the gate at all, and no source in the table was shown to have it for the household's airports.

No source here publishes gates that no other source also gets from the airline or airport; the aggregators resell the same live feeds. So adding a second aggregator mostly buys a second chance at the same airport coverage, not new information. That is the only reason to add one (section 6).

## 3. How a gate would reach the user

Three changes, from cheapest and most useful. None is built.

1. **Keep a gate once it is known.** The card should show the last gate Waypoint was told, with its "as of" time, until the next answer replaces it, not for 15 minutes. That needs a small stored row per flight number and date (departure terminal and gate, arrival terminal and gate, when fetched), the shape of the existing `flight_status` row for finals: a flight number, a date and a gate hold no personal data and are not tied to a booking. It changes the docs' sentence that anything that can still change is never stored, so it is decision 1 below. Without it nothing else in this section is worth building.

2. **Refresh nearer departure and when the gate is empty.** Keep the current checkpoints and add T-6h, T-2h and T-30m, and make the added ones conditional: skip them once the gate is known and fresh, so a flight whose gate is posted early costs the same as today. Rough budget: 8 checkpoints is about 50 flights a month at 1 unit a call and about 25 at 2 units, against about 80 and 40 today (400 units). The existing reduced-budget rule (above 90% only the one-hour check) already keeps the budget safe, and the added checkpoints should be dropped first. If the owner wants more headroom the cheapest lever is the Pro plan at about $8 a month for 5,000 units, not a second service. Whether a call is 1 or 2 units for the household's US flights is something to read off the RapidAPI dashboard before choosing (decision 3).

3. **Push when a gate appears or changes.** The push providers exist (`providers/webpush.py`, `providers/apns.py`) and `domain/reminders.py` already sends a flight message through `_deliver` and records it in `reminder_sent` by owner, kind and a `ref`. A gate notice would be a new kind whose `ref` includes the segment and the gate, such as the segment id and the gate text, so each distinct gate sends once and a later change sends again, with the segment's tag so the new one replaces the old on the device. It needs a third preference next to check-in and day-of (off by default, as those are, **confirm**), and a read of the stored gate from change 1 so a change is noticed between runs. Text: the flight and the gate, nothing more; check-in notices already carry the flight number, so no new class of data goes to Apple's or the browser's push service. A gate that goes back to an earlier value would not notify again; that is acceptable.

What the page shows before a gate is known: today, nothing on the card and an empty "Gate" row on the pass card. Proposed, which is a visible change and needs the owner's sign-off on the copy (decision 4): within about six hours of departure, when a status has been fetched and has no gate, a muted "Gate not posted yet" beside the status; outside that window nothing, as now. Upcoming's next-flight card should read the same stored gate.

## 4. What it does to the promises

Read against AGENTS.md's "Waypoint's promises" and "Private data in logs":

- **Email stays on the server**, **IDs are for the household**, **Photos**, **You see the trips you're on**: not touched by a gate. The status call's own sentence in the docs (a flight number and a date leave the server, nothing about a traveller) is the case the status call already makes.
- **Times are where they happen**: a gate has no time, and the push text must not convert the flight's time (the existing messages use the segment's own wall-clock time; reuse them).
- **Waypoint sends nothing about itself to any outside service**: unchanged. A gate notice goes to the push services the check-in notice already uses.

Per source:

- **AeroDataBox, kept (any plan, any cadence):** no new data leaves. The request is the same flight number and date, with the key in a header. More calls change the volume, not the content. No new Semgrep rule and no new import-linter contract: `waypoint-flightstatus-hosts` and `flightstatus-alone` already cover `providers/flightstatus.py`.
- **FlightAware AeroAPI (or any second API):** the request would still be a flight number and a date. AeroAPI accepts an airport code and a departure date, which Waypoint has, and nothing beyond flight number, date and airport codes is needed (**confirm** against its reference, which was behind a login). It needs: a new `providers/<name>.py` for the host, a new Semgrep rule in `.semgrep/waypoint.yml` naming only that file (as `waypoint-flightstatus-hosts` does), and an import-linter independence contract naming it with the other providers (`flightstatus-alone`, `gmail-alone`, `mailimages-alone`, `immich-alone` and `mapkit-alone` all list the others, so every one of them changes), plus strict typing and the 90% provider coverage floor. The two services must not import each other, so the choice between them lives in `domain/flightstatus.py`. A second key means another environment variable and another line in the docs' "what a request carries".
- **A hosted API that offers alerts by webhook** (AeroDataBox and AeroAPI both do): not for Waypoint. A webhook needs a public address the service can reach and a stored subscription per flight that expires and must be refreshed, and the provider's own page says create and refresh are billed. A self-hosted household instance is not guaranteed a public address, and polling a handful of flights is cheaper and simpler.
- **Scraping an airline or airport page:** a new outside host per site and its markup, with terms not assessed. Even if allowed it would be a new provider per site and a new class of fragile code, against `providers/` being "the outside services". Not recommended.
- **Anything that would send more than flight number, date and airport codes** (a traveller's name, a confirmation code, a loyalty number, an email): none of the sources above needs more, and none should be given more. An airline's own API that needs a booking reference or a name to show a trip is the only kind that would, and it is out: that is a promise change, not an integration.
- **The Semgrep host rule and the import-linter contracts need a new provider module only when a second host is added.** Staying on AeroDataBox needs none.

Also needed with any change that stores a gate: `monitoring.log` lines for the new job must not carry flight numbers beyond what the existing line carries (it logs the service's error text only), and a test run inside `no_leaks`.

## 5. Failure behaviour

The existing design already does what the issue asks, and a gate should inherit it:

- A source that is down, slow, refuses the key, rate-limits, answers 204 or 404, or answers something unreadable raises one of `NotConfigured`, `RateLimited`, `Refused` or `Unavailable` (`providers/flightstatus.py`). `_check` records the attempt, pauses an hour on a 429 or a refused key, logs a warning and carries on; the card shows the pause text or nothing, and nothing else about the trip changes. A service that answers without a gate yields `dep_gate = None`, which the card does not show.
- With the stored gate of section 3, one rule must be added and tested: **an answer with no gate does not erase a gate already known** (a source that drops the gate after boarding starts, or a feed that blanks it, should not make the gate disappear), but an answer that has a different gate replaces it. An answer with a gate for a flight that has since been cancelled is dropped with the rest of the status.
- A second source, if ever added, is consulted only when the first returned no gate, and its failure is handled the same way: the gate stays empty, nothing else changes, no retry loop (a failed call uses its checkpoint).
- Offline: the saved copy of a trip would carry the stored gate with its "as of" time, as a status already does. **Confirm** how the offline copy carries `flight_status` today before promising this.

## 6. Recommendation

**Keep AeroDataBox as the only source; make Waypoint hold and refresh what it gets; push on change. Do not add a second service now; add one only if a real run shows AeroDataBox has no gate at the household's airports.** In three lines:

1. No other source is both allowed for a household and better: the airline APIs are partner-only, the airport and airline pages mean scraping, the aggregators resell the same live feeds, and FlightAware's personal API is the only credible second source (about $0.005 a lookup, personal use allowed) but needs a new provider, host rule and contracts for a coverage gain nobody has measured.
2. The biggest gap is Waypoint's own: a gate it is told is thrown away after 15 minutes and fetched at only four moments before departure, so store the last gate, add checks at T-6h, T-2h and T-30m only while the gate is empty, and push a notice when a gate first appears or changes.
3. Before building, run one real week: log what AeroDataBox returns for each upcoming household flight at each checkpoint (gate present or not, and how many hours before departure) and decide the second-source question from that.

If a second source is wanted after that, it is FlightAware AeroAPI's personal tier, used as a fallback when AeroDataBox returns no gate in the last six hours, in its own provider module.

## 7. Decisions for the owner

1. **Is a stored gate acceptable?** It reverses the docs' rule that nothing that can still change is stored. It is a flight number, a date and a gate (no person, no booking) and is deleted with the other flight bookkeeping after seven days. If no, the gate can only ever be on screen for 15 minutes after a fetch.
2. **Spend more calls on gates?** The proposed extra checkpoints and their cost in section 3; or move to the Pro plan (about $8 a month) for headroom.
3. **Is a call 1 or 2 units for your US flights?** Read it off the RapidAPI dashboard; it halves or doesn't halve the household's monthly flight capacity.
4. **Copy and layout of "Gate not posted yet"**, and whether Upcoming's next flight shows it. A visible change, so it needs the signed-off design and `make verify` images at phone and desktop width.
5. **A gate notice:** wanted at all, and as a third preference (off by default) next to check-in and day-of?
6. **A second source:** none now (recommended), or FlightAware AeroAPI's personal tier as a fallback once a real week shows AeroDataBox is missing gates? It means a new account, key and card, and a new provider.
7. **Typing a gate in by hand:** wanted as a fallback for flights no source covers? It is the only source that always works, and it is a UI and storage change of its own.
8. **A real week of logging first** (recommended in section 6) or build now.

## 8. Proposed follow-up issues (not filed)

1. Keep the last known departure and arrival gate and terminal per flight and date, with the no-blank-overwrite rule, shown with its "as of" time on the trip page, Upcoming and the pass card (depends on decisions 1 and 4).
2. Gate-aware checkpoints: T-6h, T-2h and T-30m only while the gate is empty, dropped first under the reduced budget, with the monthly-limit text and the docs' budget paragraph updated.
3. A gate notice through the existing push providers: a new reminder kind and preference, one message per distinct gate (depends on 1 and decision 5).
4. A diagnostic week: record, per checkpoint, whether the answer had each of the four fields (counts and hours before departure, never the flight number), readable from the owner's settings page, then removed (a research aid; decision 8).
5. Only if the diagnostic says so: a second flight-status provider module (host rule, independence contract, key, docs, tests), consulted only when the first has no gate.

## 9. What was and wasn't checked

Checked, from the repository on `main`:

- The provider's parsing of the four fields, the checkpoints, the 15-minute hold, the final-status store, the monthly budget and pauses, the failure types and what each does (`providers/flightstatus.py`, `domain/flightstatus.py`, `server/jobs.py`).
- Where a gate shows (`FlightStatus.svelte`, `PassCard.svelte`), and that reminders carry no gate (`domain/reminders.py`).
- The Semgrep rule `waypoint-flightstatus-hosts` and the import-linter contracts that list the providers.

Checked, from public pages fetched in this session (no sign-up, no calls):

- AeroDataBox's pricing and data coverage pages; FlightAware's AeroAPI pricing page, forum thread on gates and terms of use; Aviationstack's pricing and documentation pages; search results about Delta's developer access, AeroDataBox's alert webhooks and the FAA's SWIM services.

Not checked:

- **Any real flight.** The Waypoint status tool is read-only and holds only what Waypoint has already fetched; for the two upcoming same-day flights on the household's trips it reported the feature enabled, not paused, and no status held. So it cannot say whether the status source returns a gate, for which airlines, or how early. **Not verified against real flights.** The airlines in the household's data were not individually checked; Delta's own developer portal could not be fetched from this session, American's refused an anonymous request, and the one airport page tried returned 404.
- Whether a status call costs one or two units for the household's flights.
- AeroAPI's actual gate fields and whether a card is needed (its documentation is behind a login), Aviationstack's real-time field list, and every claim marked **confirm**.
- The terms of any airline or airport page for automated reads.
- The expectation in section 1 that gates appear a few hours before departure is general experience, not a measurement.
