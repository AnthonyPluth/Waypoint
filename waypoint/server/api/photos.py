from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ... import validate
from ...domain import photogrants, photos
from ...domain.visibility import Viewer
from ..common import ApiError, row_id
from ..contract import PhotoBody, PhotoExclusionsBody, PhotoGrants, PhotoPrefs, PhotoPrefsBody, PhotoReview, PhotoSharing, PhotoSharingBody, TripPhoto, TripPhotos
from .trips import NO_TRIP, _run, viewer

NO_PHOTO = "No such photo"
PHOTOS_OFF = "Photos need sign-in"
NOTHING_TO_DO = 'Send "trip_id" to put the photo on a trip, or "excluded" to leave it off'
NOTHING_TO_SHARE = 'Send "scope" to share, or "declined" for Not now'
MAX_ID = 10 ** 18
MAX_REMOVED = 500
NOT_A_TRIP = "The trip must be a whole number"
NOT_A_PERSON = "The person must be a whole number"
NOT_A_SCOPE = 'Send "scope" as "only_me" or "trip"'
NOT_IDS = 'Send "photo_ids" as a list of whole numbers'
_v = validate.Validator(ApiError, not_number=NOT_A_TRIP)
_p = validate.Validator(ApiError, not_number=NOT_A_PERSON)


def _viewer(conn) -> Viewer:
    who = viewer(conn)
    if who.household:
        raise ApiError(PHOTOS_OFF, 404)
    return who


def _flag(body: Any, key: str) -> bool | None:
    value = body.get(key)
    if value is not None and not isinstance(value, bool):
        raise ApiError(f'Send "{key}" as true or false')
    return value


def _scope(body: Any) -> photos.Scope | None:
    value = body.get("scope")
    if value is None:
        return None
    if value not in photos.SCOPES:
        raise ApiError(NOT_A_SCOPE)
    return value


def _person(conn, who: Viewer, value: Any) -> int:
    if isinstance(value, bool):
        raise ApiError(NOT_A_PERSON)
    chosen = _p.integer(value, "person", 1, MAX_ID)
    if chosen is None:
        if who.person_id is None:
            raise ApiError(NO_TRIP, 404)
        return who.person_id
    return chosen


def _sharing(make: Callable[[], PhotoSharing | None]) -> PhotoSharing:
    return _run(make, NO_TRIP)


def api_trip_photos(conn, _q, _b, trip_id) -> TripPhotos:
    who = _viewer(conn)
    return _run(lambda: photos.for_trip(conn, who, row_id(trip_id, NO_TRIP)), NO_TRIP)


def api_photo_review(conn, _q, _b) -> PhotoReview:
    return photos.needs_a_look(conn, _viewer(conn))


def api_photo_decide(conn, _q, body: PhotoBody, photo_id) -> TripPhoto:
    who, this = _viewer(conn), row_id(photo_id, NO_PHOTO)
    if isinstance(body.get("trip_id"), bool):
        raise ApiError(NOT_A_TRIP)
    trip = _v.integer(body.get("trip_id"), "trip", 1, MAX_ID)
    excluded = _flag(body, "excluded")
    if (trip is None and not excluded) or "hidden" in body:
        raise ApiError(NOTHING_TO_DO)
    try:
        return _run(lambda: photos.decide(conn, who, this, trip, excluded), NO_PHOTO)
    except photos.OutsideWindow as e:
        raise ApiError(str(e), 409) from None


def api_photo_sharing(conn, q, _b, trip_id) -> PhotoSharing:
    who, trip = _viewer(conn), row_id(trip_id, NO_TRIP)
    person = _person(conn, who, (q.get("person_id") or [None])[0])
    return _sharing(lambda: photogrants.state_of(conn, who, person, trip))


def api_photo_sharing_set(conn, _q, body: PhotoSharingBody, trip_id) -> PhotoSharing:
    who, trip = _viewer(conn), row_id(trip_id, NO_TRIP)
    person, scope, declined = _person(conn, who, body.get("person_id")), _scope(body), _flag(body, "declined")
    if scope is None and not declined:
        raise ApiError(NOTHING_TO_SHARE)
    if declined:
        return _sharing(lambda: photogrants.decline(conn, who, person, trip))
    return _sharing(lambda: photogrants.grant(conn, who, person, trip, scope or photos.ONLY_ME))


def api_photo_sharing_stop(conn, q, _b, trip_id) -> PhotoSharing:
    who, trip = _viewer(conn), row_id(trip_id, NO_TRIP)
    person = _person(conn, who, (q.get("person_id") or [None])[0])
    return _sharing(lambda: photogrants.stop(conn, who, person, trip))


def _seen(conn, who: Viewer, trip: int) -> None:
    _sharing(lambda: photogrants.state_of(conn, who, _person(conn, who, None), trip))


def api_photo_exclude(conn, _q, body: PhotoExclusionsBody, trip_id) -> PhotoSharing:
    who, trip = _viewer(conn), row_id(trip_id, NO_TRIP)
    ids = body.get("photo_ids")
    if not isinstance(ids, list) or not ids or len(ids) > MAX_REMOVED or any(isinstance(i, bool) or not isinstance(i, int) or i < 1 for i in ids):
        raise ApiError(NOT_IDS)
    _seen(conn, who, trip)
    return _run(lambda: photogrants.exclude(conn, who, trip, ids), NO_PHOTO)


def api_photo_put_back(conn, _q, _b, trip_id, photo_id) -> PhotoSharing:
    who, trip, this = _viewer(conn), row_id(trip_id, NO_TRIP), row_id(photo_id, NO_PHOTO)
    _seen(conn, who, trip)
    return _run(lambda: photogrants.put_back(conn, who, trip, this), NO_PHOTO)


def api_photo_grants(conn, _q, _b) -> PhotoGrants:
    return photogrants.grants(conn, _viewer(conn))


def api_photo_prefs_set(conn, _q, body: PhotoPrefsBody, person_id) -> PhotoPrefs:
    who, person = _viewer(conn), row_id(person_id, NO_TRIP)
    scope = body.get("default_scope")
    if scope is not None and scope not in photos.SCOPES:
        raise ApiError('Send "default_scope" as "only_me" or "trip"')
    share_all = _flag(body, "share_all")
    if scope is None and share_all is None:
        raise ApiError('Send "default_scope" or "share_all"')
    return _run(lambda: photogrants.set_prefs(conn, who, person, scope, share_all), NO_TRIP)
