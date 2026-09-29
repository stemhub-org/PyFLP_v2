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
