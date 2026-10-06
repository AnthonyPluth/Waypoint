from __future__ import annotations

from typing import Any

from ... import validate
from ...domain import flight_import, trips
from ..common import ApiError, row_id, upload
from ..contract import ImportBody, ImportPreview, ImportRow, Imported
from .trips import MAX_TRAVELERS, viewer

MAX_FILE = 5 * 1024 * 1024
UPLOAD_ROOM = 64 * 1024
MAX_FLIGHTS = 1000
_v = validate.Validator(ApiError, empty_file="Choose a CSV file exported from another app.",
                        file_too_large="That file is larger than {limit}.")


def _text(v: Any, label: str, limit: int) -> str | None:
    if v is not None and not isinstance(v, str):
        raise ApiError(f"Send the flight’s {label} as text")
    return _v.text(v, label, limit)


def _flight(item: Any) -> flight_import.FlightIn:
    if not isinstance(item, dict):
        raise ApiError('Send "flights" as a list of flights')
    flight: flight_import.FlightIn = {
        "day": _v.day(item.get("day"), "day", required=True),
        "origin": _text(item.get("origin"), "origin", 3) or "",
        "destination": _text(item.get("destination"), "destination", 3) or ""}
    for key, limit in (("flight_number", 12), ("airline", 100), ("start_local", 19), ("end_local", 19), ("seat", 10), ("cabin", 100)):
        if key in item:
            flight[key] = _text(item[key], key.replace("_", " "), limit)   # type: ignore[literal-required]
    return flight


@upload(MAX_FILE + UPLOAD_ROOM)
def api_import_preview(conn, _q, raw: bytes) -> ImportPreview:
    file = _v.file(raw, "file", MAX_FILE)
    try:
        parsed = flight_import.read(file)
    except flight_import.Unreadable as e:
        raise ApiError(str(e)) from None
    who = viewer(conn)
    return {"format": parsed.format, "me": who.person_id,
            "rows": [ImportRow(**r) for r in flight_import.preview(conn, who, parsed.rows)]}


def api_import(conn, _q, body: ImportBody) -> Imported:
    who = viewer(conn)
    items = body.get("flights")
    if not isinstance(items, list) or not items or len(items) > MAX_FLIGHTS:
        raise ApiError(f"Send between 1 and {MAX_FLIGHTS:,} flights at a time")
    flights = [_flight(i) for i in items]
    ids = body.get("person_ids")
    if ids is None:
        chosen = [who.person_id] if who.person_id is not None else []
    elif not isinstance(ids, list) or len(ids) > MAX_TRAVELERS:
        raise ApiError('Send "person_ids" as a list of people')
    else:
        chosen = [row_id(i, "Choose travellers from People", 400) for i in ids]
    if not chosen and not who.household:
        raise ApiError("Choose who was on these flights")
    try:
        done = flight_import.save(conn, who, flights, [{"person_id": p, "name": None} for p in chosen])
    except trips.Invalid as e:
        raise ApiError(str(e)) from None
    return {"added": done.added, "existing": done.existing}
