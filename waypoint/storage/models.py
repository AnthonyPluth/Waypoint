from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase, Mapped, relationship

from . import schema


class Base(DeclarativeBase):
    metadata = schema.metadata


def _rel(target: str, join: str, **kw):
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
    aliases: Mapped[str | None]
    user_sub: Mapped[str | None]
    links: Mapped[str | None]
    claim_dismissed: Mapped[bool | None]


class Airport(Base):
    __table__ = schema.airports
    code: Mapped[str]
    name: Mapped[str]
    city: Mapped[str]
    country: Mapped[str]
    zone: Mapped[str]
    latitude: Mapped[float]
    longitude: Mapped[float]


class Airline(Base):
    __table__ = schema.airlines
    code: Mapped[str]
    icao: Mapped[str | None]
    name: Mapped[str]
    country: Mapped[str | None]


class BrandLogo(Base):
    __table__ = schema.brand_logos
    key: Mapped[str]
    name: Mapped[str]
    logo: Mapped[bytes | None]
    logo_type: Mapped[str | None]
    checked: Mapped[str | None]
    source: Mapped[str | None]


class Trip(Base):
    __table__ = schema.trips
    id: Mapped[int]
    name: Mapped[str]
    start_date: Mapped[str | None]
    end_date: Mapped[str | None]
    destination: Mapped[str | None]
    notes: Mapped[str | None]
    auto: Mapped[bool]
    booked_by: Mapped[int | None]


class Segment(Base):
    __table__ = schema.segments
    id: Mapped[int]
    trip_id: Mapped[int]
    kind: Mapped[str]
    status: Mapped[str]
    confirmation: Mapped[str | None]
    provider: Mapped[str | None]
    start_local: Mapped[str]
    start_zone: Mapped[str]
    end_local: Mapped[str]
    end_zone: Mapped[str]
    origin: Mapped[str | None]
    destination: Mapped[str | None]
    details: Mapped[str | None]
    manage_url: Mapped[str | None]
    source: Mapped[str]
    booked_by: Mapped[int | None]
    locked_fields: Mapped[str | None]
    check_times: Mapped[bool]


class SegmentTraveler(Base):
    __table__ = schema.segment_travelers
    id: Mapped[int]
    segment_id: Mapped[int]
    person_id: Mapped[int | None]
    name: Mapped[str | None]
    seat: Mapped[str | None]


class SegmentPort(Base):
    __table__ = schema.segment_ports
    id: Mapped[int]
    segment_id: Mapped[int]
    position: Mapped[int]
    name: Mapped[str]
    zone: Mapped[str]
    arrive_local: Mapped[str | None]
    depart_local: Mapped[str | None]


class SegmentRecipient(Base):
    __table__ = schema.segment_recipients
    id: Mapped[int]
    segment_id: Mapped[int]
    person_id: Mapped[int]


class LoyaltyId(Base):
    __table__ = schema.loyalty_ids
    id: Mapped[int]
    person_id: Mapped[int]
    kind: Mapped[str]
    program: Mapped[str]
    number: Mapped[str]
    expiry: Mapped[str | None]
    notes: Mapped[str | None]


class FlightStatus(Base):
    __table__ = schema.flight_status
    flight_number: Mapped[str]
    date: Mapped[str]
    state: Mapped[str]
    origin: Mapped[str | None]
    destination: Mapped[str | None]
    dep_scheduled: Mapped[str | None]
    dep_estimated: Mapped[str | None]
    dep_actual: Mapped[str | None]
    dep_zone: Mapped[str | None]
    dep_terminal: Mapped[str | None]
    dep_gate: Mapped[str | None]
    arr_scheduled: Mapped[str | None]
    arr_estimated: Mapped[str | None]
    arr_actual: Mapped[str | None]
    arr_zone: Mapped[str | None]
    arr_terminal: Mapped[str | None]
    arr_gate: Mapped[str | None]
    fetched_at: Mapped[float]
    attempted_at: Mapped[float | None]


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
    scan_error: Mapped[str | None]
    share_review: Mapped[bool]


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
    message_id: Mapped[str]
    outcome: Mapped[str]
    scanned: Mapped[float]


class ReviewItem(Base):
    __table__ = schema.review_items
    id: Mapped[int]
    mailbox_id: Mapped[int]
    message_id: Mapped[str]
    sender_domain: Mapped[str]
    received: Mapped[str | None]
    reason: Mapped[str]
    created: Mapped[float]
    suggestion: Mapped[str | None]
    suggestion_error: Mapped[str | None]
    matches: Mapped[str | None]


class StoredMessage(Base):
    __table__ = schema.stored_messages
    id: Mapped[int]
    mailbox_id: Mapped[int]
    message_id: Mapped[str]
    content: Mapped[str]
    subject: Mapped[str | None]
    created: Mapped[float]


class SegmentMessage(Base):
    __table__ = schema.segment_messages
    segment_id: Mapped[int]
    stored_message_id: Mapped[int]


class IgnoredSender(Base):
    __table__ = schema.ignored_senders
    id: Mapped[int]
    mailbox_id: Mapped[int]
    domain: Mapped[str]


class PushDevice(Base):
    __table__ = schema.push_devices
    id: Mapped[int]
    owner_sub: Mapped[str]
    endpoint: Mapped[str]
    p256dh: Mapped[str]
    auth: Mapped[str]
    created: Mapped[float]


class ReminderPrefs(Base):
    __table__ = schema.reminder_prefs
    owner_sub: Mapped[str]
    check_in: Mapped[bool]
    day_of: Mapped[bool]


class ReminderSent(Base):
    __table__ = schema.reminders_sent
    id: Mapped[int]
    owner_sub: Mapped[str]
    kind: Mapped[str]
    ref: Mapped[str]
    sent: Mapped[float]


class CalendarFeed(Base):
    __table__ = schema.calendar_feeds
    owner_sub: Mapped[str]
    key_hash: Mapped[str]
    created: Mapped[float]


class OAuthClient(Base):
    __table__ = schema.oauth_clients
    id: Mapped[str]
    name: Mapped[str | None]
    redirect_uris: Mapped[str]
    auth_method: Mapped[str]
    secret_hash: Mapped[str | None]
    kind: Mapped[str]
    metadata_url: Mapped[str | None]
    created: Mapped[float]
    last_used: Mapped[float | None]


class OAuthGrant(Base):
    __table__ = schema.oauth_grants
    id: Mapped[int]
    client_id: Mapped[str]
    sub: Mapped[str | None]
    email: Mapped[str | None]
    scope: Mapped[str]
    resource: Mapped[str]
    created: Mapped[float]
    last_used: Mapped[float | None]
    revoked: Mapped[float | None]
    revoked_reason: Mapped[str | None]


class OAuthCode(Base):
    __table__ = schema.oauth_codes
    code_hash: Mapped[str]
    client_id: Mapped[str]
    grant_id: Mapped[int]
    redirect_uri: Mapped[str]
    code_challenge: Mapped[str]
    resource: Mapped[str]
    created: Mapped[float]
    used: Mapped[float | None]


class OAuthToken(Base):
    __table__ = schema.oauth_tokens
    token_hash: Mapped[str]
    kind: Mapped[str]
    grant_id: Mapped[int]
    created: Mapped[float]
    expires: Mapped[float]
    consumed: Mapped[float | None]
    replaced_by: Mapped[str | None]


class OAuthConsent(Base):
    __table__ = schema.oauth_consents
    token_hash: Mapped[str]
    params: Mapped[str]
    created: Mapped[float]
