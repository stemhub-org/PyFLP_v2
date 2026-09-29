from __future__ import annotations

import pytest

from pyflp._events import EventTree, IndexedEvent, U32Event
from pyflp.timemarker import TimeMarker, TimeMarkerID, TimeMarkerType


def marker(raw_position: int) -> TimeMarker:
    event = U32Event(TimeMarkerID.Position, raw_position.to_bytes(4, "little"))
    return TimeMarker(EventTree(init=[IndexedEvent(0, event)]))


@pytest.mark.parametrize(
    "raw, position, action, type",
    [
        (0x00000480, 1152, 0, TimeMarkerType.Marker),
        (0x08000180, 384, 8, TimeMarkerType.Signature),
        (0x09000A80, 2688, 9, TimeMarkerType.Marker),
        (0x0B123456, 0x123456, 11, TimeMarkerType.Marker),
        (0x05FFFFFF, 0xFFFFFF, 5, TimeMarkerType.Marker),
    ],
)
def test_position_holds_action_in_high_byte(
    raw: int, position: int, action: int, type: TimeMarkerType
):
    m = marker(raw)
    assert m.position == position
    assert m.action == action
    assert m.type == type


def test_marker_without_position():
    m = TimeMarker(EventTree())
    assert m.position is None
    assert m.action is None
    assert m.type is None
