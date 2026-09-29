from __future__ import annotations

import pathlib
import struct

import pytest

import pyflp
from pyflp.arrangement import ArrangementID, ChannelPLItem, PatternPLItem, PlaylistEvent
from pyflp.types import FLVersion

from .synthetic import ascii_text, event, playlist_item, u8, u16, u32, utf16_text, write

FL_20_8_4 = FLVersion(20, 8, 4, 2576)
FL_24_1_0 = FLVersion(24, 1, 0, 4212)
FL_25_2_4 = FLVersion(25, 2, 4, 4960)


def playlist(version: FLVersion, *items: bytes) -> PlaylistEvent:
    return PlaylistEvent(ArrangementID.Playlist, b"".join(items), version=version)


@pytest.mark.parametrize(
    "version, size",
    [
        (FLVersion(12, 9, 3, 321), 32),
        (FL_20_8_4, 32),
        (FLVersion(20, 99, 3000, 3031), 60),
        (FLVersion(21, 0, 0, 3302), 60),
        (FL_24_1_0, 60),
        (FLVersion(24, 2, 99, 4720), 80),
        (FLVersion(25, 1, 0, 4858), 80),
        (FL_25_2_4, 80),
    ],
)
def test_item_size_follows_version(version: FLVersion, size: int):
    assert PlaylistEvent.item_size(version) == size


@pytest.mark.parametrize(
    "version, size, count",
    [
        (FL_20_8_4, 32, 15),  # 480 bytes, also a multiple of 60 and 80
        (FL_24_1_0, 60, 4),  # 240 bytes, also a multiple of 80
        (FL_25_2_4, 80, 3),  # 240 bytes, also a multiple of 60
        (FL_25_2_4, 80, 2),  # 160 bytes, also a multiple of 32
    ],
)
def test_items_are_split_by_version(version: FLVersion, size: int, count: int):
    items = [
        playlist_item(size, position=96 * i, pattern=1 + i % 2, track=i, uid=i + 1)
        for i in range(count)
    ]
    pl = playlist(version, *items)

    assert len(pl) == count
    assert [item["position"] for item in pl] == [96 * i for i in range(count)]
    assert [item["item_index"] for item in pl] == [20481 + i % 2 for i in range(count)]
    assert [item["track_rvidx"] for item in pl] == [499 - i for i in range(count)]
    assert bytes(pl) == event(233, b"".join(items))


def test_80_byte_items_keep_their_tail():
    item = bytearray(playlist_item(80, pattern=1))
    item[60:64] = struct.pack("<f", 1.0)
    pl = playlist(FL_25_2_4, bytes(item))
    assert pl[0]["length"] == 384
    assert bytes(pl) == event(233, bytes(item))


def test_item_size_without_version_is_guessed_from_items():
    for size, count in ((32, 15), (60, 4), (80, 3)):
        data = b"".join(playlist_item(size, pattern=1, uid=i + 1) for i in range(count))
        assert len(PlaylistEvent(ArrangementID.Playlist, data)) == count


def test_items_contradicting_version_warn():
    data = b"".join(playlist_item(80, pattern=1, uid=i + 1) for i in range(3))
    with pytest.warns(UserWarning, match="expected 60 byte playlist items, found 80"):
        pl = playlist(FL_24_1_0, data)
    assert len(pl) == 3


def test_items_matching_no_layout_warn():
    data = bytes(160)  # No pattern base in any item, whatever their size
    with pytest.warns(UserWarning, match="no known layout; assuming 80 byte items"):
        pl = playlist(FL_25_2_4, data)
    assert len(pl) == 2
    assert bytes(pl) == event(233, data)


def test_parse_passes_version_to_playlist(tmp_path: pathlib.Path):
    """FL Studio 25.2.4 project: 3 clips of 80 bytes (240 bytes, a multiple of 60)."""
    items = (
        playlist_item(80, position=0, pattern=1, track=0, uid=1),
        playlist_item(80, position=384, channel=0, track=1, uid=2, offsets=(0.0, 500.0)),
        playlist_item(80, position=768, pattern=1, track=0, uid=3),
    )
    track = struct.pack("<I", 1) + bytes(66)
    path = write(
        tmp_path,
        ascii_text(199, "25.2.4.4960"),
        event(172, b"\x01\x01\x00"),
        u32(156, 128000),
        utf16_text(231, "Unsorted"),  # DisplayGroupID.Name
        u16(64, 0),  # ChannelID.New
        u8(21, 2),  # ChannelID.Type
        u32(145, 0xFFFFFFFF),  # ChannelID.GroupNum
        u16(65, 1),  # PatternID.New
        u16(99, 1),  # ArrangementID.New
        event(233, b"".join(items)),
        *(event(238, bytes([i + 1]) + track[1:]) for i in range(3)),
        u16(100, 0),  # ArrangementsID.Current ends the last arrangement
        channel_count=1,
    )
    project = pyflp.parse(path)
    assert project.tempo == 128.0

    tracks = list(project.arrangements[0].tracks)
    assert len(tracks) == 3
    assert [type(item) for item in tracks[0]] == [PatternPLItem, PatternPLItem]
    assert [item.position for item in tracks[0]] == [0, 768]
    assert [type(item) for item in tracks[1]] == [ChannelPLItem]
    assert not len(tracks[2])

    pyflp.save(project, tmp_path / "saved.flp")
    assert (tmp_path / "saved.flp").read_bytes() == path.read_bytes()


def clip(size: int, version: FLVersion, **kw) -> PatternPLItem | ChannelPLItem:
    """The only item of a playlist, as a model."""
    pl = playlist(version, playlist_item(size, **kw))
    if "pattern" in kw:
        return PatternPLItem(pl[0], 0, pl, pattern=None)
    return ChannelPLItem(pl[0], 0, pl, channel=None)


@pytest.mark.parametrize("size, version", [(32, FL_20_8_4), (60, FL_24_1_0), (80, FL_25_2_4)])
def test_pattern_clip_offsets_are_ticks(size: int, version: FLVersion):
    assert clip(size, version, pattern=1).offsets == (-1, -1)

    item = clip(size, version, pattern=1, offsets=(96, 1536))
    assert item.offsets == (96, 1536)
    assert all(isinstance(offset, int) for offset in item.offsets)

    item.offsets = (0, 192)
    assert item._parent[0]["start_offset"] == 0
    assert bytes(item._parent)[-size:][24:32] == struct.pack("<ii", 0, 192)


def test_pattern_clip_offsets_stored_as_float():
    """Older projects (seen from FL Studio 12.9) store "none" as the float -1.0."""
    minus_one = struct.unpack("<i", struct.pack("<f", -1.0))[0]
    item = clip(32, FL_20_8_4, pattern=1, offsets=(minus_one, minus_one))
    assert item.offsets == (-1, -1)
    assert bytes(item._parent)[-32:][24:32] == struct.pack("<ff", -1.0, -1.0)


@pytest.mark.parametrize("size, version", [(32, FL_20_8_4), (60, FL_24_1_0), (80, FL_25_2_4)])
def test_channel_clip_offsets_are_floats(size: int, version: FLVersion):
    assert clip(size, version, channel=0).offsets == (-1.0, -1.0)

    item = clip(size, version, channel=0, offsets=(12.5, 480.25))
    assert item.offsets == (12.5, 480.25)

    item.offsets = (0.0, 1000.5)
    assert bytes(item._parent)[-size:][24:32] == struct.pack("<ff", 0.0, 1000.5)


def test_item_flags_are_raw():
    assert clip(80, FL_25_2_4, pattern=1).item_flags == 0x40
    assert clip(80, FL_25_2_4, channel=0, flags=0x2040).item_flags == 0x2040


def test_muted_is_unknown():
    assert clip(80, FL_25_2_4, pattern=1, flags=0x2040).muted is None
