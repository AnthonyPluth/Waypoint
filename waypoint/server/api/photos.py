from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ... import validate
from ...domain import photos, photosources
from ...domain.photosources import Actor
from ...providers import immich
from .. import jobs
from ..common import ApiError, _current, row_id
from ..contract import (Ok, PhotoBody, PhotoReview, PhotoSource, PhotoSourceBody, PhotoSourceEdit, PhotoSources, PhotoSourceTest, PhotoSourceTestBody,
                        SyncStarted, TripPhoto, TripPhotos)
from .trips import NO_TRIP, _run, viewer

NO_PHOTO = "No such photo"
NOTHING_TO_DO = 'Send "trip_id" to put the photo on a trip, or "hidden" to hide or show it'
MAX_ID = 10 ** 18
NOT_A_TRIP = "The trip must be a whole number"
OFF = "Photos are off without sign-in."
NOT_A_PERSON = "The person must be a whole number"
BAD_URL = "The Immich address must be a web address, such as https://immich.local:2283, with no path or sign-in in it"
BAD_KEY = "Enter the API key as Immich shows it"
KEY_LIMIT = 512
LABEL_LIMIT = 100
NOTHING_TO_CHANGE = 'Send "key", "label" or "paused"'
FAILED = {immich.Refused: 400, immich.NotConfigured: 400, immich.RateLimited: 503, immich.Unavailable: 502}
REFUSALS = {photosources.NOT_YOURS: 403, photosources.OTHER_STEWARD: 403, photosources.ALREADY: 409}
_v = validate.Validator(ApiError, not_number=NOT_A_TRIP, too_long="The {label} is too long (at most {limit} characters)")


def api_trip_photos(conn, _q, _b, trip_id) -> TripPhotos:
    who = viewer(conn)
    return _run(lambda: photos.for_trip(conn, who, row_id(trip_id, NO_TRIP)), NO_TRIP)


def api_photo_review(conn, _q, _b) -> PhotoReview:
    return photos.needs_a_look(conn, viewer(conn))


def api_photo_decide(conn, _q, body: PhotoBody, photo_id) -> TripPhoto:
    who, this = viewer(conn), row_id(photo_id, NO_PHOTO)
    if isinstance(body.get("trip_id"), bool):
        raise ApiError(NOT_A_TRIP)
    trip = _v.integer(body.get("trip_id"), "trip", 1, MAX_ID)
    hidden = body.get("hidden")
    if hidden is not None and not isinstance(hidden, bool):
        raise ApiError('Send "hidden" as true or false')
    if trip is None and hidden is None:
        raise ApiError(NOTHING_TO_DO)
    return _run(lambda: photos.decide(conn, who, this, trip, hidden), NO_PHOTO)


def actor(conn) -> Actor:
    user = getattr(_current, "user", None) or {}
    sub = user.get("sub")
    if user.get("local") or not sub:
        raise ApiError(OFF, 404)
    return Actor(str(sub), viewer(conn).person_id)


def _text(body: Any, key: str, label: str, limit: int, required: bool = False) -> str | None:
    value = body.get(key)
    if value is not None and not isinstance(value, str):
        raise ApiError(f'Send "{key}" as text')
    return _v.text(value, label, limit, required)


def _url(body: Any, required: bool) -> str | None:
    text = _text(body, "url", "Immich address", immich.MAX_URL, required)
    if text is None:
        return None
    cleaned = immich.clean_url(text)
    if cleaned is None:
        raise ApiError(BAD_URL)
    return cleaned


def _key(body: Any, required: bool) -> str | None:
    text = _text(body, "key", "API key", KEY_LIMIT, required)
    if text is None:
        return None
    if not immich.KEY.fullmatch(text):
        raise ApiError(BAD_KEY)
    return text


def _ask[T](make: Callable[[], T]) -> T:
    try:
        return make()
    except photosources.NoSuchSource:
        raise ApiError(photosources.NO_SOURCE, 404) from None
    except photosources.NoSuchPerson:
        raise ApiError(photosources.NO_PERSON, 404) from None
    except photosources.Refused as e:
        raise ApiError(str(e), REFUSALS.get(str(e), 400)) from None
    except immich.ImmichError as e:
        raise ApiError(str(e), next((status for kind, status in FAILED.items() if isinstance(e, kind)), 502)) from None


def api_photo_sources(conn, _q, _b) -> PhotoSources:
    return {"sources": [PhotoSource(**s) for s in photosources.listing(conn, actor(conn))], "permissions": list(photosources.PERMISSIONS)}


def api_photo_source_add(conn, _q, body: PhotoSourceBody) -> PhotoSource:
    me = actor(conn)
    if isinstance(body.get("person_id"), bool):
        raise ApiError(NOT_A_PERSON)
    person = _v.integer(body.get("person_id"), "person", 1, MAX_ID) if body.get("person_id") is not None else me.person_id
    if person is None:
        raise ApiError(photosources.NO_PERSON, 404)
    url, key = _url(body, True), _key(body, True)
    assert url is not None and key is not None
    label = _text(body, "label", "label", LABEL_LIMIT)
    return PhotoSource(**_ask(lambda: photosources.connect(conn, me, person, url, key, label)))


def api_photo_source_test_new(conn, _q, body: PhotoSourceTestBody) -> PhotoSourceTest:
    actor(conn)
    url, key = _url(body, True), _key(body, True)
    assert url is not None and key is not None
    return _ask(lambda: photosources.test_new(url, key))


def api_photo_source_test(conn, _q, body: PhotoSourceTestBody, source_id) -> PhotoSourceTest:
    me, this = actor(conn), row_id(source_id, photosources.NO_SOURCE)
    key = _key(body, False)
    return _ask(lambda: photosources.test(conn, me, this, key))


def api_photo_source_edit(conn, _q, body: PhotoSourceEdit, source_id) -> PhotoSource:
    me, this = actor(conn), row_id(source_id, photosources.NO_SOURCE)
    key = _key(body, False)
    paused = body.get("paused")
    if paused is not None and not isinstance(paused, bool):
        raise ApiError('Send "paused" as true or false')
    label = _text(body, "label", "label", LABEL_LIMIT)
    if key is None and paused is None and "label" not in body:
        raise ApiError(NOTHING_TO_CHANGE)
    if key is not None:
        _ask(lambda: photosources.change_key(conn, me, this, key))
    return PhotoSource(**_ask(lambda: photosources.edit(conn, me, this, label, paused, "label" in body)))


def api_photo_source_remove(conn, _q, _b, source_id) -> Ok:
    me, this = actor(conn), row_id(source_id, photosources.NO_SOURCE)
    _ask(lambda: photosources.remove(conn, me, this))
    return {"ok": True}


def api_photo_source_sync(conn, _q, _b, source_id) -> SyncStarted:
    me, this = actor(conn), row_id(source_id, photosources.NO_SOURCE)
    _ask(lambda: photosources.owned(conn, me, this))
    return {"started": jobs.sync_photos_now(this)}
