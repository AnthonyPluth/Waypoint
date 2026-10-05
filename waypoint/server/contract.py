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
