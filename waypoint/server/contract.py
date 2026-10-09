from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


class Ok(TypedDict):
    ok: bool


class SignedIn(TypedDict):
    name: str | None
    email: str | None
    sub: NotRequired[str]
    local: NotRequired[bool]


class State(TypedDict):
    version: str
    database: Literal["sqlite", "postgres"]
    user: SignedIn | None
    last_backup: str | None
    review_count: int
    person_id: int | None


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


class Mailbox(TypedDict):
    id: int
    address: str
    status: Literal["connected", "reconnect", "error"]
    last_error: str | None
    last_scan: str | None
    scan_error: str | None
    scanning: bool
    scan_notice: str | None
    share_review: bool


class MailboxList(TypedDict):
    configured: bool
    mailboxes: list[Mailbox]


class ShareBody(TypedDict):
    share: bool


class Started(TypedDict):
    url: str


class ScanStarted(TypedDict):
    started: bool


class Disconnected(TypedDict):
    ok: bool
    revoked: bool


class AiSuggestion(TypedDict):
    kind: Literal["flight", "hotel", "car", "train", "cruise"]
    origin: str
    start_local: str
    end_local: str
    provider: NotRequired[str]
    confirmation: NotRequired[str]
    destination: NotRequired[str]
    start_zone: NotRequired[str]
    end_zone: NotRequired[str]


class ReviewItem(TypedDict):
    id: int
    address: str
    owner: str
    mine: bool
    sender_domain: str
    subject: str | None
    has_email: bool
    received: str | None
    reason: Literal["no_markup", "incomplete", "broken"]
    gmail_url: str | None
    suggestion: AiSuggestion | None
    suggestion_error: str | None


class WhoIsThis(TypedDict):
    id: int
    name: str
    segment_id: int
    trip_id: int
    kind: Literal["flight", "hotel", "car", "train", "cruise"]
    provider: str | None
    origin: str | None
    destination: str | None
    start_local: str
    start_zone: str


class ReviewBooking(TypedDict):
    kind: Literal["flight", "hotel", "car", "train", "cruise"]
    provider: str | None
    confirmation: str | None
    origin: str | None
    destination: str | None
    start_local: str
    end_local: str


class ReviewCandidate(TypedDict):
    segment_id: int
    trip_id: int
    trip_name: str
    kind: Literal["flight", "hotel", "car", "train", "cruise"]
    provider: str | None
    origin: str | None
    destination: str | None
    start_local: str
    end_local: str


class ReviewMatch(TypedDict):
    item_id: int
    entry: int
    subject: str | None
    received: str | None
    mine: bool
    booking: ReviewBooking
    candidates: list[ReviewCandidate]


class MatchBody(TypedDict):
    entry: int
    segment_id: int | None


class Review(TypedDict):
    items: list[ReviewItem]
    matches: list[ReviewMatch]
    who: list[WhoIsThis]
    ai: bool


class Preview(TypedDict):
    subject: str | None
    text: str
    html: str | None
    truncated: bool


class StoredEmail(TypedDict):
    subject: str | None
    sender_domain: str | None
    received: str | None
    text: str
    html: str | None
    truncated: bool


class SegmentEmails(TypedDict):
    emails: list[StoredEmail]


class OfflineMessages(TypedDict):
    segment_id: int
    emails: list[StoredEmail]


class Offline(TypedDict):
    trip: Trip | None
    messages: list[OfflineMessages]


class WhoBody(TypedDict):
    person_id: NotRequired[int]
    new_guest: NotRequired[str]


class Matched(TypedDict):
    ok: bool
    matched: int


class AiSettings(TypedDict):
    mode: Literal["off", "local", "openrouter"]
    ollama_url: str
    ollama_model: str
    openrouter_model: str
    key: Literal["env", "saved"] | None


class LogoDevStatus(TypedDict):
    configured: bool
    searchable: bool
    with_logo: int
    unknown: int
    waiting: int
    last_error: str | None


class LogoDevFetch(TypedDict):
    started: bool


class LogoDevBody(TypedDict):
    token: NotRequired[str]
    secret: NotRequired[str]
    clear: NotRequired[bool]
    clear_secret: NotRequired[bool]


class AiBody(TypedDict):
    mode: Literal["off", "local", "openrouter"]
    ollama_url: NotRequired[str]
    ollama_model: NotRequired[str]
    openrouter_model: NotRequired[str]
    openrouter_key: NotRequired[str]


class Person(TypedDict):
    id: int
    display_name: str
    first_name: str | None
    legal_name: str | None
    aliases: list[str]
    member: bool
    links: list[PersonLink]


class PersonLink(TypedDict):
    guest: str
    by: str
    on: str


class People(TypedDict):
    people: list[Person]


class ClaimSuggestions(TypedDict):
    guests: list[Person]


class PersonBody(TypedDict):
    display_name: str
    first_name: NotRequired[str | None]
    legal_name: NotRequired[str | None]
    aliases: NotRequired[list[str]]


class Traveler(TypedDict):
    id: int
    person_id: int | None
    name: str
    seat: str | None


class SegmentLinks(TypedDict):
    app: str | None
    directions: str | None
    call: str | None


class Port(TypedDict):
    name: str
    zone: str
    arrive_local: str | None
    depart_local: str | None


class CruiseStop(TypedDict):
    name: str
    zone: str
    arrive_local: str | None
    depart_local: str | None
    recorded: bool


class CruiseDay(TypedDict):
    day: int
    date: str
    sea: bool
    stops: list[CruiseStop]


class Segment(TypedDict):
    id: int
    trip_id: int
    kind: Literal["flight", "hotel", "car", "train", "cruise"]
    status: Literal["confirmed", "changed", "cancelled"]
    confirmation: str | None
    provider: str | None
    start_local: str
    start_zone: str
    end_local: str
    end_zone: str
    origin: str | None
    destination: str | None
    details: dict[str, str]
    manage_url: str | None
    source: Literal["manual", "email", "import"]
    booked_by: int | None
    locked_fields: list[str]
    check_times: bool
    travelers: list[Traveler]
    itinerary: list[Port]
    days: list[CruiseDay]
    logo: str | None
    logo_label: str | None
    has_email: bool
    links: SegmentLinks


class Trip(TypedDict):
    id: int
    name: str
    start_date: str | None
    end_date: str | None
    destination: str | None
    notes: str | None
    auto: bool
    booked_by: int | None
    segments: list[Segment]


class TripList(TypedDict):
    trips: list[Trip]


class TripBody(TypedDict):
    name: NotRequired[str]
    destination: NotRequired[str | None]
    notes: NotRequired[str | None]
    start_date: NotRequired[str | None]
    end_date: NotRequired[str | None]


class MergeBody(TypedDict):
    merge: int


class SplitBody(TypedDict):
    segment_ids: list[int]


class TravelerBody(TypedDict):
    person_id: NotRequired[int | None]
    name: NotRequired[str | None]
    seat: NotRequired[str | None]


class SegmentBody(TypedDict):
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
    travelers: NotRequired[list[TravelerBody]]
    itinerary: NotRequired[list[Port]]


class SegmentEdit(TypedDict):
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
    travelers: NotRequired[list[TravelerBody]]
    itinerary: NotRequired[list[Port]]


class Airport(TypedDict):
    code: str
    name: str
    city: str
    country: str
    zone: str


class ImportRow(TypedDict):
    line: int
    status: Literal["new", "exists", "unreadable"]
    reason: str | None
    day: str | None
    origin: str | None
    destination: str | None
    flight_number: str | None
    airline: str | None
    start_local: str | None
    end_local: str | None
    seat: str | None
    cabin: str | None
    aircraft: str | None


class ImportPreview(TypedDict):
    format: str
    me: int | None
    rows: list[ImportRow]


class ImportFlight(TypedDict):
    day: str
    origin: str
    destination: str
    flight_number: NotRequired[str | None]
    airline: NotRequired[str | None]
    start_local: NotRequired[str | None]
    end_local: NotRequired[str | None]
    seat: NotRequired[str | None]
    cabin: NotRequired[str | None]
    aircraft: NotRequired[str | None]


class ImportBody(TypedDict):
    flights: list[ImportFlight]
    person_ids: NotRequired[list[int]]


class Imported(TypedDict):
    added: int
    existing: int


class FlightStatus(TypedDict):
    segment_id: int
    state: Literal["scheduled", "delayed", "departed", "landed", "cancelled", "diverted"]
    origin: str | None
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
    delay_minutes: int | None
    fetched_at: str


class FlightStatusPause(TypedDict):
    until: str
    reason: Literal["limit", "rate", "key"]


class FlightStatusList(TypedDict):
    enabled: bool
    month: str
    used: int
    limit: int
    paused: FlightStatusPause | None
    statuses: list[FlightStatus]


class LoyaltyEntry(TypedDict):
    id: int
    person_id: int
    kind: str
    program: str
    masked: str
    readable: bool
    expiry: str | None
    notes: str | None


class LoyaltyConflict(TypedDict):
    person_id: int
    kind: str
    program: str


class LoyaltyList(TypedDict):
    loyalty: list[LoyaltyEntry]
    conflicts: list[LoyaltyConflict]
    programs: dict[str, list[str]]


class LoyaltyBody(TypedDict):
    person_id: int
    kind: str
    program: str
    number: NotRequired[str | None]
    expiry: NotRequired[str | None]
    notes: NotRequired[str | None]


class Revealed(TypedDict):
    number: str


class StatsNamed(TypedDict):
    name: str
    count: int


class StatsPlace(TypedDict):
    name: str
    first_visit: str
    visits: int


class StatsAirport(TypedDict):
    code: str
    name: str
    city: str | None
    country: str | None
    visits: int
    latitude: float | None
    longitude: float | None


class StatsAirline(TypedDict):
    code: str | None
    name: str
    flights: int


class StatsMapTrip(TypedDict):
    trip_id: int
    name: str
    start: str
    end: str


class StatsRoute(TypedDict):
    a: str
    b: str
    flights: int
    distance_km: float | None
    a_latitude: float | None
    a_longitude: float | None
    b_latitude: float | None
    b_longitude: float | None
    trips: list[StatsMapTrip]


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
    air_seconds: int
    airports: list[StatsAirport]
    airlines: list[StatsAirline]
    countries: list[StatsNamed]
    routes: list[StatsRoute]
    cabins: list[StatsNamed]
    top_seat: str | None
    seat_positions: StatsSeats
    longest: StatsFlightRecord | None
    shortest: StatsFlightRecord | None
    most_visited_airport: str | None
    busiest_month: str | None
    times_around_earth: float
    moon_fraction: float


class StatsStayPlace(TypedDict):
    name: str
    stays: int
    nights: int


class StatsStayRecord(TypedDict):
    hotel: str | None
    city: str | None
    nights: int
    start_local: str


class StatsStayPin(TypedDict):
    city: str
    country: str | None
    latitude: float
    longitude: float
    stays: int
    nights: int
    trips: list[StatsMapTrip]


class StatsStays(TypedDict):
    nights: int
    chains: list[StatsNamed]
    cities: list[StatsNamed]
    countries: list[StatsNamed]
    count: int
    average_nights: float
    hotels: list[StatsStayPlace]
    cities_by_nights: list[StatsStayPlace]
    longest: StatsStayRecord | None
    most_visited_hotel: StatsStayPlace | None
    most_visited_city: StatsStayPlace | None
    busiest_month: str | None
    pins: list[StatsStayPin]


class StatsCars(TypedDict):
    days: int
    companies: list[StatsNamed]


class StatsCruises(TypedDict):
    count: int
    nights: int
    sea_days: int
    ports: int
    lines: list[StatsNamed]


class StatsPlaces(TypedDict):
    countries: list[StatsPlace]
    cities: list[StatsPlace]


class DistanceUnit(TypedDict):
    distance_unit: Literal["mi", "km"]


class DistanceUnitBody(TypedDict):
    distance_unit: Literal["mi", "km"]


class Stats(TypedDict):
    years: list[int]
    person: int | None
    year: int | None
    distance_unit: Literal["mi", "km"]
    flights: StatsFlights
    stays: StatsStays
    cars: StatsCars
    cruises: StatsCruises
    places: StatsPlaces


class ReminderDevice(TypedDict):
    id: int
    service: str
    created: float


class Reminders(TypedDict):
    public_key: str
    check_in: bool
    day_of: bool
    devices: list[ReminderDevice]
    feed: bool


class RemindersBody(TypedDict):
    check_in: bool
    day_of: bool


class DeviceBody(TypedDict):
    endpoint: str
    p256dh: str
    auth: str


class FeedMade(TypedDict):
    url: str


class McpConnection(TypedDict):
    id: int
    client: str | None
    who: str | None
    scope: list[str]
    created: str | None
    last_used: str | None


class McpSettings(TypedDict):
    allow_writes: bool
    oauth: bool
    url: str | None
    reason: str | None
    connections: list[McpConnection]


class McpWritesBody(TypedDict):
    allow: bool
