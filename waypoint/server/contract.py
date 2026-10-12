from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


class EmailsCleared(TypedDict):
    removed: int


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
    ai: bool


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


class ScanSummary(TypedDict):
    found: int
    read: int
    bookings: int
    review: int
    skipped: int
    capped: bool
    labels_dropped: int
    triaged: int
    total: int
    not_travel: int
    followups: int
    with_facts: int
    attached: int
    ai_asked: int


class Mailbox(TypedDict):
    id: int
    address: str
    status: Literal["connected", "reconnect", "error"]
    last_error: str | None
    last_scan: str | None
    scan_error: str | None
    scanning: bool
    scan_notice: str | None
    scan_summary: ScanSummary | None
    reading_again: str | None
    labels_picked: int
    share_review: bool


class MailboxList(TypedDict):
    configured: bool
    mailboxes: list[Mailbox]


class MailboxLabel(TypedDict):
    id: str
    name: str
    count: int
    picked: bool


class MailboxLabels(TypedDict):
    labels: list[MailboxLabel]


class LabelsBody(TypedDict):
    labels: list[str]


class IgnoredSenders(TypedDict):
    domains: list[str]


class GlanceReason(TypedDict):
    reason: Literal["no_markup", "incomplete", "broken", "match", "generic"]
    waiting: int
    recent: int


class GlanceGap(TypedDict):
    label: str
    count: int


class GlanceDomain(TypedDict):
    domain: str
    count: int
    reason: Literal["no_markup", "incomplete", "broken", "match", "generic"]
    item_id: int | None
    known_sender: bool


class GlanceScan(TypedDict):
    at: str
    added: int


class ReviewGlance(TypedDict):
    waiting: int
    days: int
    reasons: list[GlanceReason]
    gaps: list[GlanceGap]
    domains: list[GlanceDomain]
    scans: list[GlanceScan]


class UnignoreBody(TypedDict):
    domain: str


class Ignoring(TypedDict):
    ok: bool
    mailbox_id: int
    domain: str


class ShareBody(TypedDict):
    share: bool


class Started(TypedDict):
    url: str


class ScanStarted(TypedDict):
    started: bool


class Disconnected(TypedDict):
    ok: bool
    revoked: bool


class AiTraveler(TypedDict):
    name: str
    seat: str


class AiSuggestion(TypedDict):
    kind: Literal["flight", "hotel", "car", "train", "cruise", "parking"]
    origin: str
    start_local: str
    end_local: str
    provider: NotRequired[str]
    confirmation: NotRequired[str]
    destination: NotRequired[str]
    start_zone: NotRequired[str]
    end_zone: NotRequired[str]
    address: NotRequired[str]
    phone: NotRequired[str]
    room: NotRequired[str]
    ship: NotRequired[str]
    deck: NotRequired[str]
    flight_number: NotRequired[str]
    cabin: NotRequired[str]
    travelers: NotRequired[list[AiTraveler]]
    price_minor: NotRequired[int]
    price_currency: NotRequired[str]
    sources: NotRequired[dict[str, str]]


class ReviewOther(TypedDict):
    id: int
    subject: str | None
    has_email: bool
    received: str | None


class ReviewItem(TypedDict):
    id: int
    address: str
    owner: str
    mine: bool
    sender_domain: str
    known_sender: bool
    holds_bookings: bool
    subject: str | None
    has_email: bool
    received: str | None
    reason: Literal["no_markup", "incomplete", "broken", "generic"]
    suggestions: list[AiSuggestion]
    suggestion_error: str | None
    auto_read: bool
    count: int
    others: list[ReviewOther]


class WhoIsThis(TypedDict):
    id: int
    name: str
    segment_id: int
    trip_id: int
    kind: Literal["flight", "hotel", "car", "train", "cruise", "parking", "visit"]
    provider: str | None
    origin: str | None
    destination: str | None
    start_local: str
    start_zone: str


class ReviewBooking(TypedDict):
    kind: Literal["flight", "hotel", "car", "train", "cruise", "parking"]
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
    kind: Literal["flight", "hotel", "car", "train", "cruise", "parking"]
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


class SameBooking(TypedDict):
    booking: ReviewCandidate | None


class Attached(TypedDict):
    ok: bool
    segment_id: int


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
    original: bool
    images: int


class StoredEmail(TypedDict):
    subject: str | None
    sender_domain: str | None
    received: str | None
    text: str
    html: str | None
    truncated: bool
    original: bool
    images: int


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
    auto: bool


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
    auto: NotRequired[bool]


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
    open: str | None
    open_kind: Literal["app", "website"] | None
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


class Price(TypedDict):
    amount_minor: int
    currency: str
    source: Literal["email", "manual"]


class PriceBody(TypedDict):
    amount_minor: int
    currency: str


class CostTotal(TypedDict):
    currency: str
    amount_minor: int


class TripCosts(TypedDict):
    totals: list[CostTotal]
    priced: int
    bookings: int


class GateCode(TypedDict):
    state: Literal["ready", "choose"]
    day: str | None


class GateCodeBody(TypedDict):
    email: int
    image: int


class Segment(TypedDict):
    id: int
    trip_id: int
    kind: Literal["flight", "hotel", "car", "train", "cruise", "parking", "visit"]
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
    hotel_brand: str | None
    has_email: bool
    gate_code: GateCode | None
    price: Price | None
    links: SegmentLinks


class Trip(TypedDict):
    id: int
    name: str
    start_date: str | None
    end_date: str | None
    destination: str | None
    destination_manual: bool
    notes: str | None
    auto: bool
    booked_by: int | None
    emails: int
    can_clear_emails: bool
    done_at: float | None
    people: list[int]
    costs: TripCosts
    segments: list[Segment]


class TripList(TypedDict):
    trips: list[Trip]


class TripAirportPoint(TypedDict):
    code: str
    city: str
    latitude: float
    longitude: float


class TripCityPoint(TypedDict):
    city: str
    latitude: float
    longitude: float


class TripStayPoint(TypedDict):
    segment_id: int
    latitude: float
    longitude: float
    precision: Literal["airport", "zip", "city"]


class TripRoadLeg(TypedDict):
    from_segment_id: int
    to_segment_id: int
    refs: list[str]
    points: list[list[float]]


class TripRoadLine(TypedDict):
    ref: str
    points: list[list[float]]


class TripRoads(TypedDict):
    legs: list[TripRoadLeg]
    interstates: list[TripRoadLine]


class TripStateLine(TypedDict):
    points: list[list[float]]


class TripHome(TypedDict):
    city: str
    latitude: float
    longitude: float


class TripPlaces(TypedDict):
    home: TripHome | None
    airports: list[TripAirportPoint]
    cities: list[TripCityPoint]
    stays: list[TripStayPoint]
    roads: TripRoads
    boundaries: list[TripStateLine]


class TripBody(TypedDict):
    name: NotRequired[str]
    destination: NotRequired[str | None]
    notes: NotRequired[str | None]
    start_date: NotRequired[str | None]
    end_date: NotRequired[str | None]
    people: NotRequired[list[int]]
    confirm: NotRequired[bool]


class DestinationSuggestion(TypedDict):
    suggestion: str


class MergeBody(TypedDict):
    merge: int
    confirm: NotRequired[bool]


class MoveBody(TypedDict):
    trip_id: int | None
    confirm: NotRequired[bool]


class SplitBody(TypedDict):
    segment_ids: list[int]


class TravelerBody(TypedDict):
    person_id: NotRequired[int | None]
    name: NotRequired[str | None]
    seat: NotRequired[str | None]


class SegmentBody(TypedDict):
    kind: Literal["flight", "hotel", "car", "train", "cruise", "parking", "visit"]
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
    price: NotRequired[PriceBody | None]


class SegmentEdit(TypedDict):
    kind: NotRequired[Literal["flight", "hotel", "car", "train", "cruise", "parking", "visit"]]
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
    price: NotRequired[PriceBody | None]


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
    logo: str | None


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


class StatsParking(TypedDict):
    days: int
    bookings: int
    lots: list[StatsNamed]


class StatsVisit(TypedDict):
    country: str
    state: str | None
    latitude: float
    longitude: float
    trips: list[StatsMapTrip]


class StatsPlacePoint(TypedDict):
    name: str
    kind: str
    latitude: float
    longitude: float
    trips: list[StatsMapTrip]


class StatsPlaces(TypedDict):
    countries: list[StatsPlace]
    cities: list[StatsPlace]
    visits: list[StatsVisit]
    points: list[StatsPlacePoint]


class DistanceUnit(TypedDict):
    distance_unit: Literal["mi", "km"]


class DistanceUnitBody(TypedDict):
    distance_unit: Literal["mi", "km"]


class Home(TypedDict):
    city: str
    state: str
    zip: str
    country: str
    saved: bool
    placed: bool


class HomeBody(TypedDict):
    city: str
    state: NotRequired[str]
    zip: NotRequired[str]
    country: NotRequired[str]


class Stats(TypedDict):
    years: list[int]
    person: int | None
    year: int | None
    distance_unit: Literal["mi", "km"]
    flights: StatsFlights
    stays: StatsStays
    cars: StatsCars
    cruises: StatsCruises
    parking: StatsParking
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


class McpMailBody(TypedDict):
    allow: bool


class McpSettings(TypedDict):
    allow_writes: bool
    oauth: bool
    url: str | None
    reason: str | None
    connections: list[McpConnection]


class McpWritesBody(TypedDict):
    allow: bool


class AssistantMatch(TypedDict):
    segment_id: int
    trip_id: int
    confidence: Literal["exact", "likely", "possible"]


class AssistantItem(TypedDict):
    id: int
    mailbox_id: int
    mine: bool
    sender_domain: str
    reason: Literal["no_markup", "incomplete", "broken", "match", "generic"]
    status: str | None
    kind: str | None
    received: str | None
    has_email: bool
    bookings: int
    match: AssistantMatch | None


class AssistantItems(TypedDict):
    items: list[AssistantItem]
    total: int
    not_shown: int
    next: str | None


class AssistantParsed(TypedDict):
    kind: str | None
    status: str | None
    provider: str | None
    confirmation: str | None
    origin: str | None
    destination: str | None
    address: str | None
    phone: str | None
    start_local: str | None
    start_zone: str | None
    end_local: str | None
    end_zone: str | None
    details: dict[str, str]
    travelers: list[str]
    read: dict[str, str]


class AssistantCandidate(TypedDict):
    segment_id: int
    trip_id: int
    trip_name: str
    kind: str
    provider: str | None
    origin: str | None
    destination: str | None
    start_local: str
    end_local: str
    confidence: Literal["exact", "likely", "possible"]
    agreed: list[str]
    differed: list[str]


class AssistantEntry(TypedDict):
    entry: int
    booking: AssistantParsed
    candidates: list[AssistantCandidate]


class AssistantItemDetail(AssistantItem):
    entries: list[AssistantEntry]
    suggestion: AssistantParsed | None
    suggestions: list[AssistantParsed]


class AssistantEmail(TypedDict):
    subject: str | None
    sender_domain: str | None
    received: str | None
    text: str
    truncated: bool
    html: str | None
    html_truncated: bool
    kept: Literal["original", "plain text"]


class AssistantSegmentEmails(TypedDict):
    emails: list[AssistantEmail]


class AssistantMatchBody(TypedDict):
    entry: NotRequired[int | None]
    segment_id: NotRequired[int | None]
    trip_id: NotRequired[int | None]


class AssistantCreateBody(SegmentEdit):
    entry: NotRequired[int | None]


class AssistantDismissBody(TypedDict):
    reason: Literal["not_travel", "duplicate", "already_added", "other"]
    note: NotRequired[str | None]


class AssistantDismissed(TypedDict):
    ok: bool
    reason: Literal["not_travel", "duplicate", "already_added", "other"]


class AssistantMatched(TypedDict):
    ok: bool
    segment_id: int
    trip_id: int
