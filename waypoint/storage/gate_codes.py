from __future__ import annotations

import base64
import binascii
import hashlib
import json
import struct
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any, Literal, NamedTuple

from sqlalchemy import delete, exists, or_, select, update

from . import db, secretbox
from .models import Segment, SegmentCode, SegmentMessage, StoredMessage
from .stored_mail import Image, _images, _parsed

KIND = "parking"
MIN_SIDE = 100
MAX_SIDE = 1000
SQUARE_WITHIN = 0.1

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_FRAMES = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}

State = Literal["ready", "choose"]


def dimensions(data: bytes) -> tuple[int, int] | None:
    if data.startswith(PNG_MAGIC) and data[12:16] == b"IHDR" and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return width, height
    if data[:2] == b"\xff\xd8":
        at = 2
        while at + 4 <= len(data):
            if data[at] != 0xFF:
                at += 1
                continue
            marker = data[at + 1]
            if marker == 0xFF:
                at += 1
                continue
            if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:
                at += 2
                continue
            if marker == 0xD9:
                return None
            length = struct.unpack(">H", data[at + 2:at + 4])[0]
            if marker in JPEG_FRAMES:
                if at + 9 > len(data):
                    return None
                height, width = struct.unpack(">HH", data[at + 5:at + 9])
                return width, height
            at += 2 + length
    return None


def looks_like_a_code(data: bytes) -> bool:
    found = dimensions(data)
    if found is None:
        return False
    width, height = found
    if not (MIN_SIDE <= width <= MAX_SIDE and MIN_SIDE <= height <= MAX_SIDE):
        return False
    return width <= height and height - width <= SQUARE_WITHIN * height


def qualifying(images: Sequence[Image]) -> list[int]:
    seen = Counter(hashlib.sha256(i["data"]).digest() for i in images if i["data"])
    return [n for n, i in enumerate(images) if i["data"] and seen[hashlib.sha256(i["data"]).digest()] == 1 and looks_like_a_code(i["data"])]


def _sealed(image: Image) -> str:
    return secretbox.encrypt(json.dumps({"type": image["type"], "data": base64.b64encode(image["data"]).decode("ascii")}, separators=(",", ":"))) or ""


def _unsealed(value: str | None) -> Image | None:
    found = _parsed(value)
    if found is None:
        return None
    try:
        data = base64.b64decode(found["data"], validate=True)
    except (KeyError, TypeError, ValueError, binascii.Error):
        return None
    return {"type": str(found.get("type") or ""), "data": data} if data and found.get("type") else None


def _replaces(day: str | None, held: str | None) -> bool:
    return held is None or (day is not None and day > held)


def is_parking(conn: db.Connection, segment_id: int) -> bool:
    return conn.execute(select(Segment.kind).where(Segment.id == segment_id)).scalar() == KIND


def _set(conn: db.Connection, segment_id: int, mailbox_id: int, image: Image | None, day: str | None, now: float,
         opener: int | None = None) -> None:
    db.upsert(conn, SegmentCode, {"segment_id": segment_id, "mailbox_id": mailbox_id, "content": _sealed(image) if image else None,
                                  "day": day, "created": now, "opened_by": opener if image is None else None},
              key=["segment_id"], update=["mailbox_id", "content", "day", "created", "opened_by"])


def _open_choice(conn: db.Connection, segment_id: int, mailbox_id: int, day: str | None, now: float, opener: int | None) -> bool:
    first = (db.dialect_insert(conn, SegmentCode)
             .values(segment_id=segment_id, mailbox_id=mailbox_id, content=None, day=day, created=now, opened_by=opener)
             .on_conflict_do_nothing(index_elements=["segment_id"]).returning(SegmentCode.segment_id))
    if conn.execute(first).fetchone() is not None:
        return True
    if day is None:
        return False
    return int(conn.execute(update(SegmentCode).where(SegmentCode.segment_id == segment_id, SegmentCode.content.is_(None),
                                                      or_(SegmentCode.day.is_(None), SegmentCode.day < day))
                            .values(mailbox_id=mailbox_id, opened_by=opener, day=day, created=now)).rowcount) == 1


def offer(conn: db.Connection, segment_id: int, mailbox_id: int, images: Sequence[Image], day: str | None, now: float,
          opener: int | None = None) -> bool:
    if not is_parking(conn, segment_id):
        return False
    fits = qualifying(images)
    if not fits:
        return False
    if len(fits) > 1:
        return _open_choice(conn, segment_id, mailbox_id, day, now, opener)
    held = conn.execute(select(SegmentCode.content, SegmentCode.day).where(SegmentCode.segment_id == segment_id)).fetchone()
    if held is not None and held["content"] is not None and not _replaces(day, held["day"]):
        return False
    _set(conn, segment_id, mailbox_id, images[fits[0]], day, now)
    return True


def offer_stored(conn: db.Connection, segment_id: int, stored_message_id: int) -> bool:
    if not is_parking(conn, segment_id):
        return False
    row = conn.execute(select(StoredMessage.mailbox_id, StoredMessage.content, StoredMessage.created).where(StoredMessage.id == stored_message_id)).fetchone()
    found = _parsed(row["content"]) if row else None
    if row is None or found is None:
        return False
    received = found.get("received")
    return offer(conn, segment_id, int(row["mailbox_id"]), _images(found.get("images")), received if isinstance(received, str) else None,
                 float(row["created"]), stored_message_id)


def _emails_of(conn: db.Connection, segment_id: int) -> list[tuple[int, dict[str, Any]]]:
    rows = conn.execute(select(StoredMessage.mailbox_id, StoredMessage.content).join(SegmentMessage, SegmentMessage.stored_message_id == StoredMessage.id)
                        .where(SegmentMessage.segment_id == segment_id).order_by(StoredMessage.created.desc(), StoredMessage.id.desc())).fetchall()
    opened = [(int(r["mailbox_id"]), _parsed(r["content"])) for r in rows]
    return [(box, found) for box, found in opened if found is not None]


def choose(conn: db.Connection, segment_id: int, email: int, index: int, now: float) -> bool:
    if not is_parking(conn, segment_id):
        return False
    emails = _emails_of(conn, segment_id)
    if not 0 <= email < len(emails):
        return False
    mailbox_id, found = emails[email]
    pictures = _images(found.get("images"))
    if not 0 <= index < len(pictures) or not pictures[index]["data"]:
        return False
    received = found.get("received")
    _set(conn, segment_id, mailbox_id, pictures[index], received if isinstance(received, str) else None, now)
    return True


def waiting(conn: db.Connection, segment_id: int) -> bool:
    if not is_parking(conn, segment_id):
        return False
    row = conn.execute(select(SegmentCode.content).where(SegmentCode.segment_id == segment_id)).fetchone()
    return row is not None and row["content"] is None


class Candidate(NamedTuple):
    stored_id: int
    mailbox_id: int
    position: int
    image: Image
    day: str | None


def keep_chosen(conn: db.Connection, segment_id: int, mailbox_id: int, image: Image, day: str | None, now: float) -> bool:
    if not image["data"]:
        return False
    permits = SegmentCode.day.is_(None) if day is None else or_(SegmentCode.day.is_(None), SegmentCode.day <= day)
    done = conn.execute(update(SegmentCode).where(SegmentCode.segment_id == segment_id, SegmentCode.content.is_(None), permits,
                                                  exists().where(Segment.id == SegmentCode.segment_id, Segment.kind == KIND))
                        .values(mailbox_id=mailbox_id, content=_sealed(image), day=day, created=now))
    return int(done.rowcount) == 1


def stored_id(conn: db.Connection, mailbox_id: int, message_id: str) -> int | None:
    found = conn.execute(select(StoredMessage.id).where(StoredMessage.mailbox_id == mailbox_id, StoredMessage.message_id == message_id)).scalar()
    return None if found is None else int(found)


def candidates(conn: db.Connection, segment_id: int, stored: int) -> list[Candidate]:
    if not waiting(conn, segment_id):
        return []
    row = conn.execute(select(StoredMessage.mailbox_id, StoredMessage.content).join(SegmentMessage, SegmentMessage.stored_message_id == StoredMessage.id)
                       .where(SegmentMessage.segment_id == segment_id, StoredMessage.id == stored)).fetchone()
    found = _parsed(row["content"]) if row else None
    if row is None or found is None:
        return []
    received = found.get("received")
    pictures = _images(found.get("images"))
    return [Candidate(stored, int(row["mailbox_id"]), n, pictures[n], received if isinstance(received, str) else None) for n in qualifying(pictures)]


def keep_candidate(conn: db.Connection, segment_id: int, picked: Candidate, now: float) -> bool:
    digest = hashlib.sha256(picked.image["data"]).digest()
    same = [c for c in candidates(conn, segment_id, picked.stored_id)
            if c.position == picked.position and hashlib.sha256(c.image["data"]).digest() == digest]
    return bool(same) and keep_chosen(conn, segment_id, same[0].mailbox_id, same[0].image, same[0].day, now)


def opens_choice(conn: db.Connection, segment_id: int, stored_message_id: int | None) -> bool:
    if stored_message_id is None:
        return False
    return conn.execute(select(SegmentCode.segment_id).where(SegmentCode.segment_id == segment_id, SegmentCode.content.is_(None),
                                                              SegmentCode.opened_by == stored_message_id,
                                                              exists().where(Segment.id == SegmentCode.segment_id, Segment.kind == KIND))).fetchone() is not None


def opens_unstored(conn: db.Connection, segment_id: int, day: str | None) -> bool:
    return conn.execute(select(SegmentCode.segment_id).where(SegmentCode.segment_id == segment_id, SegmentCode.content.is_(None),
                                                              SegmentCode.opened_by.is_(None),
                                                              SegmentCode.day.is_(None) if day is None else SegmentCode.day == day,
                                                              exists().where(Segment.id == SegmentCode.segment_id, Segment.kind == KIND))).fetchone() is not None


def image_for(conn: db.Connection, segment_id: int) -> Image | None:
    return _unsealed(conn.execute(select(SegmentCode.content).where(SegmentCode.segment_id == segment_id)).scalar())


def states(conn: db.Connection, segment_ids: Iterable[int]) -> dict[int, tuple[State, str | None]]:
    ids = sorted(set(segment_ids))
    if not ids:
        return {}
    rows = conn.execute(select(SegmentCode.segment_id, SegmentCode.content, SegmentCode.day).where(SegmentCode.segment_id.in_(ids))).fetchall()
    return {int(r["segment_id"]): ("ready" if r["content"] else "choose", r["day"]) for r in rows}


def clear_for_segments(conn: db.Connection, segment_ids: Iterable[int]) -> int:
    ids = sorted(set(segment_ids))
    return int(conn.execute(delete(SegmentCode).where(SegmentCode.segment_id.in_(ids))).rowcount) if ids else 0
