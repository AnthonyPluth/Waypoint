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
    last_scan: str | None           # with its UTC offset


class MailboxList(TypedDict):
    configured: bool                # GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are set
    mailboxes: list[Mailbox]        # the signed-in member's own


class Started(TypedDict):
    url: str                        # Google's consent screen, to send the browser to


class Disconnected(TypedDict):
    ok: bool
    revoked: bool                   # false when Waypoint couldn't unlock the saved token to revoke it: remove it at Google


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
