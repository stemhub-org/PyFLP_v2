from __future__ import annotations

import struct
from typing import Callable

import pytest

from pyflp._events import RGBA, EventTree, IndexedEvent
from pyflp.arrangement import (
    Arrangement,
    Arrangements,
    ChannelPLItem,
    PatternPLItem,
    Track,
    TrackEvent,
    TrackID,
    TrackMotion,
    TrackPress,
    TrackSync,
)
from pyflp.timemarker import TimeMarkerType


def test_arrangements(arrangements: Arrangements):
    assert len(arrangements) == 2
    assert arrangements.current == arrangements[0]
    assert arrangements.loop_pos == (3840, 5376)
    assert arrangements.max_tracks == 500
    assert arrangements.time_signature.num == 4
    assert arrangements.time_signature.beat == 4


@pytest.fixture(scope="session")
def arrangement(arrangements: Arrangements):
    def wrapper(index: int):
        return arrangements[index]

    return wrapper


@pytest.fixture(scope="session")
def tracks(arrangement: Callable[[int], Arrangement]):
    return tuple(arrangement(0).tracks)[:22]


def test_track_color(tracks: tuple[Track, ...]):
    for track in tracks:
        assert (
            track.color == RGBA(1.0, 0.0, 0.0, 0.0)
            if track.name == "Red"
            else track.color == RGBA.from_bytes(bytes((72, 81, 86, 0)))
        )


def test_track_content_locked(tracks: tuple[Track, ...]):
    for track in tracks:
        assert (
            track.content_locked if track.name == "Locked to content" else not track.content_locked
        )


def test_track_enabled(tracks: tuple[Track, ...]):
    for track in tracks:
        assert not track.enabled if track.name == "Disabled" else track.enabled


def test_track_grouped(tracks: tuple[Track, ...]):
    for track in tracks:
        assert track.grouped if track.name == "Grouped" else not track.grouped


def test_track_height(tracks: tuple[Track, ...]):
    for track in tracks:
        if track.name == "Min Size":
            assert track.height == "0%"
        elif track.name == "Max Size":
            assert track.height == "1000%"
        else:
            assert track.height == "100%"


def test_track_icon(tracks: tuple[Track, ...]):
    for track in tracks:
        assert track.icon == 70 if track.name == "Iconified" else not track.icon


def test_track_items(tracks: tuple[Track, ...]):
    for track in tracks:
        num_items = 0
        if track.name == "Audio track":
            num_items = 16
            assert {type(i) for i in track} == {ChannelPLItem}
            assert {i.channel.iid for i in track} == {11}  # type: ignore
        elif track.name == "MIDI":
            num_items = 4
            assert {type(i) for i in track} == {PatternPLItem}
            assert {i.pattern.iid for i in track} == {3}  # type: ignore
            assert [i.position for i in track] == [p * 384 for p in range(num_items)]
        elif track.name in ("Cut pattern", "Automation"):
            num_items = 1

        if track.name == "Audio track":
            assert {i.offsets for i in track} == {(-1.0, -1.0)}
        elif track.name == "MIDI":
            assert {i.offsets for i in track} == {(-1, -1)}
        elif track.name == "Cut pattern":
            assert [i.offsets for i in track] == [(0, 1536)]

        assert len(track) == num_items
        assert [i.group for i in track] == [0] * num_items


def test_track_locked(tracks: tuple[Track, ...]):
    for track in tracks:
        assert track.locked if track.name == "Locked" else not track.locked


def test_track_motion(tracks: tuple[Track, ...]):
    for track in tracks:
        assert (
            track.motion == TrackMotion.Random
            if track.name == "Random Motion"
            else track.motion == TrackMotion.Stay
        )


def test_track_name(tracks: tuple[Track, ...]):
    assert [track.name for track in tracks] == [
        None,
        "Enabled",
        "Disabled",
        "Locked",
        "Red",
        "Iconified",
        "Grouped",
        "Audio track",
        "Instrument track",
        "MIDI",
        "Cut pattern",
        "Automation",
        "Locked to content",
        "Locked to size",
        "Min Size",
        "Max Size",
        "Latched",
        "Random Motion",
        "Trigger Sync OFF",
        "Position Sync AUTO",
        "Queued",
        "Intolerant",
    ]


def test_track_position_sync(tracks: tuple[Track, ...]):
    for track in tracks:
        assert (
            track.position_sync == TrackSync.Auto
            if track.name == "Position Sync AUTO"
            else track.position_sync == TrackSync.Off
        )


def test_track_press(tracks: tuple[Track, ...]):
    for track in tracks:
        assert (
            track.press == TrackPress.Latch
            if track.name == "Latched"
            else track.press == TrackPress.Retrigger
        )


def test_track_tolerant(tracks: tuple[Track, ...]):
    for track in tracks:
        assert not track.tolerant if track.name == "Intolerant" else track.tolerant


def test_track_queued(tracks: tuple[Track, ...]):
    for track in tracks:
        assert track.queued if track.name == "Queued" else not track.queued


def test_first_arrangement(arrangement: Callable[[int], Arrangement]):
    arr = arrangement(0)
    assert arr.name == "Just tracks"
    assert not tuple(arr.timemarkers)
    assert len(tuple(arr.tracks)) == 500


def test_second_arrangement(arrangement: Callable[[int], Arrangement]):
    arr = arrangement(1)
    assert arr.name == "Just timemarkers"
    assert len(tuple(arr.timemarkers)) == 11
    assert len(tuple(arr.tracks)) == 500


def test_timemarker_positions_and_actions(arrangement: Callable[[int], Arrangement]):
    markers = tuple(arrangement(1).timemarkers)
    assert [m.position for m in markers] == [384 * bar for bar in range(11)]
    assert [m.action for m in markers] == [5, 8, 8, 0, 4, 0, 3, 9, 10, 1, 2]
    assert [m.type for m in markers] == [
        TimeMarkerType.Signature if m.action == 8 else TimeMarkerType.Marker for m in markers
    ]
    assert [(m.numerator, m.denominator) for m in markers[1:3]] == [(2, 8), (4, 4)]


# What follows the 48 bytes of known fields in track data, as FL Studio writes it.
TRACK_DATA_TAILS = {
    61: bytes(5) + b"\xff" * 8,  # FL Studio 12.9
    66: bytes(5) + b"\xff" * 8 + b"\x01" + bytes(4),  # FL Studio 20.8 to 24.1
    70: bytes(5) + b"\xff" * 8 + b"\x01" + bytes(8),  # From FL Studio 24.2.99
}


def track_data(size: int, height: float = 1.0) -> bytes:
    """Track data (event 238) of ``size`` bytes: track 1, default settings."""
    known = struct.pack(
        "<IIIBfiBIIIIIIBB", 1, 0x565148, 0, 1, height, -16, 0, 0, 0, 5, 0, 1, 0, 0, 0
    )
    return known + TRACK_DATA_TAILS[size]


def track(data: bytes) -> Track:
    return Track(EventTree(init=[IndexedEvent(0, TrackEvent(TrackID.Data, data))]), items=[])


@pytest.mark.parametrize("size", [61, 66, 70])
def test_track_data_sizes(size: int):
    data = track_data(size)
    model = track(data)

    assert model.iid == 1
    assert model.color == RGBA.from_bytes(bytes((72, 81, 86, 0)))
    assert model.enabled
    assert model.height == "100%"
    assert model.trigger_sync == TrackSync.FourBeats
    assert model.tolerant
    assert not model.locked
    assert bytes(model.events.first(TrackID.Data)) == bytes((238, size)) + data


@pytest.mark.parametrize("size", [61, 66, 70])
def test_track_height_is_kept_exact(size: int):
    height = struct.unpack("<f", struct.pack("<f", 1.14))[0]  # 113.99999...%
    data = track_data(size, height)
    model = track(data)

    assert model.height == "114%"
    assert bytes(model.events.first(TrackID.Data)) == bytes((238, size)) + data

    model.height = "50%"
    assert model.height == "50%"
    assert bytes(model.events.first(TrackID.Data))[15:19] == struct.pack("<f", 0.5)
