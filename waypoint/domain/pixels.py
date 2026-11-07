from __future__ import annotations

import struct
import zlib

Color = tuple[int, int, int]

SIGNATURE = b"\x89PNG\r\n\x1a\n"
RGB = 2
GREY = 0


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(width: int, height: int, rows: bytes, color_type: int = RGB) -> bytes:
    return SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def gradient(width: int, height: int, top: Color, bottom: Color) -> bytes:
    rows = b"".join(b"\x00" + bytes(top[c] + (bottom[c] - top[c]) * y // max(height - 1, 1) for c in range(3)) * width for y in range(height))
    return png(width, height, rows)
