from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from .trips import PortIn, SegmentOut, TripOut, flight_groups, untimed

PRODID = "-//Waypoint//Trips//EN"
FOLD = 75
DETAILS = (("flight_number", "Flight"), ("terminal", "Terminal"), ("seat", "Seat"), ("cabin", "Cabin"), ("room", "Room"),
           ("car_class", "Car"), ("address", "Address"), ("phone", "Phone"), ("ship", "Ship"), ("deck", "Deck"))


def escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\n").replace("\r", "\n")
            .replace("\n", "\\n"))


def fold(line: str) -> str:
    out: list[str] = []
    current, size = "", 0
    for ch in line:
        n = len(ch.encode())
        if size + n > (FOLD if not out else FOLD - 1):
            out.append(current)
            current, size = "", 0
        current += ch
        size += n
    out.append(current)
    return "\r\n ".join(out)


def stamp(local: str) -> str:
    t = datetime.fromisoformat(local)
    return f"{t:%Y%m%dT%H%M%S}"


def _offset(t: datetime) -> str:
    total = int((t.utcoffset() or timedelta(0)).total_seconds())
    sign = "-" if total < 0 else "+"
    h, rest = divmod(abs(total), 3600)
    return f"{sign}{h:02d}{rest // 60:02d}"


def _at(zone: ZoneInfo, moment: datetime) -> datetime:
    return moment.astimezone(zone)


def _transition(zone: ZoneInfo, low: datetime, high: datetime) -> datetime:
    before = _at(zone, low).utcoffset()
    minute = timedelta(minutes=1)
    while (span := (high - low) // minute) > 1:
        mid = low + (span // 2) * minute
        if _at(zone, mid).utcoffset() == before:
            low = mid
        else:
            high = mid
    return high


def vtimezone(name: str, first: date, last: date) -> list[str]:
    zone = ZoneInfo(name)
    start = datetime(first.year, first.month, first.day, tzinfo=UTC) - timedelta(days=1)
    end = datetime(last.year, last.month, last.day, tzinfo=UTC) + timedelta(days=2)
    lines = ["BEGIN:VTIMEZONE", f"TZID:{name}"]

    def observance(onset_local: datetime, was: datetime, now: datetime) -> None:
        kind = "DAYLIGHT" if now.dst() else "STANDARD"
        lines.extend([f"BEGIN:{kind}", f"DTSTART:{onset_local:%Y%m%dT%H%M%S}", f"TZOFFSETFROM:{_offset(was)}",
                      f"TZOFFSETTO:{_offset(now)}", f"TZNAME:{escape(now.tzname() or name)}", f"END:{kind}"])

    here = _at(zone, start)
    observance(here.replace(tzinfo=None), here, here)
    t = start
    while t < end:
        nxt = min(t + timedelta(days=1), end)
        if _at(zone, nxt).utcoffset() != _at(zone, t).utcoffset():
            moment = _transition(zone, t, nxt)
            was, now = _at(zone, moment - timedelta(minutes=1)), _at(zone, moment)
            observance(was.replace(tzinfo=None) + timedelta(minutes=1), was, now)
        t = nxt
    lines.append("END:VTIMEZONE")
    return lines


def _title(seg: SegmentOut) -> str:
    where = " → ".join(p for p in (seg["origin"], seg["destination"]) if p)
    if seg["kind"] == "flight":
        number = seg["details"].get("flight_number")
        return " ".join(p for p in ("Flight", number, where) if p)
    if seg["kind"] == "hotel":
        return f"Hotel: {seg['origin']}" if seg["origin"] else "Hotel"
    if seg["kind"] == "car":
        return f"Car: {where}" if where else "Car"
    if seg["kind"] == "cruise":
        ship = seg["details"].get("ship")
        return " ".join(p for p in ("Cruise", f"({ship})" if ship else None, where) if p)
    return f"Train: {where}" if where else "Train"


def _clock(local: str) -> str:
    return stamp(local)[9:11] + ":" + stamp(local)[11:13]


def _description(group: Sequence[SegmentOut], trip: TripOut) -> str:
    seg = group[0]
    lines = [f"Trip: {trip['name']}"]
    if seg["provider"]:
        lines.append(seg["provider"])
    codes = [g["confirmation"] for g in group if g["confirmation"]]
    if len(group) > 1 and codes:
        lines.append(f"Confirmations: {', '.join(codes)}")
    elif codes:
        lines.append(f"Confirmation: {codes[0]}")
    live = [g for g in group if g["status"] != "cancelled" and not untimed(g["details"])]
    if len({(g["start_local"], g["end_local"]) for g in live}) > 1:
        lines.append("Times differ between bookings:")
        lines += [f"{g['confirmation'] or 'Booking'}: departs {_clock(g['start_local'])}, arrives {_clock(g['end_local'])}" for g in live]
    lines += [f"{label}: {seg['details'][key]}" for key, label in DETAILS if seg["details"].get(key) and key != "flight_number"]
    seated = [f"{t['name']} {t['seat']}" for g in group for t in g["travelers"] if t["seat"]]
    if seated:
        lines.append(f"Seats: {', '.join(dict.fromkeys(seated))}")
    if seg["itinerary"]:
        lines.append("Itinerary:")
        lines += [f"{p['name']}: {_stop(p)}" for p in seg["itinerary"]]
    for g in group:
        if g["manage_url"]:
            which = f" ({g['confirmation']})" if len(group) > 1 and g["confirmation"] else ""
            lines.append(f"Manage{which}: {g['manage_url']}")
    return "\n".join(lines)


def _stop(port: PortIn) -> str:
    parts = [f"{label} {at[:10]} {_clock(at)}" for label, at in (("arrives", port["arrive_local"]), ("leaves", port["depart_local"])) if at]
    return ", ".join(parts) or "in port"


def _times(seg: SegmentOut) -> list[str]:
    if untimed(seg["details"]):
        day = datetime.fromisoformat(seg["start_local"]).date()
        return [f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}"]
    return [f"DTSTART;TZID={seg['start_zone']}:{stamp(seg['start_local'])}", f"DTEND;TZID={seg['end_zone']}:{stamp(seg['end_local'])}"]


def _event(group: Sequence[SegmentOut], trip: TripOut, now: datetime) -> list[str]:
    seg = next((g for g in group if g["status"] != "cancelled"), group[0])
    lines = ["BEGIN:VEVENT", f"UID:segment-{group[0]['id']}@waypoint", f"DTSTAMP:{now.astimezone(UTC):%Y%m%dT%H%M%SZ}",
             *_times(seg),
             f"SUMMARY:{escape(_title(seg))}", f"DESCRIPTION:{escape(_description(group, trip))}"]
    place = (seg["details"].get("address") or seg["origin"]) if seg["kind"] in ("hotel", "car", "cruise") else None
    if place:
        lines.append(f"LOCATION:{escape(place)}")
    cancelled = all(g["status"] == "cancelled" for g in group)
    lines += [f"STATUS:{'CANCELLED' if cancelled else 'CONFIRMED'}", "END:VEVENT"]
    return lines


def feed(trips: Sequence[TripOut], now: datetime) -> str:
    pairs = [(group, trip) for trip in trips for group in flight_groups(trip["segments"])]
    spans: dict[str, tuple[date, date]] = {}
    for group, _trip in pairs:
        seg = next((g for g in group if g["status"] != "cancelled"), group[0])
        if untimed(seg["details"]):
            continue
        for zone, local in ((seg["start_zone"], seg["start_local"]), (seg["end_zone"], seg["end_local"])):
            day = datetime.fromisoformat(local).date()
            low, high = spans.get(zone, (day, day))
            spans[zone] = (min(low, day), max(high, day))
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "X-WR-CALNAME:Waypoint trips"]
    for zone in sorted(spans):
        lines += vtimezone(zone, *spans[zone])
    for group, trip in pairs:
        lines += _event(group, trip, now)
    lines.append("END:VCALENDAR")
    return "".join(fold(line) + "\r\n" for line in lines)
