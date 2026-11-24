from __future__ import annotations

import pathlib

import pytest

import pyflp
from pyflp._events import (
    EXTENDED_ID,
    FL_STUDIO_TEXT,
    EventEnum,
    UnicodeEvent,
    UnknownDataEvent,
    fixed_size,
)
from pyflp.exceptions import EventIDOutOfRange, InvalidEventChunkSize
from pyflp.project import FLVersion, ProjectID

from .synthetic import ascii_text, event, event_id, flp, u8, u16, u32, utf16_text, write

# The head of a project saved by FL Studio 25.2.4. Its second event is the extended event
# 0xC0000101: byte 0xAC, the ID as a u32, then a length-prefixed text, "FL Studio <version>".
FL_25_2_4_HEAD = (
    ascii_text(199, "25.2.4.4960"),
    u32(159, 4960),
    u32(169, 7),
    u8(28, 1),
    utf16_text(FL_STUDIO_TEXT, "FL Studio 25.2.4.4960.4960"),
    u8(37, 2),
    u32(156, 140000),
    u16(67, 1),
    u8(9, 0),
    u16(64, 0),  # ChannelID.New: save() writes the channel count to the header
)
HEAD_IDS = [199, 159, 169, 28, FL_STUDIO_TEXT, 37, 156, 67, 9, 64]

# What FL Studio 26.1.7 writes after the (empty) comments: the 1 byte extended event 0x100.
FL_26_AFTER_COMMENTS = (event(195, b"\0\0"), event(0x100, b"\0"), event(237, bytes(16)))


def test_the_fl_studio_text_is_written_as_fl_studio_writes_it():
    # The bytes of a real FL Studio 25.2.4 project, which PyFLP used to read as a 3 byte
    # event 172 then a text event 192.
    assert FL_25_2_4_HEAD[4][:6] == bytes.fromhex("ac010100c036")
    assert event(0x100, b"\0") == bytes.fromhex("ac0001000000")  # FL Studio 26.1.7


def test_an_extended_id_is_read_after_0xac(tmp_path: pathlib.Path):
    path = write(tmp_path, *FL_25_2_4_HEAD, channel_count=1)
    project = pyflp.parse(path)

    assert project.version == FLVersion(25, 2, 4, 4960)
    assert project.tempo == 140.0
    assert [int(e.id) for e in project.events] == HEAD_IDS

    text = project.events.first(ProjectID.FLStudio)
    assert isinstance(text, UnicodeEvent)
    assert text.value == "FL Studio 25.2.4.4960.4960"
    assert text.size == 5 + 1 + 54  # 0xAC + u32 ID, length, UTF-16 text


def test_an_fl_studio_26_project_reads_and_saves_back(tmp_path: pathlib.Path):
    path = write(tmp_path, *FL_25_2_4_HEAD, *FL_26_AFTER_COMMENTS, channel_count=1)
    project = pyflp.parse(path)

    assert [int(e.id) for e in project.events] == [*HEAD_IDS, 195, 0x100, 237]
    ev256 = project.events.first(EventEnum(0x100))
    assert isinstance(ev256, UnknownDataEvent)
    assert ev256.value == b"\0"
    assert ev256.size == 6
    assert project.tempo == 140.0

    pyflp.save(project, tmp_path / "saved.flp")
    assert (tmp_path / "saved.flp").read_bytes() == path.read_bytes()


def test_extended_events_save_byte_identical(tmp_path: pathlib.Path):
    path = write(tmp_path, *FL_25_2_4_HEAD, channel_count=1)
    pyflp.save(pyflp.parse(path), tmp_path / "saved.flp")
    assert (tmp_path / "saved.flp").read_bytes() == path.read_bytes()


@pytest.mark.parametrize(
    ("id", "size"),
    [
        (0, 1),
        (63, 1),
        (64, 2),
        (127, 2),
        (128, 4),
        (191, 4),
        (192, None),
        (255, None),
        # an extended ID's top 4 bits give its size, as the ranges do for one byte IDs
        (0x100, 1),
        (0x0FFFFFFF, 1),
        (0x40000000, 2),
        (0x80000000, 4),
        (FL_STUDIO_TEXT, None),
        (0xCFFFFFFF, None),
        # FL Studio reads no data for the other top bits; no project seen holds one
        (0x10000000, 0),
        (0xFFFFFFFF, 0),
    ],
)
def test_fixed_size(id: int, size: int | None):
    assert fixed_size(id) == size


def test_an_extended_id_without_data_keeps_the_stream_in_step(tmp_path: pathlib.Path):
    # Top 4 bits 1: FL Studio reads no data. Reading 0xAC as 3 bytes then a one byte ID
    # took the tempo's ID as the data of event 16 and lost the tempo.
    path = write(
        tmp_path, *FL_25_2_4_HEAD[:4], event(0x10000000, b""), *FL_25_2_4_HEAD[4:], channel_count=1
    )
    project = pyflp.parse(path)

    assert [int(e.id) for e in project.events] == [*HEAD_IDS[:4], 0x10000000, *HEAD_IDS[4:]]
    assert project.tempo == 140.0
    pyflp.save(project, tmp_path / "saved.flp")
    assert (tmp_path / "saved.flp").read_bytes() == path.read_bytes()


@pytest.mark.parametrize(
    ("data", "error"),
    [
        pytest.param(bytes([EXTENDED_ID, 1, 1]), InvalidEventChunkSize, id="extended ID cut"),
        pytest.param(event_id(0x80000000) + b"\1\2", InvalidEventChunkSize, id="extended data cut"),
        pytest.param(
            bytes([EXTENDED_ID]) + (156).to_bytes(4, "little") + bytes(4),
            EventIDOutOfRange,
            id="ID below 256",
        ),
    ],
)
def test_malformed_extended_ids_raise(tmp_path: pathlib.Path, data: bytes, error: type):
    path = tmp_path / "bad.flp"
    path.write_bytes(flp(ascii_text(199, "25.2.4.4960"), data))

    with pytest.raises(error):
        pyflp.parse(path)


def test_no_event_has_the_escape_id():
    # FL Studio would read 0xAC back as the start of an extended ID.
    with pytest.raises(EventIDOutOfRange):
        UnknownDataEvent(EventEnum(EXTENDED_ID), b"\x01\x01\x00\x00")


def test_invalid_utf16_text_does_not_stop_parsing(tmp_path: pathlib.Path):
    comments = "Mix: 🙈\rMaster: \ud83d!\0".encode("utf-16-le", "surrogatepass")
    path = write(tmp_path, *FL_25_2_4_HEAD, event(195, comments), channel_count=1)

    with pytest.warns(UnicodeWarning, match="invalid UTF-16"):
        project = pyflp.parse(path)
    assert project.comments == "Mix: 🙈\rMaster: \ufffd!"
    assert project.tempo == 140.0

    pyflp.save(project, tmp_path / "saved.flp")
    assert (tmp_path / "saved.flp").read_bytes() == path.read_bytes()
