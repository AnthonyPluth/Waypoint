# Every provider module (waypoint/providers/) takes the day it's given, as the mail scan does.
from datetime import date


def sync(conn, today=None):
    # ok: waypoint-today-in-jobs
    today = today or date.today()
    return today


def statement(conn):
    # ruleid: waypoint-today-in-jobs
    return date.today()
