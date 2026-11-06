from __future__ import annotations

from ... import validate
from ...domain import photos
from ..common import ApiError, row_id
from ..contract import PhotoBody, PhotoReview, TripPhoto, TripPhotos
from .trips import NO_TRIP, _run, viewer

NO_PHOTO = "No such photo"
NOTHING_TO_DO = 'Send "trip_id" to put the photo on a trip, or "hidden" to hide or show it'
MAX_ID = 10 ** 18
NOT_A_TRIP = "The trip must be a whole number"
_v = validate.Validator(ApiError, not_number=NOT_A_TRIP)


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
