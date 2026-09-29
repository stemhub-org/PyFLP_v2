"""Builds synthetic FLP byte streams, so tests need no FL Studio project files.

Events are written in one of two ways. :func:`event` and the helpers built on it
(:func:`u8`, :func:`ascii_text`, ...) serialise whole events, which :func:`flp` and
:func:`write` put in a project. :func:`flp_bytes` takes ``(id, payload)`` pairs
(:data:`RawEvent`) instead, payloads made by the ``pack_*`` helpers, and writes the
version event first.
"""

from __future__ import annotations

import pathlib
import struct
from typing import Iterable, Tuple

import construct as c

import pyflp
from pyflp import Project
from pyflp._events import TEXT

RawEvent = Tuple[int, bytes]


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


def pack_u8(value: int) -> bytes:
    return struct.pack("<B", value)


def pack_u16(value: int) -> bytes:
    return struct.pack("<H", value)


def pack_i32(value: int) -> bytes:
    return struct.pack("<i", value)


def pack_text(value: str) -> bytes:
    """A string event payload (UTF-16 since FL Studio 11.5)."""
    return (value + "\0").encode("utf-16-le")


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


def mixer_param(key: int, slot: int, id: int, kind: int, value: int) -> bytes:
    """One 12-byte item of ``MixerID.Params``; ``key`` is ``channel_data >> 6``."""
    return struct.pack("<IBBHi", 0, id, kind, (key << 6) | slot, value)


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


def flp_bytes(
    events: Iterable[RawEvent], *, version: str = "25.2.0.5098", channel_count: int = 0
) -> bytes:
    """Serialises ``events`` as a project file saved by FL Studio ``version``."""
    serialised = (event(id, payload) for id, payload in events)
    return flp(ascii_text(199, version), *serialised, channel_count=channel_count)


def parse(tmp_path: pathlib.Path, data: bytes) -> Project:
    file = tmp_path / "synthetic.flp"
    file.write_bytes(data)
    return pyflp.parse(file)
