"""Waypoint's database schema, for SQLite and Postgres alike. Alembic migrations (waypoint/storage/migrations) create and change it."""
from sqlalchemy import Column, Float, ForeignKey, Index, Integer, MetaData, Table, Text, UniqueConstraint
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

# Tables whose integer id is assigned by the database.
AUTO_ID = {t.name for t in metadata.tables.values() if 'id' in t.c and t.c.id.autoincrement is True}
