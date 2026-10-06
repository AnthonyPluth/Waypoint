"""Brand logos: a booking's logo (served from Waypoint's own copy, through a segment the viewer can see) and Settings → Logos, where
the household saves its Logo.dev keys (waypoint/domain/logos.py). The keys are saved encrypted and never come back: the reply only
says whether one is saved."""
from __future__ import annotations

from ... import validate
from ...domain import logos
from ...storage import db
from ...storage import settings_keys as sk
from .. import jobs
from ..common import ApiError, Response, row_id
from ..contract import LogoDevBody, LogoDevFetch, LogoDevStatus
from .trips import NO_SEGMENT, viewer

_v = validate.Validator(ApiError, too_long="The {label} is too long (at most {limit} characters)")


def api_segment_logo(conn, _q, _b, segment_id) -> Response:
    """The logo of this segment's airline, hotel, rental company or cruise line. 404 for a segment that isn't the viewer's, as
    for one that isn't there, and for one whose brand has no logo."""
    found = logos.segment_logo(conn, viewer(conn), row_id(segment_id, NO_SEGMENT))
    if found is None:
        raise ApiError(NO_SEGMENT, 404)
    data, content_type = found
    return Response(data, content_type, cache="private, max-age=86400")


def api_logodev(conn, _q, _b) -> LogoDevStatus:
    """Where logos stand (never the keys)."""
    return logos.status(conn)


def api_logodev_save(conn, _q, body: LogoDevBody) -> LogoDevStatus:
    """Save the publishable key (pk_...) and, optionally, the secret key (sk_..., for Brand Search), or forget them. Saving a key
    starts fetching the logos of the brands in bookings."""
    token, secret = body.get("token"), body.get("secret")
    for name, value in (("token", token), ("secret", secret)):
        if value is not None and not isinstance(value, str):
            raise ApiError(f"Send “{name}” as text")
    if body.get("clear") is True:
        db.set_setting(conn, sk.LOGODEV_TOKEN, None)
        db.set_setting(conn, sk.LOGODEV_SECRET, None)
        db.set_setting(conn, sk.LOGODEV_LAST_ERROR, None)
        return logos.status(conn)
    if token is not None:
        token = _v.text(token, "Logo.dev publishable key", 200, required=True)
        if not (token or "").startswith("pk_"):
            raise ApiError("That isn't a Logo.dev publishable key: it starts with pk_ (the secret sk_ key goes in the other box).")
    if secret is not None:
        secret = _v.text(secret, "Logo.dev secret key", 200, required=True)
        if not (secret or "").startswith("sk_"):
            raise ApiError("That isn't a Logo.dev secret key: it starts with sk_.")
        if token is None and not logos.configured(conn):
            raise ApiError("Save the publishable key first.")
    # (everything is checked: a request that is refused changes nothing)
    if body.get("clear_secret") is True:
        db.set_setting(conn, sk.LOGODEV_SECRET, None)
    if token is not None:
        db.set_setting(conn, sk.LOGODEV_TOKEN, token)
    if secret is not None:
        db.set_setting(conn, sk.LOGODEV_SECRET, secret)
    if token is not None or secret is not None:
        conn.commit()   # the round below reads it from its own connection
        jobs.fetch_logos_now()
    return logos.status(conn)


def api_logodev_fetch(conn, _q, _b) -> LogoDevFetch:
    """Fetch the logos not fetched yet now (they fill in over the next minutes), in the background."""
    if not logos.configured(conn):
        raise ApiError("Save a Logo.dev key first.")
    return {"started": jobs.fetch_logos_now()}
