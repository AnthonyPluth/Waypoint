"""Waypoint's database schema, for SQLite and Postgres alike. Alembic migrations (waypoint/storage/migrations) create and change it."""
from sqlalchemy import Boolean, Column, Float, ForeignKey, Index, Integer, MetaData, Table, Text, UniqueConstraint, false
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import FunctionElement

metadata = MetaData()


def refers(table: str, column: str, target: str, ondelete: str) -> ForeignKey:
    """A foreign key, named fk_<table>_<column>. ondelete is what removing the row it refers to does: CASCADE takes
    this row with it, SET NULL lets go (deleted_accounts.remove does the rest by hand). Deferrable, so a restore can
    load rows that refer to each other in any order (backup.restore), but checked at once otherwise."""
    return ForeignKey(target, name=f"fk_{table}_{column}", ondelete=ondelete, deferrable=True, initially="IMMEDIATE")



class now_text(FunctionElement):
    """The current time as 'YYYY-MM-DD HH:MM:SS' text (UTC, or the server's local time), on either database."""
    type = Text()
    inherit_cache = True

    def __init__(self, local: bool = False):
        self.local = local
        super().__init__()


@compiles(now_text, "sqlite")
def _now_sqlite(element, compiler, **kw):
    return "(datetime('now', 'localtime'))" if element.local else "CURRENT_TIMESTAMP"


@compiles(now_text, "postgresql")
def _now_postgres(element, compiler, **kw):
    return "to_char(now()%s, 'YYYY-MM-DD HH24:MI:SS')" % ("" if element.local else " at time zone 'utc'")

auth_pending = Table(
    'auth_pending', metadata,
    Column('state', Text, primary_key=True),
    Column('nonce', Text),
    Column('verifier', Text),
    Column('next', Text),
    Column('created', Float),
    info={'doc': 'sign-ins in progress at the OIDC provider'},
)

auth_sessions = Table(
    'auth_sessions', metadata,
    Column('token_hash', Text, primary_key=True),
    Column('sub', Text),
    Column('email', Text),
    Column('name', Text),
    Column('created', Float),
    Column('expires', Float),
    Column('id_token', Text),
    info={'doc': 'signed-in browsers (only a hash of each session token is kept)'},
)

users = Table(
    'users', metadata,
    Column('sub', Text, primary_key=True),
    Column('email', Text),
    Column('name', Text),
    Column('first_name', Text),
    Column('last_seen', Float),
    info={'doc': 'people who have signed in (the household)'},
)

people = Table(
    'people', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('display_name', Text, nullable=False),
    Column('first_name', Text),
    Column('legal_name', Text),
    Column('aliases', Text),
    Column('user_sub', Text, refers('people', 'user_sub', 'users.sub', 'SET NULL')),
    Index('ux_people_user_sub', 'user_sub', unique=True),
    info={'doc': 'everyone who travels: household members (linked to their sign-in) and guests with no login'},
)

airports = Table(
    'airports', metadata,
    Column('code', Text, primary_key=True),
    Column('name', Text, nullable=False),
    Column('city', Text, nullable=False),
    Column('country', Text, nullable=False),
    Column('zone', Text, nullable=False),
    Column('latitude', Float, nullable=False),
    Column('longitude', Float, nullable=False),
    info={'doc': 'airports by IATA code, with their IANA time zone (seeded from waypoint/storage/airports.tsv.gz; reference data, not part of a backup)'},
)

airlines = Table(
    'airlines', metadata,
    Column('code', Text, primary_key=True),
    Column('icao', Text),
    Column('name', Text, nullable=False),
    Column('country', Text),
    info={'doc': 'airlines by IATA code (seeded from waypoint/storage/airlines.tsv.gz, from OpenFlights under the ODbL; reference data, not part of a backup)'},
)

trips = Table(
    'trips', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('name', Text, nullable=False),
    Column('start_date', Text),
    Column('end_date', Text),
    Column('destination', Text),
    Column('notes', Text),
    Column('auto', Boolean, nullable=False),
    Column('booked_by', Integer, refers('trips', 'booked_by', 'people.id', 'SET NULL')),
    Index('ix_trips_booked_by', 'booked_by'),
    info={'doc': 'a journey: its segments, grouped by Waypoint (auto) or made by hand; its dates are its local dates'},
)

segments = Table(
    'segments', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('trip_id', Integer, refers('segments', 'trip_id', 'trips.id', 'CASCADE'), nullable=False),
    Column('kind', Text, nullable=False),
    Column('status', Text, nullable=False),
    Column('confirmation', Text),
    Column('provider', Text),
    Column('start_local', Text, nullable=False),
    Column('start_zone', Text, nullable=False),
    Column('end_local', Text, nullable=False),
    Column('end_zone', Text, nullable=False),
    Column('origin', Text),
    Column('destination', Text),
    Column('details', Text),
    Column('manage_url', Text),
    Column('source', Text, nullable=False),
    Column('booked_by', Integer, refers('segments', 'booked_by', 'people.id', 'SET NULL')),
    Column('locked_fields', Text),
    Column('check_times', Boolean, nullable=False, server_default=false()),
    Index('ix_segments_trip_id', 'trip_id'),
    Index('ix_segments_booked_by', 'booked_by'),
    info={'doc': "one flight leg, hotel stay, car rental or train; times are local wall-clock times with the place's IANA zone"},
)

segment_travelers = Table(
    'segment_travelers', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('segment_id', Integer, refers('segment_travelers', 'segment_id', 'segments.id', 'CASCADE'), nullable=False),
    Column('person_id', Integer, refers('segment_travelers', 'person_id', 'people.id', 'CASCADE')),
    Column('name', Text),
    Index('ix_segment_travelers_segment_id', 'segment_id'),
    Index('ix_segment_travelers_person_id', 'person_id'),
    info={'doc': 'who a segment is for: a person, or until matched to one, the name as printed on the booking'},
)

loyalty_ids = Table(
    'loyalty_ids', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('person_id', Integer, refers('loyalty_ids', 'person_id', 'people.id', 'CASCADE'), nullable=False),
    Column('kind', Text, nullable=False),
    Column('program', Text, nullable=False),
    Column('number', Text, nullable=False),
    Column('tier', Text),
    Column('expiry', Text),
    Column('notes', Text),
    Index('ix_loyalty_ids_person_id', 'person_id'),
    info={'doc': "loyalty and Known Traveler numbers, one row per membership; the number is encrypted (waypoint/storage/secretbox.py)"},
)

flight_status = Table(
    'flight_status', metadata,
    Column('flight_number', Text, primary_key=True),
    Column('date', Text, primary_key=True),
    Column('state', Text, nullable=False),
    Column('origin', Text),
    Column('destination', Text),
    Column('dep_scheduled', Text),
    Column('dep_estimated', Text),
    Column('dep_actual', Text),
    Column('dep_zone', Text),
    Column('dep_terminal', Text),
    Column('dep_gate', Text),
    Column('arr_scheduled', Text),
    Column('arr_estimated', Text),
    Column('arr_actual', Text),
    Column('arr_zone', Text),
    Column('arr_terminal', Text),
    Column('arr_gate', Text),
    Column('fetched_at', Float, nullable=False),
    Column('attempted_at', Float),
    info={'doc': "the last live status answer for a flight number on a local departure date (a cache shared by everyone on the flight, with no personal data; not part of a backup)"},
)

settings = Table(
    'settings', metadata,
    Column('key', Text, primary_key=True),
    Column('value', Text),
)

mailboxes = Table(
    'mailboxes', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('owner_sub', Text, nullable=False),
    Column('address', Text, nullable=False),
    Column('token', Text, nullable=False),
    Column('history_id', Text),
    Column('last_scan', Float),
    Column('status', Text, nullable=False),
    Column('last_error', Text),
    Column('created', Float),
    Column('scan_error', Text),
    UniqueConstraint('owner_sub', 'address', name='uq_mailboxes_owner_address'),
    info={'doc': "Gmail accounts members connected (read-only); each belongs to the member who connected it, its refresh token is kept encrypted"},
)

mailbox_pending = Table(
    'mailbox_pending', metadata,
    Column('state', Text, primary_key=True),
    Column('owner_sub', Text, nullable=False),
    Column('verifier', Text, nullable=False),
    Column('created', Float, nullable=False),
    info={'doc': 'Gmail connections in progress at Google'},
)

scanned_messages = Table(
    'scanned_messages', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('mailbox_id', Integer, refers('scanned_messages', 'mailbox_id', 'mailboxes.id', 'CASCADE'), nullable=False),
    Column('message_id', Text, nullable=False),
    Column('outcome', Text, nullable=False),
    Column('scanned', Float, nullable=False),
    UniqueConstraint('mailbox_id', 'message_id', name='uq_scanned_messages_mailbox_message'),
    info={'doc': "each Gmail message id a scan has looked at and what came of it (booking, unreadable, ignored), so nothing is read twice; holds no content"},
)

review_items = Table(
    'review_items', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('mailbox_id', Integer, refers('review_items', 'mailbox_id', 'mailboxes.id', 'CASCADE'), nullable=False),
    Column('message_id', Text, nullable=False),
    Column('sender_domain', Text, nullable=False),
    Column('received', Text),
    Column('reason', Text, nullable=False),
    Column('created', Float, nullable=False),
    Column('suggestion', Text),
    Column('suggestion_error', Text),
    UniqueConstraint('mailbox_id', 'message_id', name='uq_review_items_mailbox_message'),
    info={'doc': "mail that looked like a booking but couldn't be read (\"Couldn't read\"), for its mailbox's owner alone; neither its subject nor its body is kept; `suggestion` is the booking's fields (JSON) the optional AI read from it, for the person to confirm or edit, and `suggestion_error` why it couldn't (fixed text)"},
)

ignored_senders = Table(
    'ignored_senders', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('mailbox_id', Integer, refers('ignored_senders', 'mailbox_id', 'mailboxes.id', 'CASCADE'), nullable=False),
    Column('domain', Text, nullable=False),
    UniqueConstraint('mailbox_id', 'domain', name='uq_ignored_senders_mailbox_domain'),
    info={'doc': "sender domains a mailbox's owner chose to stop reviewing: their mail is skipped by later scans"},
)

push_devices = Table(
    'push_devices', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('owner_sub', Text, nullable=False),
    Column('endpoint', Text, nullable=False),
    Column('p256dh', Text, nullable=False),
    Column('auth', Text, nullable=False),
    Column('created', Float, nullable=False),
    UniqueConstraint('endpoint', name='uq_push_devices_endpoint'),
    Index('ix_push_devices_owner', 'owner_sub'),
    info={'doc': "browsers and phones a member turned notifications on for; each ends when its owner can no longer sign in, and doesn't travel in a backup"},
)

reminder_prefs = Table(
    'reminder_prefs', metadata,
    Column('owner_sub', Text, primary_key=True),
    Column('check_in', Boolean, nullable=False),
    Column('day_of', Boolean, nullable=False),
    info={'doc': "which reminders a member gets: \"Check-in opens\" 24 hours before a flight, and the day-of summary"},
)

reminders_sent = Table(
    'reminders_sent', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('owner_sub', Text, nullable=False),
    Column('kind', Text, nullable=False),
    Column('ref', Text, nullable=False),
    Column('sent', Float, nullable=False),
    UniqueConstraint('owner_sub', 'kind', 'ref', name='uq_reminders_sent_owner_kind_ref'),
    info={'doc': "each reminder already sent (a flight's check-in, a day's summary), so none goes out twice; holds no content"},
)

calendar_feeds = Table(
    'calendar_feeds', metadata,
    Column('owner_sub', Text, primary_key=True),
    Column('key_hash', Text, nullable=False),
    Column('created', Float, nullable=False),
    UniqueConstraint('key_hash', name='uq_calendar_feeds_key_hash'),
    info={'doc': "a member's private calendar feed: only the hash of the random key in its address is kept; ends when its owner can no longer sign in, and doesn't travel in a backup"},
)

# Tables whose integer id is assigned by the database.
AUTO_ID = {t.name for t in metadata.tables.values() if 'id' in t.c and t.c.id.autoincrement is True}
