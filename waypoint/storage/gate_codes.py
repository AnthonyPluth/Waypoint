from __future__ import annotations

import base64
import binascii
import hashlib
import json
import struct
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any, Literal

from sqlalchemy import delete, select

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


def _set(conn: db.Connection, segment_id: int, mailbox_id: int, image: Image | None, day: str | None, now: float) -> None:
    db.upsert(conn, SegmentCode, {"segment_id": segment_id, "mailbox_id": mailbox_id, "content": _sealed(image) if image else None,
                                  "day": day, "created": now}, key=["segment_id"], update=["mailbox_id", "content", "day", "created"])


def offer(conn: db.Connection, segment_id: int, mailbox_id: int, images: Sequence[Image], day: str | None, now: float) -> bool:
    if not is_parking(conn, segment_id):
        return False
    fits = qualifying(images)
    if not fits:
        return False
    held = conn.execute(select(SegmentCode.content, SegmentCode.day).where(SegmentCode.segment_id == segment_id)).fetchone()
    if len(fits) > 1:
        if held is None:
            _set(conn, segment_id, mailbox_id, None, day, now)
            return True
        return False
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
    return offer(conn, segment_id, int(row["mailbox_id"]), _images(found.get("images")), received if isinstance(received, str) else None, float(row["created"]))


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
