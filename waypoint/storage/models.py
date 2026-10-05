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


class MailboxPending(Base):
    __table__ = schema.mailbox_pending
    state: Mapped[str]
    owner_sub: Mapped[str]
    verifier: Mapped[str]
    created: Mapped[float]
