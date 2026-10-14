from __future__ import annotations

from ...domain import logos
from ..common import ApiError, Response, row_id
from .trips import NO_SEGMENT, viewer

NO_MEMBERSHIP = "No such membership"


def api_segment_logo(conn, _q, _b, segment_id) -> Response:
    found = logos.segment_logo(conn, viewer(conn), row_id(segment_id, NO_SEGMENT))
    if found is None:
        raise ApiError(NO_SEGMENT, 404)
    data, content_type = found
    return Response(data, content_type, cache="private, max-age=86400")


def api_loyalty_logo(conn, _q, _b, loyalty_id) -> Response:
    found = logos.membership_logo(conn, row_id(loyalty_id, NO_MEMBERSHIP))
    if found is None:
        raise ApiError(NO_MEMBERSHIP, 404)
    data, content_type = found
    return Response(data, content_type, cache="private, max-age=86400")
