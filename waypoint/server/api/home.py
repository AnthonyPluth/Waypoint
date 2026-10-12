from __future__ import annotations

from ...domain import home
from ..common import ApiError
from ..contract import Home, HomeBody


def api_home(conn, _q, _b) -> Home:
    return home.read(conn)


def api_home_save(conn, _q, body: HomeBody) -> Home:
    try:
        return home.save(conn, dict(body))
    except home.Invalid as e:
        raise ApiError(str(e)) from None


def api_home_clear(conn, _q, _b) -> Home:
    return home.clear(conn)
