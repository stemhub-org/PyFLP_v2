from __future__ import annotations

import datetime
import pathlib
import textwrap

import pytest

import pyflp
from pyflp.channel import ChannelID
from pyflp.mixer import InsertID, MixerID
from pyflp.project import VALID_PPQS, FileFormat, FLVersion, PanLaw, Project, ProjectID

from .synthetic import fl2024_channel, flp_bytes, pack_i32, pack_text, pack_u8, pack_u16, parse


def test_project(project: Project):
    assert project.artists == "demberto"
    assert project.channel_count == 19
    assert (
        project.comments
        == textwrap.dedent(
            """\
    This is a testing FLP used by PyFLP - An FL Studio project file parser.

    Notes for contributors:
    1. Make a separate item for every testable property (and its inverse if its a bool).
    2. Give item names related to the property they will be tested for.

    Terms:
    "item(s)": Refers to a channel, insert, slot, track, pattern, timemarker, etc.
    """
        ).replace("\n", "\r")
    )  # Who the hell uses \r?
    assert project.created_on == datetime.datetime(2022, 9, 16, 20, 47, 12, 746000)
    assert project.data_path == pathlib.Path("")
    assert project.format == FileFormat.Project
    assert project.genre == "Testing..."
    assert project.licensed
    assert project.licensee == "VIKTORKHLEBNIKOV38394416"
    assert project.looped
    assert project.main_pitch == 0
    assert project.main_volume is None
    assert project.pan_law == PanLaw.Circular
    assert project.ppq == 96
    assert project.show_info
    assert project.tempo == 69.420
    # ! assert project.time_spent == datetime.timedelta(hours=2, minutes=35, seconds=53)
    assert project.title == "PyFLP Test FLP"
    assert project.url == "https://github.com/demberto/PyFLP"
    assert project.version == FLVersion(20, 8, 4, 2576)

    with pytest.raises(ValueError, match="cannot be less than zero"):
        project.channel_count = -1

    with pytest.raises(ValueError, match=f"{VALID_PPQS}"):
        project.ppq = 0

    with pytest.raises(ValueError, match="10.0-522.0"):
        project.tempo = 999.0

    with pytest.raises(ValueError, match="major.minor.build.patch?"):
        project.version = "2.2"  # type: ignore


def test_null_check(project: Project, tmp_path: pathlib.Path):
    pyflp.save(project, tmp_path / "null_check.flp")
    b1 = open(pathlib.Path(__file__).parent / "assets" / "FL 20.8.4.flp", "rb").read()
    b2 = open(tmp_path / "null_check.flp", "rb").read()
    # result = b1 == b2  # ! Don't compare 2 big bytes objects in pytest EVER
    assert b1 == b2


def test_fl2024_events(tmp_path: pathlib.Path):
    flags = bytes(4) + pack_i32(0x0C) + bytes(4)
    insert = [
        (42, pack_u8(0)),
        (236, flags),
        (165, pack_i32(3)),
        (166, pack_i32(1)),
        (49, pack_u8(0)),
    ]
    insert += [(154, pack_i32(-1)), (147, pack_i32(-1))]
    events = [
        (169, pack_i32(7)),
        (231, pack_text("Unsorted")),
        *fl2024_channel(insert=1),
        (29, pack_u8(1)),
        (103, pack_u16(2)),
        *insert,
        *insert,
    ]
    data = flp_bytes(events, channel_count=1)
    project = parse(tmp_path, data)
    assert {event.id for event in project.events} >= {
        ProjectID._169,
        ChannelID.RoutedToInsert,
        ChannelID._50,
        ChannelID._51,
        ChannelID._170,
        MixerID.InsertCount,
        InsertID._42,
        InsertID._165,
        InsertID._166,
        InsertID._49,
    }
    assert project.events.first(ChannelID._170).value == -1

    pyflp.save(project, tmp_path / "saved.flp")
    assert (tmp_path / "saved.flp").read_bytes() == data
