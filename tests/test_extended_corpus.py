"""Checks run on local projects when ``PYFLP_EXTENDED_CORPUS`` names a folder of FLPs.

Skipped otherwise. Projects which aren't ours to share (FL Studio demo songs,
user projects) must stay out of the repository; point this at them instead.

Projects from FL Studio 12.9 to 25.2.4 pass both tests. They rely on these
parsing fixes, without which FL Studio 2024 and 2025 projects fail or come out
wrong: event 172 read as 3 bytes (FL Studio 25.2.3+ projects, where 4 bytes
shift every later event), playlist items sized by the FL Studio version (80
bytes from 24.2) and text which isn't valid UTF-16 decoded with a warning (seen
in FL Studio 25.1 comments). :func:`test_project` also relies on pattern clip
offsets and track data saving back unchanged. :func:`test_mixer` relies on the
mixer fixes: inserts ending with their output, slots closed by their index,
mixer params mapped by key layout, routes read from the routing flags and
channel inserts read from ``ChannelID.RoutedToInsert`` (event 104).
"""

from __future__ import annotations

import os
import pathlib
import warnings
from typing import Iterator

import construct as c
import pytest

import pyflp
from pyflp._events import ODD_SIZE_IDS, StrEventBase, fixed_size
from pyflp.arrangement import PATTERN_BASE, ArrangementID, PlaylistEvent, TrackID
from pyflp.channel import Instrument, Sampler
from pyflp.mixer import SlotID
from pyflp.project import Project, ProjectID
from pyflp.timemarker import TimeMarkerID

CORPUS = os.environ.get("PYFLP_EXTENDED_CORPUS")
PATHS = sorted(pathlib.Path(CORPUS).rglob("*.flp")) if CORPUS else []
ARRANGEMENT_IDS = {*ArrangementID, *TrackID, *TimeMarkerID, *ODD_SIZE_IDS}

pytestmark = pytest.mark.skipif(not CORPUS, reason="PYFLP_EXTENDED_CORPUS is not set")


def parse(path: pathlib.Path) -> Project:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pyflp.parse(path)


def raw_events(data: bytes) -> Iterator[tuple[int, bytes, int]]:
    """Yields the ID, the serialised bytes and the data size of every event of an FLP."""
    pos = 22
    while pos < len(data):
        start, id = pos, data[pos]
        size = fixed_size(id)
        if size is None:
            size = c.VarInt.parse(data[pos + 1 : pos + 11])
            pos += len(c.VarInt.build(size))
        pos += 1 + size
        yield id, data[start:pos], size


@pytest.mark.parametrize("path", PATHS, ids=lambda path: path.name)
def test_project(path: pathlib.Path):
    data = path.read_bytes()
    project = parse(path)

    raw = list(raw_events(data))
    events = list(project.events)
    assert [id for id, *_ in raw] == [int(event.id) for event in events]
    if any(id == ProjectID.Tempo for id, *_ in raw):
        assert project.tempo is not None

    items = 0
    for (id, chunk, size), event in zip(raw, events):
        if id in ARRANGEMENT_IDS or isinstance(event, StrEventBase):
            assert bytes(event) == chunk, f"event {id} doesn't save back unchanged"

        if isinstance(event, PlaylistEvent):
            assert len(event) * event._kwds["item_size"] == size
            assert {item["pattern_base"] for item in event} <= {PATTERN_BASE}
            items += len(event)

    if items:
        assert sum(len(t) for a in project.arrangements for t in a.tracks) == items


@pytest.mark.parametrize("path", PATHS, ids=lambda path: path.name)
def test_mixer(path: pathlib.Path):
    project = parse(path)
    mixer = project.mixer
    inserts = list(mixer)
    numbers = [*range(len(inserts) - 1), -1]  # Master first, "current" insert last

    assert len(mixer) == len(inserts)
    assert [insert.number for insert in inserts] == numbers
    for insert in inserts:
        assert insert.volume is not None
        assert len(list(insert)) == mixer.max_slots
        for slot in insert:
            assert list(slot.events)[-1].id == SlotID.Index
        for route in insert.routes:
            assert route.destination in numbers[:-1]

    for channel in project.channels:
        if isinstance(channel, (Instrument, Sampler)):
            assert channel.insert in numbers
