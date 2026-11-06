from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ... import validate
from ...domain import photogrants, photos, photosources
from ...domain.photosources import Actor
from ...domain.visibility import Viewer
from ...providers import immich
from .. import jobs
from ..common import ApiError, _current, row_id
from ..contract import (Ok, PhotoBody, PhotoExclusionsBody, PhotoGrants, PhotoPrefs, PhotoPrefsBody, PhotoReview, PhotoSharing, PhotoSharingBody, PhotoSource,
                        PhotoSourceBody, PhotoSourceEdit, PhotoSourceNewTestBody, PhotoSources, PhotoSourceTest, PhotoSourceTestBody, SyncStarted, TripPhoto,
                        TripPhotos)
from .trips import NO_TRIP, _run, viewer

NO_PHOTO = "No such photo"
PHOTOS_OFF = "Photos need sign-in"
NOTHING_TO_DO = 'Send "trip_id" to put the photo on a trip, or "excluded" to leave it off'
NOTHING_TO_SHARE = 'Send "scope" to share, or "declined" for Not now'
MAX_ID = 10 ** 18
MAX_REMOVED = 500
NOT_A_TRIP = "The trip must be a whole number"
OFF = "Photos are off without sign-in."
BAD_URL = "The Immich address must be a web address, such as https://immich.local:2283, with no path or sign-in in it"
BAD_KEY = "Enter the API key as Immich shows it"
KEY_LIMIT = 512
LABEL_LIMIT = 100
NOTHING_TO_CHANGE = 'Send "key", "label" or "paused"'
FAILED = {immich.Refused: 400, immich.NotConfigured: 400, immich.RateLimited: 503, immich.Unavailable: 502}
REFUSALS = {photosources.NOT_YOURS: 403, photosources.OTHER_STEWARD: 403, photosources.ALREADY: 409, photosources.RESUME_ASKS: 409}
_v = validate.Validator(ApiError, not_number=NOT_A_TRIP, too_long="The {label} is too long (at most {limit} characters)")
NOT_A_PERSON = "The person must be a whole number"
NOT_A_SCOPE = 'Send "scope" as "only_me" or "trip"'
NOT_IDS = 'Send "photo_ids" as a list of whole numbers'
NOT_A_WINDOW = 'Send "window" as {"start": …, "end": …} text'
NOT_WINDOWS = 'Send "windows" as a map of trip ids to windows'
NOT_A_STAMP = 'Send "expected_changed" as a number'
NOT_AN_AUDIENCE = 'Send "audience" as a list of person ids'
NOT_AUDIENCES = 'Send "audiences" as a map of trip ids to lists of person ids'
NOT_SOURCES = 'Send "sources" as a list of {id, status}'
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
    try:
        return _run(make, NO_TRIP)
    except photogrants.Stale as e:
        raise ApiError(str(e), 409) from None


def _window(value: Any, label: str = "window") -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or any(not isinstance(value.get(k), str) for k in ("start", "end")):
        raise ApiError(NOT_A_WINDOW)
    return {"start": value["start"], "end": value["end"]}


def _stamp(value: Any, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(label)
    return float(value)


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
    except (photos.OutsideWindow, photos.Changed) as e:
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
    window, expected = _window(body.get("window")), _stamp(body.get("expected_changed"), NOT_A_STAMP)
    audience, sources = _ids(body.get("audience"), NOT_AN_AUDIENCE), _sources(body.get("sources"))
    if declined:
        return _sharing(lambda: photogrants.decline(conn, who, person, trip))
    return _sharing(lambda: photogrants.grant(conn, who, person, trip, scope or photos.ONLY_ME, window=window, expected_changed=expected,
                                              sources=sources, audience=audience, strict=True))


def _ids(value: Any, label: str) -> list[int] | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(isinstance(v, bool) or not isinstance(v, int) for v in value):
        raise ApiError(label)
    return [int(v) for v in value]


def _sources(value: Any) -> list[dict[str, object]] | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(s, dict) or isinstance(s.get("id"), bool) or not isinstance(s.get("id"), int)
                                          or not isinstance(s.get("status"), str) for s in value):
        raise ApiError(NOT_SOURCES)
    return [{"id": int(s["id"]), "status": str(s["status"])} for s in value]


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


def api_photo_put_back(conn, q, _b, trip_id, photo_id) -> PhotoSharing:
    who, trip, this = _viewer(conn), row_id(trip_id, NO_TRIP), row_id(photo_id, NO_PHOTO)
    given = (q.get("created") or [None])[0]
    try:
        created = float(given) if given is not None else None
    except ValueError:
        raise ApiError('Send "created" as a number') from None
    _seen(conn, who, trip)
    try:
        return _run(lambda: photogrants.put_back(conn, who, trip, this, created), NO_PHOTO)
    except photogrants.Stale as e:
        raise ApiError(str(e), 409) from None


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
    given = body.get("windows")
    if given is not None and not isinstance(given, dict):
        raise ApiError(NOT_WINDOWS)
    windows = {str(k): w for k, v in given.items() if (w := _window(v)) is not None} if given is not None else None
    heard = body.get("audiences")
    if heard is not None and not isinstance(heard, dict):
        raise ApiError(NOT_AUDIENCES)
    audiences = {str(k): a for k, v in heard.items() if (a := _ids(v, NOT_AUDIENCES)) is not None} if heard is not None else None
    sources = _sources(body.get("sources"))
    try:
        return _run(lambda: photogrants.set_prefs(conn, who, person, scope, share_all, windows=windows, sources=sources, audiences=audiences, strict=True), NO_TRIP)
    except photogrants.Stale as e:
        raise ApiError(str(e), 409) from None


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


def api_photo_source_test_new(conn, _q, body: PhotoSourceNewTestBody) -> PhotoSourceTest:
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
