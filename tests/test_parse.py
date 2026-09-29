from __future__ import annotations

import pathlib

import pytest

import pyflp
from pyflp._events import EventEnum, UnknownDataEvent
from pyflp.exceptions import InvalidEventChunkSize
from pyflp.project import FLVersion

from .synthetic import ascii_text, event, u8, u16, u32, utf16_text, write

# The head of a project saved by FL Studio 25.2.4: event 172 carries 3 bytes
# although its ID lies in the 4 byte (DWORD) range. Text event 192 follows it.
FL_25_2_4_HEAD = (
    ascii_text(199, "25.2.4.4960"),
    u32(159, 4960),
    u32(169, 7),
    u8(28, 1),
    event(172, b"\x01\x01\x00"),
    utf16_text(192, "FL Studio 25.2.4.4960.4960"),
    u8(37, 2),
    u32(156, 140000),
    u16(67, 1),
    u8(9, 0),
    u16(64, 0),  # ChannelID.New: save() writes the channel count to the header
)


def test_event_172_is_3_bytes(tmp_path: pathlib.Path):
    path = write(tmp_path, *FL_25_2_4_HEAD, channel_count=1)
    project = pyflp.parse(path)

    assert project.version == FLVersion(25, 2, 4, 4960)
    assert project.tempo == 140.0
    assert [int(e.id) for e in project.events] == [199, 159, 169, 28, 172, 192, 37, 156, 67, 9, 64]

    ev172 = project.events.first(EventEnum(172))
    assert isinstance(ev172, UnknownDataEvent)
    assert ev172.value == b"\x01\x01\x00"
    assert ev172.size == 4
    assert project.events.first(EventEnum(192)).value == "FL Studio 25.2.4.4960.4960"


def test_event_172_saves_byte_identical(tmp_path: pathlib.Path):
    path = write(tmp_path, *FL_25_2_4_HEAD, channel_count=1)
    pyflp.save(pyflp.parse(path), tmp_path / "saved.flp")
    assert (tmp_path / "saved.flp").read_bytes() == path.read_bytes()


def test_event_172_size_is_checked():
    with pytest.raises(InvalidEventChunkSize, match="3"):
        UnknownDataEvent(EventEnum(172), b"\x01\x01\x00\x00")


def test_invalid_utf16_text_does_not_stop_parsing(tmp_path: pathlib.Path):
    comments = "Mix: 🙈\rMaster: \ud83d!\0".encode("utf-16-le", "surrogatepass")
    path = write(tmp_path, *FL_25_2_4_HEAD, event(195, comments), channel_count=1)

    with pytest.warns(UnicodeWarning, match="invalid UTF-16"):
        project = pyflp.parse(path)
    assert project.comments == "Mix: 🙈\rMaster: \ufffd!"
    assert project.tempo == 140.0

    pyflp.save(project, tmp_path / "saved.flp")
    assert (tmp_path / "saved.flp").read_bytes() == path.read_bytes()
