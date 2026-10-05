"""ORM models: one class per table in waypoint/storage/schema.py.

schema.py stays the one source of truth for the schema (Alembic compares the database with it): each model maps
onto its `Table` (`__table__ = schema.x`), so there's nothing here to migrate. The `Mapped[...]` annotations are for
readers and type checkers; they must match schema.py (tests/test_models.py checks).

Use the classes' attributes in SQLAlchemy statements (`select(User.sub, User.email).where(...)`, run with
`conn.execute(...)`), or load objects through the connection's ORM session (`conn.orm.get(User, sub)`).
docs/src/content/docs/contributing/orm.md has the conventions.

Relationships: each one spells out its join (not every one has a foreign key behind it). They're all `viewonly` (writes
go through the columns; what a delete takes along is the database's foreign keys' doing) and `lazy="raise"`, so reading one
that wasn't loaded up front fails loudly rather than running a query per row: load them with
`options(selectinload(...))`, or join on them.
"""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase, Mapped, relationship

from . import schema


class Base(DeclarativeBase):
    metadata = schema.metadata


def _rel(target: str, join: str, **kw):
    """A read-only relationship that must be loaded explicitly (see above)."""
    return relationship(target, primaryjoin=join, viewonly=True, lazy="raise", **kw)


class AuthPending(Base):
    __table__ = schema.auth_pending
    state: Mapped[str]
    nonce: Mapped[str | None]
    verifier: Mapped[str | None]
    next: Mapped[str | None]
    created: Mapped[float | None]


class AuthSession(Base):
    __table__ = schema.auth_sessions
    token_hash: Mapped[str]
    sub: Mapped[str | None]
    email: Mapped[str | None]
    name: Mapped[str | None]
    created: Mapped[float | None]
    expires: Mapped[float | None]
    id_token: Mapped[str | None]


class User(Base):
    __table__ = schema.users
    sub: Mapped[str]
    email: Mapped[str | None]
    name: Mapped[str | None]
    first_name: Mapped[str | None]
    last_seen: Mapped[float | None]


class Person(Base):
    __table__ = schema.people
    id: Mapped[int]
    display_name: Mapped[str]
    first_name: Mapped[str | None]
    legal_name: Mapped[str | None]
    aliases: Mapped[str | None]   # a JSON list of the ways an airline prints the name (waypoint/domain/people.py)
    user_sub: Mapped[str | None]


class Airport(Base):
    __table__ = schema.airports
    code: Mapped[str]
    name: Mapped[str]
    city: Mapped[str]
    country: Mapped[str]
    zone: Mapped[str]
    latitude: Mapped[float]
    longitude: Mapped[float]


class Trip(Base):
    __table__ = schema.trips
    id: Mapped[int]
    name: Mapped[str]
    start_date: Mapped[str | None]   # the first segment's local date
    end_date: Mapped[str | None]     # the last segment's local date
    destination: Mapped[str | None]
    notes: Mapped[str | None]
    auto: Mapped[bool]               # grouped by Waypoint (False: made by hand, or changed by a person)
    booked_by: Mapped[int | None]    # a person


class Segment(Base):
    __table__ = schema.segments
    id: Mapped[int]
    trip_id: Mapped[int]
    kind: Mapped[str]                # flight, hotel, car or train (waypoint/domain/trips.py)
    status: Mapped[str]              # confirmed, changed or cancelled
    confirmation: Mapped[str | None]
    provider: Mapped[str | None]
    start_local: Mapped[str]         # wall-clock time at the start's place, 2026-03-01T22:15:00, never converted
    start_zone: Mapped[str]          # that place's IANA zone
    end_local: Mapped[str]
    end_zone: Mapped[str]
    origin: Mapped[str | None]
    destination: Mapped[str | None]
    details: Mapped[str | None]      # a JSON object: flight number, terminal, seat, cabin, room, car class, address, phone
    manage_url: Mapped[str | None]
    source: Mapped[str]              # manual or email
    booked_by: Mapped[int | None]    # a person
    locked_fields: Mapped[str | None]   # a JSON list of the fields a person edited, which a later email never overwrites


class SegmentTraveler(Base):
    __table__ = schema.segment_travelers
    id: Mapped[int]
    segment_id: Mapped[int]
    person_id: Mapped[int | None]
    name: Mapped[str | None]         # as printed, until it's matched to a person


class LoyaltyId(Base):
    __table__ = schema.loyalty_ids
    id: Mapped[int]
    person_id: Mapped[int]
    kind: Mapped[str]
    program: Mapped[str]
    number: Mapped[str]   # encrypted: read only through waypoint/domain/loyalty.py
    tier: Mapped[str | None]
    expiry: Mapped[str | None]   # a day, YYYY-MM-DD
    notes: Mapped[str | None]


class FlightStatus(Base):
    __table__ = schema.flight_status
    flight_number: Mapped[str]       # no spaces, upper case: EX101
    date: Mapped[str]                # the flight's local departure date, YYYY-MM-DD
    state: Mapped[str]               # scheduled, delayed, departed, landed, cancelled, diverted or unknown (waypoint/domain/flightstatus.py)
    origin: Mapped[str | None]       # airport codes, as the service names them
    destination: Mapped[str | None]
    dep_scheduled: Mapped[str | None]   # wall-clock times at the airports, 2026-03-01T22:15, never converted
    dep_estimated: Mapped[str | None]
    dep_actual: Mapped[str | None]
    dep_zone: Mapped[str | None]     # the airport's IANA zone
    dep_terminal: Mapped[str | None]
    dep_gate: Mapped[str | None]
    arr_scheduled: Mapped[str | None]
    arr_estimated: Mapped[str | None]
    arr_actual: Mapped[str | None]
    arr_zone: Mapped[str | None]
    arr_terminal: Mapped[str | None]
    arr_gate: Mapped[str | None]
    fetched_at: Mapped[float]        # when the answer came, seconds since the epoch (0 when no call has succeeded)
    attempted_at: Mapped[float | None]   # when a call for it was last made, which used up that check whether or not it worked


class Setting(Base):
    __table__ = schema.settings
    key: Mapped[str]
    value: Mapped[str | None]


class Mailbox(Base):
    __table__ = schema.mailboxes
    id: Mapped[int]
    owner_sub: Mapped[str]
    address: Mapped[str]
    token: Mapped[str]
    history_id: Mapped[str | None]
    last_scan: Mapped[float | None]
    status: Mapped[str]
    last_error: Mapped[str | None]
    created: Mapped[float | None]
    scan_error: Mapped[str | None]   # what the last scan couldn't do (fixed text); cleared by a scan that finishes


class MailboxPending(Base):
    __table__ = schema.mailbox_pending
    state: Mapped[str]
    owner_sub: Mapped[str]
    verifier: Mapped[str]
    created: Mapped[float]


class ScannedMessage(Base):
    __table__ = schema.scanned_messages
    id: Mapped[int]
    mailbox_id: Mapped[int]
    message_id: Mapped[str]          # Gmail's id for the message: a reference, never its content
    outcome: Mapped[str]             # booking, unreadable or ignored (waypoint/domain/mail/scan.py)
    scanned: Mapped[float]


class ReviewItem(Base):
    __table__ = schema.review_items
    id: Mapped[int]
    mailbox_id: Mapped[int]
    message_id: Mapped[str]
    sender_domain: Mapped[str]
    received: Mapped[str | None]     # the day on the message's Date header
    reason: Mapped[str]              # why it couldn't be read: a code (waypoint/domain/mail/review.py)
    created: Mapped[float]


class IgnoredSender(Base):
    __table__ = schema.ignored_senders
    id: Mapped[int]
    mailbox_id: Mapped[int]
    domain: Mapped[str]
