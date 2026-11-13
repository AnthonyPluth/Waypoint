# Research: where flight gate numbers can come from when the booking email has none (#635)

Status: research only; nothing is built and no follow-up issue is filed (section 8 proposes them). Facts about the current code come from reading it on `main`. Facts about other services come from their public pages (pricing, documentation, terms), fetched in this session; nothing was signed up for, paid for or called, and no household data was sent anywhere. A claim from memory rather than a page is marked **confirm**.

Owner's direction, added after the first draft: lean on the local AI reading the airlines' own gate and gate-change emails instead of building a parser per airline. That is section 3a and now the first half of the recommendation (section 6); AeroDataBox stays, as the fallback. Everything in 3a comes from the code and the docs; no email, airline or flight was looked at.

What was and wasn't checked against real flights is in section 9. Short version: nothing was checked against a real flight's gate. The read-only status tool answered for the household's two same-day upcoming flights with no status held, which is what the tool does when Waypoint has not asked the service (it never looks anything up), so the question "how many hours before departure does a gate appear" is **not verified against real flights**.

## 1. What the current source returns

The source is AeroDataBox through RapidAPI (`waypoint/providers/flightstatus.py`, host `aerodatabox.p.rapidapi.com`, one request, `GET /flights/number/{number}/{date}`). Off until `RAPIDAPI_KEY` is set.

What the code does with a gate:

- `_side` reads `departure.terminal`, `departure.gate`, `arrival.terminal` and `arrival.gate` from the reply, each trimmed to 10 characters (`dep_gate`, `arr_gate`, `dep_terminal`, `arr_terminal` on `Status`). A missing or non-text value is `None`. Waypoint does not invent, infer or carry over a gate: whatever the service says at that call is what is shown, and an absent field is an empty gate.
- The same four values pass through `domain/flightstatus.py` (`_out`, `StatusOut`), the API contract and `frontend/src/lib/api-types.ts` unchanged. There is nothing to add to the schema to show a gate from this source.

When a call is made (`domain/flightstatus.py`):

- `run_due` runs from a background job (`check_flights` in `server/jobs.py`) over flights starting between two days ago and three days ahead (`watching`). A flight is checked at its booked departure minus 24 hours, 3 hours, 1 hour and 20 minutes, and once at the booked arrival (`CHECKS`, `checkpoints`). After downtime only the latest missed checkpoint is made up. A failed call still uses its checkpoint.
- Refresh on a flight's card fetches now unless an answer under 15 minutes old is held (`REFRESH_AFTER`).
- A monthly counter caps requests, not units: `_spend` adds one per request and `usage` compares that count with the limit (default 400, `WAYPOINT_FLIGHT_STATUS_MONTHLY_LIMIT`). It knows nothing of what the service charges per request. At 90% of the limit only the one-hour check is kept; at 100% nothing is fetched until the 1st; a 429 or a refused key pauses fetching for an hour.

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
| The airline's own gate and gate-change emails, read by the local AI (Ollama, Local mode only) | Yes, when the airline sends one and the household's mailbox receives it; the airline decides if and when | Nothing per message beyond the household's own Ollama server; no outside service, no key | The mail is the household's own and already read in memory by Waypoint; the AI path is the existing one (section 3a) | The Gmail connection and Local AI already in Settings |
| Typing the gate in by hand | Whatever the person reads off the airline's app or the board | Free | None | None |

What this means for the household's scale: a household makes a few flights a month, so any of the paid APIs is a few dollars at most, and the free AeroDataBox plan is already enough for the calls as long as the budget is spent where the gate is (section 3). The limit that bites is not the quota but whether the source has the gate at all, and no source in the table was shown to have it for the household's airports.

No source here publishes gates that no other source also gets from the airline or airport; the aggregators resell the same live feeds. So adding a second aggregator mostly buys a second chance at the same airport coverage, not new information. That is the only reason to add one (section 6).

## 3. How a gate would reach the user

Three changes, from cheapest and most useful. None is built.

1. **Keep a gate once it is known.** The card should show the last gate Waypoint was told, with its "as of" time, until the next answer replaces it, not for 15 minutes. That needs a small stored row per flight number and date (departure terminal and gate, arrival terminal and gate, when fetched), the shape of the existing `flight_status` row for finals: a flight number, a date and a gate hold no personal data and are not tied to a booking. It changes the docs' sentence that anything that can still change is never stored, so it is decision 1 below. Without it nothing else in this section is worth building.

2. **Refresh nearer departure and when the gate is empty.** Keep the current checkpoints and add T-6h, T-2h and T-30m, and make the added ones conditional: skip them once the gate is known and fresh, so a flight whose gate is posted early costs the same as today. Rough budget: 8 checkpoints is about 50 flights a month at 1 unit a call and about 25 at 2 units, against about 80 and 40 today (400 units). The existing reduced-budget rule (above 90% of the limit only the one-hour check) protects the allowance only if the limit is in the same unit as the allowance. It counts requests, so at 2 units a request the default limit of 400 lets Waypoint spend 800 units before the cap, and the reduction starts at 360 requests, which is 720 units, past a 400-unit plan. **The extra checkpoints must not be presented as covered by that guard until `WAYPOINT_FLIGHT_STATUS_MONTHLY_LIMIT` is set to the plan's units divided by the confirmed units per request (200 for a 400-unit plan at 2 units), or the accounting is made unit-aware (follow-up 2).** With that set, the added checkpoints should be the first dropped. If the owner wants more headroom the cheapest lever is the Pro plan at about $8 a month for 5,000 units, not a second service. Whether a call is 1 or 2 units for the household's US flights is something to read off the RapidAPI dashboard before choosing (decision 3).

3. **Push when a gate appears or changes.** The push providers exist (`providers/webpush.py`, `providers/apns.py`) and `domain/reminders.py` already sends a flight message through `_deliver` and records it in `reminder_sent` by owner, kind and a `ref`. A gate notice would be a new kind whose `ref` includes the segment and the gate, such as the segment id and the gate text, so each distinct gate sends once and a later change sends again, with the segment's tag so the new one replaces the old on the device. It needs a third preference next to check-in and day-of (off by default, as those are, **confirm**), and a read of the stored gate from change 1 so a change is noticed between runs. Text: the flight and the gate, nothing more; check-in notices already carry the flight number, so no new class of data goes to Apple's or the browser's push service. A gate that goes back to an earlier value would not notify again; that is acceptable.

What the page shows before a gate is known: today, nothing on the card and an empty "Gate" row on the pass card. Proposed, which is a visible change and needs the owner's sign-off on the copy (decision 4): within about six hours of departure, when a status has been fetched and has no gate, a muted "Gate not posted yet" beside the status; outside that window nothing, as now. Upcoming's next-flight card should read the same stored gate.

## 3a. Gate emails read by the local AI (owner's direction)

The owner's direction is to lean on the existing local AI path to read the emails airlines send when a gate is assigned or changed (and any status email that states one), instead of building a parser for each airline. This section says how that would work, what it would keep, and where it stops. Nothing is built. Whether Delta, American or any other airline sends such emails to the household is **not verified**; the whole option is worth exactly what the airlines send.

What happens to such a message today (from `waypoint/domain/mail/scan.py`, `followup.py`, `references.py`, `autoask.py` and the AI docs):

- A message with no booking in it, carrying the confirmation code of exactly one visible reservation from the same sender, is a follow-up (`followup.attach`): remembered by its Gmail id and that booking's id alone and not stored. `references.facts_in` already notices that its text mentions a gate (and a terminal, a seat or an address), and the scan counts it as a follow-up "with details not applied": `FACT_DETAIL` maps a gate to nothing, so a gate is never applied and never read by the AI.
- Follow-ups are also excluded from the automatic AI reading, which takes only a message that passed triage with a strong travel signal, that no reader produced a booking for and that is not a follow-up of a booking the person can see.
- A gate email with no confirmation code is an unreadable message: triage may skip it, or it waits in Review for **Ask AI**, whose answer is a booking, not a gate.

So today no path reads a gate from an email.

How it would route, with no vendor parser: a new step after the follow-up check, for flights only.

1. **Cheap filter first.** The existing generic cues decide whether to ask the AI at all: the message has no booking of its own, its sender is the sender of a visible flight's provider or of mail already attached to it (`_same_sender`), and its text matches the gate cue in `references.py`. That regex is shared by every airline; it is a filter, not a reading, and an airline that words things differently is simply not asked.
2. **A narrower question than "what is the booking".** The Local AI (`ai.mail_config`, Ollama only) is asked for a handful of fields: the gate, the terminal, which airport and whether it is a departure or arrival, the flight number, the flight's date, the confirmation code if printed, and whether the message says the gate is new or changed. It is not asked for, and cannot create, a booking.
3. **Validated like other AI output.** A reply that isn't JSON of that shape is thrown away whole. Each value must appear verbatim in the text that was sent (as an address or phone must today), a gate and a terminal must have the shape of one and fit the 10 characters the status source keeps, and a flight number must match the booking's. Nothing is completed by guessing.
4. **Tied to a visible flight, or dropped.** The message sets a gate only when it names one visible flight, either by the confirmation code of one visible reservation from the same sender (the follow-up rule, unchanged) or, for a message with no code, by flight number, departure date and the departure airport all matching exactly one flight the person can see. If two flights match (two trips, two travellers' bookings) or none, nothing is applied. The second way is wider than the promise's present sentence, which says a follow-up is "never matched on dates or names": a flight number and date printed in the message are facts, not a guess, but the sentence and the promise's checks would change with it (decision 10).
5. **An unclear read is dropped, not queued.** A Review item holds a booking, and a gate is not one, so a gate Waypoint can't tie to a flight or read with confidence is left off, the message stays a counted follow-up with details not applied, and the mailbox's last-scan line counts them (counts only, as now). Sending it to Review would be a new kind of item and a visible change (decision 11).
6. **Window.** Only flights that leave within about 48 hours and have not yet arrived are asked about; an older flight's gate is no use, and it keeps the AI's load to a few messages a day.

What the AI is sent, and the promise it keeps (AGENTS.md "Email stays on the server"):

- Same as **Ask AI** today: the message's plain text only, unredacted and untrimmed, to the household's own Ollama server through the one module that asks the AI (`domain/mail/ai.py`), never markup, never a picture, never the subject or sender, never logged, never a hosted provider. The sender check above runs on Waypoint's side, before anything is sent.
- With the AI Off or on OpenRouter nothing is sent and gates come only from the status source.
- This is a new reason to send email text to the AI, so it needs its own consent, in the way "Read unreadable mail with AI automatically" and its gap-filling extension did: a household that turned the existing switch on keeps its narrower behaviour until someone chooses the new wording, off by default, offered only while the AI is Local, with a plain warning ("Waypoint will send the text of an airline's gate and status emails to the AI you chose, without asking each time") (decision 9). It extends the promise's list of cases in which email text reaches an AI, and its checks: `waypoint-mail-ai-local-only`, `tests/test_mail_ai_auto.py`'s two-switch rule and a test inside `no_leaks` with canary values in the body.
- What is kept: the booking's gate and terminal fields (and the time of the message that gave them), and the message's Gmail id remembered with the booking's id, as for any follow-up. The message text, the AI's prompt and its reply are not kept.

Accuracy:

- A gate comes only from a message tied to a visible flight as above; a message from another sender, a marketing email that mentions a gate, a forward from someone else or a message for a flight the person can't see sets nothing.
- Departure and arrival gates are separate fields; a message that doesn't say which end is dropped.
- A hand-edited gate is never overwritten (`locked_fields`); the booking says a newer email disagreed, as #639 does.
- The read is only as good as the model, so before relying on it the model should be run over a handful of real gate emails kept by the owner (outside the repository, which is public) and judged by hand; the repository's tests use made-up emails with invented gates and canary values.

How it composes with #636 and its pull request #639 (open and a draft when this was written, so this assumes it merges):

- #639 replaces a booking's attached email, and applies its fields, when a newer message is a booking of its own for the same reservation. A gate email has no booking, so it never goes through that step (`newer.decide` takes a parsed booking), does not replace the attached confirmation and does not make older emails go. It sets only the gate and terminal fields.
- "Newer" in #639 means a strictly later day of the message's own `Date`, so two gate emails on the same day (assigned, then changed an hour later) are not ordered by it. The gate needs its own order: the message's own timestamp to the minute, kept as a number beside the gate (bookkeeping, not content), so an older gate email scanned later never replaces a newer gate. This is a field #639 does not have and the main thing to settle before building.
- The rules that do carry over: locked fields stay, the booking records that a newer email disagreed, and the same web push path (`jobs.notify_times`, which sends one push per flight and new time when it leaves within 24 hours) is the model for the gate push.

Which gate the card shows when the email and the status source both have one: the one with the later "as of" time wins, labelled with where it came from ("from the airline's email" or "from live status", with its time); a hand-edited gate wins over both (decision 12). The status source (AeroDataBox) stays as the fallback for every flight with no gate email, and its answers continue to refresh the card near departure as in section 3.

The push: when a gate first appears or changes from either source, one notice through the existing push providers, as section 3 proposes: the flight label and the gate, a new reminder kind whose `ref` includes the segment and the gate so each distinct gate sends once. It is the same follow-up for both sources.

The timing problem the AI does not solve: mail is scanned every four hours (`SCAN_EVERY` in `server/jobs.py`) and Gmail's history is asked only then, so a gate email that arrives an hour before departure would be read up to four hours later. This option is useless without a near-departure mail check: while a visible flight leaves within about 12 hours, check the mailbox for new mail from that flight's sender every 10 to 15 minutes (Gmail's history call, the sender filter the scanner already takes), and stop at departure. That is more frequent Gmail use than the docs describe ("every few hours"), so the Gmail docs and the privacy page change with it. Waiting for Google to push (Gmail's watch needs a public address and a Google Cloud topic) is not something a household instance can count on.

What it can't do:

- No email, no gate. An airline that doesn't email gates (many show them only in their app or at the airport) gives nothing here, and the status source is the only route. Which airlines in the household's trips email gates is not known; Delta's and American's behaviour is unverified, and no email was read for this note.
- A household whose mailbox isn't connected, or whose AI is Off or hosted, gets nothing from it.
- It depends on the Ollama server being up and fast enough; a message that can't be asked about is retried at most twice more, as other automatic reads are, and then left, and by then the gate may have changed again.
- It can only be as early as the airline's email, and a gate email that arrives after the flight has left is of no use.
- Two travellers on one flight with different mailboxes would both see the gate; the field is the booking's and is visible to everyone who can see the booking, as every other field is.

## 4. What it does to the promises

Read against AGENTS.md's "Waypoint's promises" and "Private data in logs":

- **Email stays on the server**, **IDs are for the household**, **Photos**, **You see the trips you're on**: not touched by a gate. The status call's own sentence in the docs (a flight number and a date leave the server, nothing about a traveller) is the case the status call already makes.
- **Times are where they happen**: a gate has no time, and the push text must not convert the flight's time (the existing messages use the segment's own wall-clock time; reuse them).
- **Waypoint sends nothing about itself to any outside service**: unchanged. A gate notice goes to the push services the check-in notice already uses.

Per source:

- **Gate emails read by the local AI (section 3a):** no new host and no new provider module: email text goes only to the household's Ollama server through the existing module, so the Semgrep rules (`waypoint-mail-ai-local-only`, `waypoint-ai-hosts`) and the import-linter contracts need nothing new. What does change is the email promise's list of reasons email text reaches an AI (a third one, with its own switch and consent wording), its statement of how often a mailbox is read (a near-departure check), and the sentence that a follow-up is never matched on dates or names if a message with no code is matched on flight number, date and airport. Those are decisions 9, 10 and 13.
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
- The email route fails the same way: an unreachable or slow Ollama, a reply that isn't the expected JSON, a value not in the text, a message that ties to no flight or to two, or the AI set to Off or hosted all leave the gate empty and the message a counted follow-up with details not applied; nothing else about the trip changes and no error shows. A gate from the email is never blanked by a later message that has none.
- A second source, if ever added, is consulted only when the first returned no gate, and its failure is handled the same way: the gate stays empty, nothing else changes, no retry loop (a failed call uses its checkpoint).
- Offline: the saved copy of a trip would carry the stored gate with its "as of" time, as a status already does. **Confirm** how the offline copy carries `flight_status` today before promising this.

## 6. Recommendation

**Two layers: read the airline's own gate emails with the local AI as the first source, and keep AeroDataBox as the fallback and the refresh. Do not build a parser for any airline, and do not add a second status service now.** In four lines:

1. Gate emails first (section 3a): the existing local AI path reads gate and gate-change emails from the sender of a visible flight, validated like other AI output, tied to the flight by its confirmation code or by flight number, date and airport, applied only to the booking's gate and terminal fields, never stored as text, with an unclear read dropped. It is the only source that costs nothing, needs no new account and sends nothing outside the household's network, and it needs a near-departure mail check to be of any use (mail is scanned every four hours today).
2. AeroDataBox stays for every flight with no gate email, and fixes Waypoint's own gap: a gate it is told is thrown away after 15 minutes and fetched at only four moments before departure, so store the last gate, add checks at T-6h, T-2h and T-30m only while the gate is empty (after setting `WAYPOINT_FLIGHT_STATUS_MONTHLY_LIMIT` to the plan's units divided by the confirmed units per request, or making the counter unit-aware, because the existing guard counts requests, not units), and show the later of the two sources' gates with where it came from.
3. One push when a gate first appears or changes, from either source, through the existing providers.
4. Before building, run one real week and one real read: log what AeroDataBox returns for each upcoming household flight at each checkpoint, and have the owner try the local model on a few real gate emails (outside the repository) to see which airlines send them, how early, and whether the model reads them right. The share of flights covered by either layer decides whether a second status service is ever needed; if it is, FlightAware AeroAPI's personal tier in its own provider module is the candidate.

Why not other sources: the airline APIs are partner-only, the airport and airline pages mean scraping, the aggregators resell the same live feeds, and FlightAware's personal API (about $0.005 a lookup, personal use allowed) needs a new provider, host rule and contracts for a coverage gain nobody has measured.

## 7. Decisions for the owner

1. **Is a stored gate acceptable?** It reverses the docs' rule that nothing that can still change is stored. It is a flight number, a date and a gate (no person, no booking) and is deleted with the other flight bookkeeping after seven days. If no, the gate can only ever be on screen for 15 minutes after a fetch.
2. **Spend more calls on gates?** The proposed extra checkpoints and their cost in section 3; or move to the Pro plan (about $8 a month) for headroom.
3. **Is a call 1 or 2 units for your US flights?** Read it off the RapidAPI dashboard; it halves or doesn't halve the household's monthly flight capacity, and it decides what `WAYPOINT_FLIGHT_STATUS_MONTHLY_LIMIT` must be set to (the plan's units divided by units per request) before any extra checkpoint ships, because the guard counts requests. This is a pre-build check, not only a preference.
4. **Copy and layout of "Gate not posted yet"**, and whether Upcoming's next flight shows it. A visible change, so it needs the signed-off design and `make verify` images at phone and desktop width.
5. **A gate notice:** wanted at all, and as a third preference (off by default) next to check-in and day-of?
6. **A second source:** none now (recommended), or FlightAware AeroAPI's personal tier as a fallback once a real week shows AeroDataBox is missing gates? It means a new account, key and card, and a new provider.
7. **Typing a gate in by hand:** wanted as a fallback for flights no source covers? It is the only source that always works, and it is a UI and storage change of its own.
8. **Set the request limit to the real unit cost before any extra checkpoint ships** (the plan's units divided by units per request; 200 for 400 units at 2 units a request), or ask for unit-aware accounting. Today's guard counts requests, so it does not protect the allowance otherwise (section 3, change 2).
9. **A new consent for reading airline gate and status emails with the local AI**, off by default, Local only, with the warning in section 3a, as a third reason email text reaches an AI. Or no email reading and the status source alone.
10. **Matching a message with no confirmation code to a flight** by flight number, departure date and departure airport, all printed in it, all matching exactly one visible flight? It is wider than "never matched on dates or names" in the promise. If no, only messages carrying the code count and gate emails without one are lost.
11. **An unclear gate read:** dropped and counted (recommended), or sent to Review as a new kind of item (a visible change needing design sign-off).
12. **Which gate wins** when the email and the status source differ: the later one with its source shown (recommended), the email always, or the status source always. A hand-edited gate wins over both.
13. **A near-departure mail check** (every 10 to 15 minutes while a flight leaves within about 12 hours, from that flight's sender): acceptable, given it is more Gmail use than the docs describe? Without it the email route can't deliver a gate in time.
14. **A real week of logging and a try on a few real gate emails first** (recommended in section 6) or build now.

## 8. Proposed follow-up issues (not filed)

1. Keep the last known departure and arrival gate and terminal per flight and date, with the no-blank-overwrite rule, shown with its "as of" time on the trip page, Upcoming and the pass card (depends on decisions 1 and 4).
2. Gate-aware checkpoints: T-6h, T-2h and T-30m only while the gate is empty, dropped first under the reduced budget, with the monthly-limit text and the docs' budget paragraph updated. It must either make the counter unit-aware (record the units each call costs, which the service's reply or dashboard has to show, **confirm**) or document and check that the limit is set to units divided by units per request; without one of the two the reduced-budget rule does not protect the allowance.
3. A gate notice through the existing push providers: a new reminder kind and preference, one message per distinct gate (depends on 1 and decision 5).
4. A diagnostic week: record, per checkpoint, whether the answer had each of the four fields (counts and hours before departure, never the flight number), readable from the owner's settings page, then removed (a research aid; decision 14).
5. Read airline gate and status emails with the local AI: the narrower AI question and its validation, the gate and terminal fields with the message's own timestamp, tying to a visible flight, the new consent switch and its docs and privacy wording, the AGENTS.md promise and checks updated with it (depends on 1 and decisions 9 to 12, and on #639 merging).
6. A near-departure mail check while a flight is about to leave, with the Gmail docs updated (depends on 5 and decision 13).
7. Only if the diagnostic says so: a second flight-status provider module (host rule, independence contract, key, docs, tests), consulted only when the first has no gate.

## 9. What was and wasn't checked

Checked, from the repository on `main`:

- The provider's parsing of the four fields, the checkpoints, the 15-minute hold, the final-status store, the monthly budget and pauses, the failure types and what each does (`providers/flightstatus.py`, `domain/flightstatus.py`, `server/jobs.py`).
- Where a gate shows (`FlightStatus.svelte`, `PassCard.svelte`), and that reminders carry no gate (`domain/reminders.py`).
- The Semgrep rule `waypoint-flightstatus-hosts` and the import-linter contracts that list the providers.

Checked, from public pages fetched in this session (no sign-up, no calls):

- AeroDataBox's pricing and data coverage pages; FlightAware's AeroAPI pricing page, forum thread on gates and terms of use; Aviationstack's pricing and documentation pages; search results about Delta's developer access, AeroDataBox's alert webhooks and the FAA's SWIM services.

Checked, for the email option (from the code and the docs only): how a gate email is handled today (`scan.py`, `followup.py`, `references.py`, `autoask.py`, the AI docs), the scan interval (`SCAN_EVERY`, every four hours), and what #639's `newer.decide` does and does not take (read from the pull request's diff, a draft that had not merged).

Not checked:

- **Any real flight.** The Waypoint status tool is read-only and holds only what Waypoint has already fetched; for the two upcoming same-day flights on the household's trips it reported the feature enabled, not paused, and no status held. So it cannot say whether the status source returns a gate, for which airlines, or how early. **Not verified against real flights.** The airlines in the household's data were not individually checked; Delta's own developer portal could not be fetched from this session, American's refused an anonymous request, and the one airport page tried returned 404.
- Whether a status call costs one or two units for the household's flights. Until that is known, how far the existing request-counting guard (`_spend`, `usage`) falls short of the plan's allowance is also unknown; section 3 makes it a pre-build check.
- AeroAPI's actual gate fields and whether a card is needed (its documentation is behind a login), Aviationstack's real-time field list, and every claim marked **confirm**.
- The terms of any airline or airport page for automated reads.
- Whether any airline in the household's trips emails a gate or a gate change, how early, and what such a message says; whether the local model reads one correctly; no real email was opened or read. Delta's and American's behaviour is unverified.
- Whether #639 merges as it stands, which section 3a assumes.
- The expectation in section 1 that gates appear a few hours before departure is general experience, not a measurement.
