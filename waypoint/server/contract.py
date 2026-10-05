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


class MailboxList(TypedDict):
    configured: bool                # GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are set
    mailboxes: list[Mailbox]        # the signed-in member's own


class Started(TypedDict):
    url: str                        # Google's consent screen, to send the browser to


class ScanStarted(TypedDict):
    started: bool                   # false when a scan of this mailbox was already running


class Disconnected(TypedDict):
    ok: bool
    revoked: bool                   # false when Waypoint couldn't unlock the saved token to revoke it: remove it at Google


# Review: mail that looked like a booking and couldn't be read, and names on bookings to match to people

class ReviewItem(TypedDict):
    """One message Waypoint couldn't read, for the member whose mailbox it is. Never its text: who it came from, its
    subject and its day."""
    id: int
    address: str                    # the mailbox it came from
    sender_domain: str              # empty when the message didn't say
    subject: str | None             # null when Waypoint can't unlock it any more (its key changed)
    received: str | None            # a day, YYYY-MM-DD
    reason: Literal["no_markup", "incomplete", "broken"]   # no booking details in it; some missing; couldn't be opened
    gmail_url: str                  # opens the message in Gmail


class WhoIsThis(TypedDict):
    """A name on a booking that isn't matched to a person, with the segment it's on."""
    id: int                         # the traveller to match
    name: str                       # as printed on the booking
    segment_id: int
    trip_id: int
    kind: Literal["flight", "hotel", "car", "train"]
    provider: str | None
    origin: str | None
    destination: str | None
    start_local: str
    start_zone: str


class Review(TypedDict):
    items: list[ReviewItem]
    who: list[WhoIsThis]


class WhoBody(TypedDict):
    """Who a printed name is: a person in People, or a name to add as a guest. Send one."""
    person_id: NotRequired[int]
    new_guest: NotRequired[str]


class Matched(TypedDict):
    ok: bool
    matched: int                    # how many travellers on bookings became that person (the same printed name is matched everywhere)


# People

class Person(TypedDict):
    """Someone who travels: a household member (`member`, linked to their sign-in) or a guest with no login."""
    id: int
    display_name: str
    first_name: str | None
    legal_name: str | None         # as on an ID
    aliases: list[str]             # how airlines print the name ("DOE/JANE MS")
    member: bool


class People(TypedDict):
    people: list[Person]            # members first, then guests


class PersonBody(TypedDict):
    """A person's names, to add a guest or to change anyone's (a member's link to their login can't be changed)."""
    display_name: str
    first_name: NotRequired[str | None]
    legal_name: NotRequired[str | None]
    aliases: NotRequired[list[str]]


# Trips and segments

class Traveler(TypedDict):
    id: int
    person_id: int | None           # null until the printed name is matched to a person
    name: str                       # the person's name, or the name as printed on the booking


class Segment(TypedDict):
    """One flight leg, hotel stay, car rental or train. Its times are local wall-clock times at the place, never
    converted: `start_local` is 2026-03-01T22:15 in `start_zone`, whatever zone the server or the viewer is in."""
    id: int
    trip_id: int
    kind: Literal["flight", "hotel", "car", "train"]
    status: Literal["confirmed", "changed", "cancelled"]
    confirmation: str | None
    provider: str | None
    start_local: str                # a hotel's check-in, a car's pick-up, a flight's departure
    start_zone: str                 # the IANA zone of the place it starts (Pacific/Auckland)
    end_local: str
    end_zone: str
    origin: str | None              # a flight's airport code; a stay's or a rental's place
    destination: str | None
    details: dict[str, str]         # flight_number, terminal, seat, cabin, room, car_class, address, phone
    manage_url: str | None
    source: Literal["manual", "email"]
    booked_by: int | None           # a person
    locked_fields: list[str]        # what a person edited, which a later email never overwrites
    travelers: list[Traveler]


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


class SegmentBody(TypedDict):
    """A segment to add; `trip_id` leaves it to Waypoint to group it into a trip. A flight's zones come from its airports
    unless given."""
    kind: Literal["flight", "hotel", "car", "train"]
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


class SegmentEdit(TypedDict):
    """What to change on a segment: only the fields sent. The ones that end up different are locked."""
    kind: NotRequired[Literal["flight", "hotel", "car", "train"]]
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


class Airport(TypedDict):
    code: str
    name: str
    city: str
    country: str
    zone: str                       # IANA


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


class LoyaltyList(TypedDict):
    loyalty: list[LoyaltyEntry]
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
