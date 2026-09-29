"""Builds synthetic FLP byte streams, so tests need no FL Studio project files."""

from __future__ import annotations

import pathlib
import struct

import construct as c

from pyflp._events import TEXT


def event(id: int, data: bytes) -> bytes:
    """Serialises an event: fixed size data as is, from ``TEXT`` on length-prefixed."""
    if id >= TEXT:
        return bytes([id]) + c.VarInt.build(len(data)) + data
    return bytes([id]) + data


def u8(id: int, value: int) -> bytes:
    return event(id, struct.pack("<B", value))


def u16(id: int, value: int) -> bytes:
    return event(id, struct.pack("<H", value))


def u32(id: int, value: int) -> bytes:
    return event(id, struct.pack("<I", value))


def ascii_text(id: int, text: str) -> bytes:
    return event(id, (text + "\0").encode("ascii"))


def utf16_text(id: int, text: str) -> bytes:
    return event(id, (text + "\0").encode("utf-16-le"))


PATTERN_BASE = 20480


def playlist_item(
    size: int,
    *,
    position: int = 0,
    channel: int | None = None,
    pattern: int | None = None,
    length: int = 384,
    track: int = 0,
    flags: int = 0x40,
    offsets: tuple[float, float] = (-1, -1),
    uid: int = 1,
) -> bytes:
    """A playlist item (clip) of ``size`` bytes: 32 (FL <= 20.8), 60 or 80 (FL >= 24.2).

    Pattern clips store their offsets as int32 ticks, channel clips as float32.
    The tail of the 60 and 80 byte forms mimics what FL Studio writes.
    """
    index = channel if pattern is None else PATTERN_BASE + pattern
    assert index is not None
    item = struct.pack(
        "<IHHIHHHH", position, PATTERN_BASE, index, length, 499 - track, 0, 120, flags
    )
    item += bytes((64, 100, 128, 128))
    item += struct.pack("<ii" if pattern is not None else "<ff", *offsets)
    if size >= 60:
        item += struct.pack("<I", uid) + bytes(16) + struct.pack("<fI", 1.0, 0)
    if size >= 80:
        item += struct.pack("<fd", 0.0, 1.0) + bytes(8)
    assert len(item) == size
    return item


def flp(*events: bytes, channel_count: int = 0, ppq: int = 96) -> bytes:
    """An FLP file: header chunk, then a data chunk holding ``events``."""
    data = b"".join(events)
    header = struct.pack("<4sIh2H", b"FLhd", 6, 0, channel_count, ppq)
    return header + b"FLdt" + struct.pack("<I", len(data)) + data


def write(directory: pathlib.Path, *events: bytes, **kw: int) -> pathlib.Path:
    """Writes :func:`flp` of ``events`` to a file in ``directory``."""
    path = directory / "synthetic.flp"
    path.write_bytes(flp(*events, **kw))
    return path
