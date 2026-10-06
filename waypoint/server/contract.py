"""The API's contract with the web app: the request bodies and replies of the routes it covers, as TypedDicts.

A handler names its reply (its return annotation) and, for a route that takes one, its body (the annotation of its third
parameter) with a type from here; mypy then holds the handler to it, and tools/api_contract.py turns those annotations,
with the route table (routes.py), into docs/openapi.json and the web app's frontend/src/lib/api-types.ts. `make check`
and CI fail when either is out of date, and tests/test_api_contract.py checks each covered route's real reply against
docs/openapi.json, so a field renamed on one side fails the web app's type-check, the drift check or the tests.

A body is what the web app sends. The handler still checks every value it reads (waypoint/validate.py): anyone can send
anything, so a field typed `float | str` here is one the validators accept as either ("12.50" or 12.5).

Only the types the generator understands are used here: str, int, float, bool, None, Any, `X | Y`, list[X],
dict[str, X], Literal[...], NotRequired[X], and the TypedDicts in this module (a subclass has its base's fields too).
Not every route is covered yet; tools/api_contract.py lists the ones that are.
"""
from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


class Ok(TypedDict):
    ok: bool


# The app's state

class SignedIn(TypedDict):
    """Who's signed in. Without sign-in configured (on your own machine), everyone is `local`."""
    name: str | None
    email: str | None
    sub: NotRequired[str]       # the sign-in provider's id for them (with sign-in on)
    local: NotRequired[bool]


class State(TypedDict):
    version: str
    database: Literal["sqlite", "postgres"]
    user: SignedIn | None
    last_backup: str | None         # when a backup was last downloaded from Settings, with its UTC offset
    review_count: int               # what waits in Review for the signed-in member: mail Waypoint couldn't read, names to match
    person_id: int | None           # the signed-in member's own person (whose stats the Stats page opens on); none on your own machine


# Backups

class BackupContents(TypedDict):
    created: str | None
    source: str | None
    counts: dict[str, int]
    current: dict[str, int]
    database: Literal["sqlite", "postgres"]


class Restored(TypedDict):
    ok: bool
    created: str | None
    source: str | None
    counts: dict[str, int]
    safety_copy: str | None
    unreadable_secrets: list[str]


# Gmail connections

class Mailbox(TypedDict):
    id: int
    address: str
    status: Literal["connected", "reconnect", "error"]   # reconnect: Google no longer honours it; error: it couldn't be reached
    last_error: str | None
    last_scan: str | None           # when a scan last finished, with its UTC offset
    scan_error: str | None          # what the last scan couldn't do (the last good state is kept); null once one finishes
    scanning: bool                  # a scan is running now
    scan_notice: str | None         # why the last scan couldn't start (nothing was recorded; it isn't a failed scan), until one does
    share_review: bool              # its "Couldn't read" items are shown to the household (off until its owner says)


class MailboxList(TypedDict):
    configured: bool                # GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are set
    mailboxes: list[Mailbox]        # the signed-in member's own


class ShareBody(TypedDict):
    share: bool                     # show this mailbox's "Couldn't read" items to the household, or stop


class Started(TypedDict):
    url: str                        # Google's consent screen, to send the browser to


class ScanStarted(TypedDict):
    started: bool                   # false when a scan of this mailbox was already running


class Disconnected(TypedDict):
    ok: bool
    revoked: bool                   # false when Waypoint couldn't unlock the saved token to revoke it: remove it at Google


# Review: mail that looked like a booking and couldn't be read, and names on bookings to match to people

class AiSuggestion(TypedDict):
    """The booking's fields the AI read, as the Add by hand form has them. A flight has no zones: its airports give them."""
    kind: Literal["flight", "hotel", "car", "train"]
    origin: str
    start_local: str                # YYYY-MM-DDTHH:MM, as written at the place
    end_local: str
    provider: NotRequired[str]
    confirmation: NotRequired[str]
    destination: NotRequired[str]
    start_zone: NotRequired[str]
    end_zone: NotRequired[str]


class ReviewItem(TypedDict):
    """One message Waypoint couldn't read, for the member whose mailbox it is and, when its owner shares that mailbox, the
    household. Never its subject or text: only who it came from and its day (Open in Gmail shows the message, to its owner)."""
    id: int
    address: str                    # the mailbox it came from
    owner: str                      # whose mailbox it is
    mine: bool                      # the signed-in member's own; false: shared with them, and they can only add it by hand or dismiss it
    sender_domain: str              # empty when the message didn't say
    received: str | None            # a day, YYYY-MM-DD
    reason: Literal["no_markup", "incomplete", "broken"]   # no booking details in it; some missing; couldn't be opened
    gmail_url: str | None           # opens the message in Gmail; none for someone else's
    suggestion: AiSuggestion | None   # what the optional AI read from it (never its text), pre-filled into Add by hand to confirm or edit
    suggestion_error: str | None    # why the AI gave none, in fixed text


class WhoIsThis(TypedDict):
    """A name on a booking that isn't matched to a person, with the segment it's on."""
    id: int                         # the traveller to match
    name: str                       # as printed on the booking
    segment_id: int
    trip_id: int
    kind: Literal["flight", "hotel", "car", "train", "cruise"]
    provider: str | None
    origin: str | None
    destination: str | None
    start_local: str
    start_zone: str


class Review(TypedDict):
    items: list[ReviewItem]
    who: list[WhoIsThis]
    ai: bool                        # the optional AI is on, so Ask AI works


class Preview(TypedDict):
    """A review item's message as plain text and, when it has an HTML part, as markup rebuilt from an allowlist (no scripts, styles,
    images or remote loads), fetched from Gmail when asked and shown to its mailbox's owner alone; Waypoint keeps none of it."""
    text: str
    html: str | None                # null: the message has no HTML part
    truncated: bool                 # cut at 30,000 characters


class WhoBody(TypedDict):
    """Who a printed name is: a person in People, or a name to add as a guest. Send one."""
    person_id: NotRequired[int]
    new_guest: NotRequired[str]


class Matched(TypedDict):
    ok: bool
    matched: int                    # how many travellers on bookings became that person (the same printed name is matched everywhere)


# AI (optional, off by default)

class AiSettings(TypedDict):
    mode: Literal["off", "local", "openrouter"]   # off; Ollama on your own network; OpenRouter with zero data retention
    ollama_url: str
    ollama_model: str
    openrouter_model: str
    key: Literal["env", "saved"] | None            # where the OpenRouter key comes from; the key itself never comes back


# Brand logos (optional, off until a Logo.dev key is saved)

class LogoDevStatus(TypedDict):
    configured: bool                # a publishable key is saved (the key itself never comes back)
    searchable: bool                # a secret key is saved too: Brand Search picks the brand
    with_logo: int                  # brands that have a logo
    unknown: int                    # brands that have no logo at the services asked
    waiting: int                    # brands not asked about yet
    last_error: str | None          # why the last round failed (fixed text)


class LogoDevFetch(TypedDict):
    started: bool                   # false when a round of fetching was already running


class LogoDevBody(TypedDict):
    """Settings → Logos. A field left out stays as it was; `clear` forgets the publishable key (and so the secret one too),
    `clear_secret` forgets only the secret key."""
    token: NotRequired[str]         # the publishable key, pk_...
    secret: NotRequired[str]        # the secret key, sk_...
    clear: NotRequired[bool]
    clear_secret: NotRequired[bool]


class AiBody(TypedDict):
    """Settings → AI. A field left out stays as it was; `openrouter_key: ""` forgets the saved key."""
    mode: Literal["off", "local", "openrouter"]
    ollama_url: NotRequired[str]
    ollama_model: NotRequired[str]
    openrouter_model: NotRequired[str]
    openrouter_key: NotRequired[str]


# People

class Person(TypedDict):
    """Someone who travels: a household member (`member`, linked to their sign-in) or a guest with no login."""
    id: int
    display_name: str
    first_name: str | None
    legal_name: str | None         # as on an ID
    aliases: list[str]             # how airlines print the name ("DOE/JANE MS")
    member: bool
    links: list[PersonLink]        # the guests this member claimed ("This is me"), oldest first


class PersonLink(TypedDict):
    """A guest a member claimed: their name, the member who claimed it and the day (YYYY-MM-DD)."""
    guest: str
    by: str
    on: str


class People(TypedDict):
    people: list[Person]            # members first, then guests


class ClaimSuggestions(TypedDict):
    """Guests the signed-in member may be (their name matches, and they have no trips yet), for "Are you one of these?"."""
    guests: list[Person]


class PersonBody(TypedDict):
    """A person's names, to add a guest or to change anyone's (a member's link to their login can't be changed). Changing
    replaces all of them, so send every name to keep: one left out is cleared."""
    display_name: str
    first_name: NotRequired[str | None]
    legal_name: NotRequired[str | None]
    aliases: NotRequired[list[str]]


# Trips and segments

class Traveler(TypedDict):
    id: int
    person_id: int | None           # null until the printed name is matched to a person
    name: str                       # the person's name, or the name as printed on the booking
    seat: str | None                # their seat on this segment


class SegmentLinks(TypedDict):
    app: str | None                 # the provider's manage-trip page (https): its app opens it if installed
    directions: str | None          # Apple Maps, for a hotel or a rental
    call: str | None                # tel:


class Port(TypedDict):
    """A cruise's port of call. Its times are local wall-clock times at the port, in its `zone`."""
    name: str
    zone: str
    arrive_local: str | None
    depart_local: str | None


class Segment(TypedDict):
    """One flight leg, hotel stay, car rental, train or cruise. Its times are local wall-clock times at the place, never
    converted: `start_local` is 2026-03-01T22:15 in `start_zone`, whatever zone the server or the viewer is in."""
    id: int
    trip_id: int
    kind: Literal["flight", "hotel", "car", "train", "cruise"]
    status: Literal["confirmed", "changed", "cancelled"]
    confirmation: str | None
    provider: str | None
    start_local: str                # a hotel's check-in, a car's pick-up, a flight's departure
    start_zone: str                 # the IANA zone of the place it starts (Pacific/Auckland)
    end_local: str
    end_zone: str
    origin: str | None              # a flight's airport code; a stay's or a rental's place
    destination: str | None
    details: dict[str, str]         # flight_number, terminal, seat, cabin, room, car_class, address, phone, ship, deck; time_unknown (an imported flight with no times)
    manage_url: str | None
    source: Literal["manual", "email", "import"]
    booked_by: int | None           # a person
    locked_fields: list[str]        # what a person edited, which a later email never overwrites
    check_times: bool               # an email's times couldn't be settled: the card asks for a look, until they're edited or confirmed
    travelers: list[Traveler]
    itinerary: list[Port]           # a cruise's ports of call in order (empty for anything else)
    logo: str | None                # where Waypoint serves its brand's logo (the airline, hotel, rental company or cruise line), when it has one
    logo_label: str | None          # a hotel brand's name ("Hyatt Regency") when the logo is its group's, not the brand's own; else null
    links: SegmentLinks              # the card's actions, built by the server


class Trip(TypedDict):
    id: int
    name: str
    start_date: str | None          # the local dates of its first and last segments
    end_date: str | None
    destination: str | None
    notes: str | None
    auto: bool                      # grouped by Waypoint; false once made or changed by hand
    booked_by: int | None
    segments: list[Segment]         # by start time


class TripList(TypedDict):
    trips: list[Trip]               # the signed-in member's own: the ones they're travelling on or booked


class TripBody(TypedDict):
    """A trip made by hand, or what changes on one (a name, where it goes, notes; its dates come from its segments)."""
    name: NotRequired[str]
    destination: NotRequired[str | None]
    notes: NotRequired[str | None]
    start_date: NotRequired[str | None]     # when creating one with no segments yet, with end_date
    end_date: NotRequired[str | None]


class MergeBody(TypedDict):
    merge: int                      # the trip to fold into this one


class SplitBody(TypedDict):
    segment_ids: list[int]          # the segments to move to a new trip


class TravelerBody(TypedDict):
    person_id: NotRequired[int | None]
    name: NotRequired[str | None]   # as printed on the booking
    seat: NotRequired[str | None]   # their seat; left out, it stays as it was


class SegmentBody(TypedDict):
    """A segment to add; `trip_id` leaves it to Waypoint to group it into a trip. A flight's zones come from its airports
    unless given."""
    kind: Literal["flight", "hotel", "car", "train", "cruise"]
    start_local: str
    end_local: str
    trip_id: NotRequired[int | None]
    status: NotRequired[Literal["confirmed", "changed", "cancelled"]]
    confirmation: NotRequired[str | None]
    provider: NotRequired[str | None]
    start_zone: NotRequired[str | None]
    end_zone: NotRequired[str | None]
    origin: NotRequired[str | None]
    destination: NotRequired[str | None]
    details: NotRequired[dict[str, str]]
    manage_url: NotRequired[str | None]
    travelers: NotRequired[list[TravelerBody]]   # who it's for; the signed-in member when left out
    itinerary: NotRequired[list[Port]]           # a cruise's ports of call, in order


class SegmentEdit(TypedDict):
    """What to change on a segment: only the fields sent. The ones that end up different are locked."""
    kind: NotRequired[Literal["flight", "hotel", "car", "train", "cruise"]]
    status: NotRequired[Literal["confirmed", "changed", "cancelled"]]
    confirmation: NotRequired[str | None]
    provider: NotRequired[str | None]
    start_local: NotRequired[str]
    start_zone: NotRequired[str | None]
    end_local: NotRequired[str]
    end_zone: NotRequired[str | None]
    origin: NotRequired[str | None]
    destination: NotRequired[str | None]
    details: NotRequired[dict[str, str]]
    manage_url: NotRequired[str | None]
    travelers: NotRequired[list[TravelerBody]]   # replaces who it's for
    itinerary: NotRequired[list[Port]]           # replaces a cruise's ports of call


class Airport(TypedDict):
    code: str
    name: str
    city: str
    country: str
    zone: str                       # IANA


# Importing past flights from another app's CSV export

class ImportRow(TypedDict):
    """One row of the uploaded file as a flight, for the preview: new, already in Waypoint, or one that can't be read (with
    why). Times are local wall-clock times at the airports; both are null when the file gave none."""
    line: int                       # the row's line in the file (the header is line 1)
    status: Literal["new", "exists", "unreadable"]
    reason: str | None
    day: str | None                 # the local departure day, YYYY-MM-DD
    origin: str | None              # airport codes
    destination: str | None
    flight_number: str | None
    airline: str | None
    start_local: str | None
    end_local: str | None
    seat: str | None
    cabin: str | None


class ImportPreview(TypedDict):
    format: str                     # which app's export it is, from its header row
    me: int | None                  # the person the sign-in belongs to (who the flights are for unless chosen otherwise)
    rows: list[ImportRow]


class ImportFlight(TypedDict):
    """A flight to save, as the preview showed it: the web app sends back only the rows being saved, never the file."""
    day: str
    origin: str
    destination: str
    flight_number: NotRequired[str | None]
    airline: NotRequired[str | None]
    start_local: NotRequired[str | None]
    end_local: NotRequired[str | None]
    seat: NotRequired[str | None]
    cabin: NotRequired[str | None]


class ImportBody(TypedDict):
    flights: list[ImportFlight]     # at most 1,000 at a time
    person_ids: NotRequired[list[int]]   # who was on these flights; the signed-in member when left out


class Imported(TypedDict):
    added: int
    existing: int                   # already in Waypoint, so left alone


# Live flight status

class FlightStatus(TypedDict):
    """A flight's live status, shown beside its booked times (the booking is never changed). Times are `2026-03-01T22:15`
    wall-clock times at the airports, in their zones (`dep_zone`, `arr_zone`), never converted."""
    segment_id: int
    state: Literal["scheduled", "delayed", "departed", "landed", "cancelled", "diverted"]
    origin: str | None              # airport codes, as the service names them
    destination: str | None
    dep_scheduled: str | None
    dep_estimated: str | None
    dep_actual: str | None
    dep_zone: str
    dep_terminal: str | None
    dep_gate: str | None
    arr_scheduled: str | None
    arr_estimated: str | None
    arr_actual: str | None
    arr_zone: str
    arr_terminal: str | None
    arr_gate: str | None
    delay_minutes: int | None       # how much later than booked it leaves (or left)
    fetched_at: str                 # when the answer came, with its UTC offset


class FlightStatusPause(TypedDict):
    until: str                      # with its UTC offset
    reason: Literal["limit", "rate", "key"]   # the monthly limit (until the 1st), a rate limit, or a key RapidAPI refused (an hour)


class FlightStatusList(TypedDict):
    enabled: bool                   # RAPIDAPI_KEY is set; without it there's nothing to show
    month: str                      # YYYY-MM, local time: the month `used` counts
    used: int                       # calls made this month, for the whole household
    limit: int                      # WAYPOINT_FLIGHT_STATUS_MONTHLY_LIMIT
    paused: FlightStatusPause | None   # why nothing is fetched now
    statuses: list[FlightStatus]    # one for each of the viewer's flight segments that has one


# Loyalty and Known Traveler numbers

class LoyaltyEntry(TypedDict):
    """One membership. The number comes only masked (its last four characters); `POST /api/loyalty/{id}/reveal` gives it."""
    id: int
    person_id: int
    kind: str                       # airline, hotel, car, known_traveler or redress
    program: str                    # one of `programs` for the kind
    masked: str
    readable: bool                  # false when Waypoint's key can't unlock the number (it has to be entered again)
    tier: str | None
    expiry: str | None              # YYYY-MM-DD
    notes: str | None


class LoyaltyConflict(TypedDict):
    """A person with two different numbers for one program (both are kept); People says so."""
    person_id: int
    kind: str
    program: str


class LoyaltyList(TypedDict):
    loyalty: list[LoyaltyEntry]
    conflicts: list[LoyaltyConflict]
    programs: dict[str, list[str]]  # the programs to choose from, by kind


class LoyaltyBody(TypedDict):
    """A membership, to save or to change. `number` is needed to save one; left out when changing, the saved one is kept."""
    person_id: int
    kind: str
    program: str
    number: NotRequired[str | None]
    tier: NotRequired[str | None]
    expiry: NotRequired[str | None]
    notes: NotRequired[str | None]


class Revealed(TypedDict):
    number: str


# Travel stats

class StatsNamed(TypedDict):
    name: str
    count: int


class StatsPlace(TypedDict):
    name: str                       # a country's ISO code or a city's name
    first_visit: str                # the local date, YYYY-MM-DD
    visits: int


class StatsAirport(TypedDict):
    code: str
    name: str                       # the code, for an airport that isn't in the table
    city: str | None
    country: str | None
    visits: int                     # each departure from it and arrival at it
    latitude: float | None          # for the map; none for an airport that isn't in the table
    longitude: float | None


class StatsAirline(TypedDict):
    code: str | None
    name: str                       # the code, for an airline that isn't in the table
    flights: int


class StatsRoute(TypedDict):
    a: str                          # A–B and B–A are one route
    b: str
    flights: int
    distance_km: float | None
    a_latitude: float | None
    a_longitude: float | None
    b_latitude: float | None
    b_longitude: float | None


class StatsFlightRecord(TypedDict):
    origin: str
    destination: str
    distance_km: float
    start_local: str
    flight_number: str | None


class StatsSeats(TypedDict):
    window: int
    aisle: int
    middle: int
    unknown: int


class StatsFlights(TypedDict):
    count: int
    distance_km: float
    air_seconds: int                # booked departure to booked arrival, each at its own zone
    airports: list[StatsAirport]    # most visited first
    airlines: list[StatsAirline]
    countries: list[StatsNamed]     # of the airports, by ISO code
    routes: list[StatsRoute]        # most flown first
    cabins: list[StatsNamed]
    top_seat: str | None
    seat_positions: StatsSeats
    longest: StatsFlightRecord | None
    shortest: StatsFlightRecord | None
    most_visited_airport: str | None
    busiest_month: str | None       # YYYY-MM
    times_around_earth: float       # of 40,075 km
    moon_fraction: float            # of the way to the Moon, 384,400 km


class StatsStayPlace(TypedDict):
    name: str                       # a hotel or a city, as first written
    stays: int
    nights: int


class StatsStayRecord(TypedDict):
    hotel: str | None
    city: str | None
    nights: int
    start_local: str                # check-in, local


class StatsStays(TypedDict):
    nights: int
    chains: list[StatsNamed]
    cities: list[StatsNamed]
    countries: list[StatsNamed]
    count: int                      # stays with at least one night
    average_nights: float           # nights per stay, to a tenth
    hotels: list[StatsStayPlace]    # by nights
    cities_by_nights: list[StatsStayPlace]
    longest: StatsStayRecord | None
    most_visited_hotel: StatsStayPlace | None
    most_visited_city: StatsStayPlace | None
    busiest_month: str | None       # YYYY-MM, the month with the most nights away


class StatsCars(TypedDict):
    days: int
    companies: list[StatsNamed]


class StatsCruises(TypedDict):
    count: int
    nights: int                     # nights aboard
    sea_days: int                   # days between embarking and disembarking with no port of call
    ports: int                      # different ports of call
    lines: list[StatsNamed]


class StatsPlaces(TypedDict):
    countries: list[StatsPlace]
    cities: list[StatsPlace]


class DistanceUnit(TypedDict):
    distance_unit: Literal["mi", "km"]   # how the Stats page shows distances (the household's setting)


class DistanceUnitBody(TypedDict):
    distance_unit: Literal["mi", "km"]


class Stats(TypedDict):
    years: list[int]                # the years with something finished, newest first, whatever year was asked about
    person: int | None              # whose; none: the household
    year: int | None                # none: lifetime
    distance_unit: Literal["mi", "km"]   # the household's setting; every distance above is kilometres
    flights: StatsFlights
    stays: StatsStays
    cars: StatsCars
    cruises: StatsCruises
    places: StatsPlaces


# Reminders and the calendar feed

class ReminderDevice(TypedDict):
    """A browser or phone that gets this member's notifications."""
    id: int
    service: str                    # the push service's host, to tell devices apart
    created: float                  # seconds since the epoch


class Reminders(TypedDict):
    """The signed-in member's own: which reminders they get, their devices, and whether they have a calendar feed."""
    public_key: str                 # this server's key, for a browser to subscribe with
    check_in: bool                  # "Check-in opens", 24 hours before a flight
    day_of: bool                    # the summary of the day's bookings, from 7:00 on the machine's clock
    devices: list[ReminderDevice]
    feed: bool                      # a calendar feed is on (its address was shown once, when it was made)


class RemindersBody(TypedDict):
    check_in: bool
    day_of: bool


class DeviceBody(TypedDict):
    """A browser's push subscription (`PushSubscription.toJSON()`)."""
    endpoint: str
    p256dh: str
    auth: str


class FeedMade(TypedDict):
    url: str                        # the feed's address, with its key: shown once, and not kept anywhere in Waypoint


# AI assistants (MCP)

class McpConnection(TypedDict):
    """An assistant connected with OAuth: one approval, ended by Disconnect or when its approver can no longer sign in."""
    id: int
    client: str | None              # the app's name, as it registered
    who: str | None                 # the member who approved it: it sees what they see
    scope: list[str]                # read, and write when they allowed changes
    created: str | None             # with its UTC offset
    last_used: str | None


class McpSettings(TypedDict):
    allow_writes: bool              # "Let assistants change trips"
    oauth: bool                     # assistants can connect (the address is one OAuth can use)
    url: str | None                 # what to add to the assistant; none when `oauth` is false
    reason: str | None              # why not
    connections: list[McpConnection]


class McpWritesBody(TypedDict):
    allow: bool
