from __future__ import annotations

import pytest

from pyflp._events import (
    WORD,
    AsciiEvent,
    EventEnum,
    EventTree,
    IndexedEvent,
    U8Event,
    UnicodeEvent,
)
from pyflp.exceptions import EventIDOutOfRange, InvalidEventChunkSize


def test_id_out_of_range():
    with pytest.raises(EventIDOutOfRange, match=str(tuple(range(0, WORD)))):
        U8Event(EventEnum(128), b"\x00")

    with pytest.raises(ValueError):
        AsciiEvent(EventEnum(0), b"1234-decode-me-baby")


def test_invalid_chunk_size():
    with pytest.raises(InvalidEventChunkSize, match="1"):
        U8Event(EventEnum(0), b"12")


def test_event_tree():
    root = EventTree()
    child = EventTree(root)
    assert child in root.children
    event = U8Event(EventEnum(0), b"\x01")
    child.append(event)
    assert root.first(EventEnum(0)) == event
    child.remove(EventEnum(0))
    assert not root


def test_event_tree_split():
    ids = (1, 2, 3, 2, 4, 1, 5)
    root = EventTree(
        init=(IndexedEvent(r, U8Event(EventEnum(id), b"\x00")) for r, id in enumerate(ids))
    )
    one, two, three = EventEnum(1), EventEnum(2), EventEnum(3)
    groups = [[event.id for event in tree] for tree in root.split(two, one, three)]
    assert groups == [[1, 2], [3, 2], [1]]


# "Hi 🙈 there" with the second half of the emoji lost, as FL Studio saved it
BROKEN_EMOJI = "Hi \ud83d there\0".encode("utf-16-le", "surrogatepass")


def test_invalid_utf16_is_replaced_with_a_warning():
    with pytest.warns(UnicodeWarning, match="invalid UTF-16"):
        event = UnicodeEvent(EventEnum(194), BROKEN_EMOJI)
    assert event.value == "Hi � there"
    assert bytes(event) == bytes((194, len(BROKEN_EMOJI))) + BROKEN_EMOJI


def test_invalid_utf16_is_rebuilt_once_changed():
    with pytest.warns(UnicodeWarning):
        event = UnicodeEvent(EventEnum(194), BROKEN_EMOJI + b"!")  # Odd size too
    assert event.value == "Hi � there\0�"

    event.value = "Hi there"
    assert bytes(event) == bytes((194, 18)) + "Hi there\0".encode("utf-16-le")


def test_valid_utf16_does_not_warn(recwarn: pytest.WarningsRecorder):
    event = UnicodeEvent(EventEnum(194), "Hi 🙈 there\0".encode("utf-16-le"))
    assert event.value == "Hi 🙈 there"
    assert not recwarn.list
