"""Who got a booking's confirmation in their own mailbox (`segment_recipients`), and a one-time merge of the duplicates the
mail scan made before it matched across the household: segments of the same kind, confirmation code and leg (the same
flight number however it was written, the same places, a start within three days) become the oldest one of them, with the
travellers of all, any fields a person edited and the worst status, and the people who booked or were on the others still
see it (as travellers or recipients). Nothing else refers to a segment by id except travellers, which are moved first
(scanned messages and review items hold a mailbox and a message id only).

Revision ID: 0010
Revises: 0009
"""
import json
import re
from datetime import date

import sqlalchemy as sa
from alembic import op

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None

NEAR_DAYS = 3
SUFFIXES = {"inc", "incorporated", "ltd", "limited", "llc", "plc", "corp", "corporation", "co", "company", "gmbh", "ag", "sa", "bv"}
FLIGHT = re.compile(r"([A-Z0-9]{2,3}?)0*(\d{1,4}[A-Z]?)")
# The columns a person's edit can lock, as the app names them (waypoint/domain/trips.py FIELDS), but travellers.
COLUMNS = ("kind", "status", "confirmation", "provider", "start_local", "start_zone", "end_local", "end_zone", "origin",
           "destination", "details", "manage_url")
WORST = {"confirmed": 0, "changed": 1, "cancelled": 2}


def upgrade() -> None:
    op.create_table(
        'segment_recipients',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('segment_id', sa.Integer(), sa.ForeignKey('segments.id', name='fk_segment_recipients_segment_id', ondelete='CASCADE',
                                                             deferrable=True, initially='IMMEDIATE'), nullable=False),
        sa.Column('person_id', sa.Integer(), sa.ForeignKey('people.id', name='fk_segment_recipients_person_id', ondelete='CASCADE',
                                                            deferrable=True, initially='IMMEDIATE'), nullable=False),
        sa.UniqueConstraint('segment_id', 'person_id', name='uq_segment_recipients_segment_person'),
    )
    op.create_index('ix_segment_recipients_person_id', 'segment_recipients', ['person_id'])
    merge_duplicates(op.get_bind())


def downgrade() -> None:   # (the merged segments stay merged)
    op.drop_index('ix_segment_recipients_person_id', table_name='segment_recipients')
    op.drop_table('segment_recipients')


# ------------------------------------------------------------------------------------------------ the one-time merge

def _flight(number):
    n = re.sub(r"[\s-]", "", number or "").upper()
    found = FLIGHT.fullmatch(n)
    return f"{found.group(1)}{found.group(2)}" if found else None


def _company(name):
    words = re.sub(r"[^\w\s]", " ", (name or "").casefold()).split()
    while len(words) > 1 and words[-1] in SUFFIXES:
        words.pop()
    return " ".join(words)


def _text(value):
    return " ".join((value or "").split()).casefold()


def _json(raw, empty):
    try:
        found = json.loads(raw) if raw else empty
    except ValueError:
        return empty
    return found if isinstance(found, type(empty)) else empty


def _same_leg(a, b):
    na, nb = _flight(_json(a["details"], {}).get("flight_number")), _flight(_json(b["details"], {}).get("flight_number"))
    near = abs((date.fromisoformat(a["start_local"][:10]) - date.fromisoformat(b["start_local"][:10])).days) <= NEAR_DAYS
    providers = bool(na and nb) or not a["provider"] or not b["provider"] or _company(a["provider"]) == _company(b["provider"])
    return (near and a["kind"] == b["kind"] and (not na or not nb or na == nb) and providers
            and _text(a["origin"]) == _text(b["origin"]) and _text(a["destination"]) == _text(b["destination"]))


def merge_duplicates(conn) -> int:
    """Fold each duplicate segment into the oldest of its leg. Returns how many were folded."""
    meta = sa.MetaData()
    segments, travelers, trips, recipients = (sa.Table(n, meta, autoload_with=conn)
                                              for n in ('segments', 'segment_travelers', 'trips', 'segment_recipients'))
    rows = [dict(r._mapping) for r in conn.execute(sa.select(segments).where(segments.c.confirmation.is_not(None)).order_by(segments.c.id))]
    kept: list[dict] = []
    folded = 0
    for row in rows:
        code = re.sub(r"\s+", "", row["confirmation"] or "").casefold()
        if not code:
            continue
        keep = next((k for k in kept if k["code"] == code and _same_leg(k["row"], row)), None)
        if keep is None:
            kept.append({"code": code, "row": row})
            continue
        _fold(conn, segments, travelers, trips, recipients, keep["row"], row)
        folded += 1
    return folded


def _fold(conn, segments, travelers, trips, recipients, keep, dup) -> None:
    locked_keep, locked_dup = _json(keep["locked_fields"], []), _json(dup["locked_fields"], [])
    changes: dict = {}
    for f in COLUMNS:   # (a field only the duplicate's person edited keeps their edit; one locked on both stays the oldest's)
        if f in locked_dup and f not in locked_keep:
            changes[f] = dup[f]
    if "status" not in locked_keep and "status" not in changes and WORST.get(dup["status"], 0) > WORST.get(keep["status"], 0):
        changes["status"] = dup["status"]
    if locked_dup:
        changes["locked_fields"] = json.dumps(sorted(set(locked_keep) | set(locked_dup)))
    if changes:
        conn.execute(sa.update(segments).where(segments.c.id == keep["id"]).values(**changes))
        keep.update(changes)
    have = [dict(r._mapping) for r in conn.execute(sa.select(travelers).where(travelers.c.segment_id == keep["id"]))]
    for t in conn.execute(sa.select(travelers).where(travelers.c.segment_id == dup["id"]).order_by(travelers.c.id)):
        same = any((t.person_id is not None and h["person_id"] == t.person_id)
                   or (t.person_id is None and h["person_id"] is None and _text(h["name"]) == _text(t.name)) for h in have)
        if not same:
            conn.execute(sa.insert(travelers).values(segment_id=keep["id"], person_id=t.person_id, name=t.name))
            have.append({"person_id": t.person_id, "name": t.name})
    # Whoever booked the duplicate still sees the booking: it was in their mailbox.
    if dup["booked_by"] is not None and dup["booked_by"] != keep["booked_by"] \
            and not any(h["person_id"] == dup["booked_by"] for h in have):
        conn.execute(sa.insert(recipients).values(segment_id=keep["id"], person_id=dup["booked_by"]))
    for r in conn.execute(sa.select(recipients.c.person_id).where(recipients.c.segment_id == dup["id"])).all():
        if not conn.execute(sa.select(recipients.c.id).where(recipients.c.segment_id == keep["id"], recipients.c.person_id == r.person_id)).first():
            conn.execute(sa.insert(recipients).values(segment_id=keep["id"], person_id=r.person_id))
    conn.execute(sa.delete(travelers).where(travelers.c.segment_id == dup["id"]))
    conn.execute(sa.delete(recipients).where(recipients.c.segment_id == dup["id"]))
    conn.execute(sa.delete(segments).where(segments.c.id == dup["id"]))
    if dup["trip_id"] != keep["trip_id"] and not conn.execute(sa.select(segments.c.id).where(segments.c.trip_id == dup["trip_id"])).first():
        conn.execute(sa.delete(trips).where(trips.c.id == dup["trip_id"], trips.c.auto.is_(True)))
