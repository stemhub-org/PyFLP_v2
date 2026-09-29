from __future__ import annotations

import itertools
import pathlib
from typing import Mapping, Sequence, cast

from pyflp._events import RGBA
from pyflp.channel import Sampler
from pyflp.mixer import Insert, InsertDock, Mixer, MixerID, MixerParamsEvent
from pyflp.plugin import FruityFastDist, VSTPlugin
from pyflp.project import Project

from .conftest import get_model
from .synthetic import (
    RawEvent,
    flp_bytes,
    mixer_param,
    pack_i32,
    pack_text,
    pack_u8,
    pack_u16,
    parse,
)

_FLAGS = bytes(4) + pack_i32(0x0C) + bytes(4)  # EnableEffects | Enabled


def insert_block(
    *,
    name: str | None = None,
    slots: Mapping[int, tuple[str, str]] | None = None,
    routing: Sequence[int] | None = None,
    output: int = -1,
    input: int = -1,
) -> list[RawEvent]:
    """The events of one insert as FL Studio 24.2.99+ saves them."""
    events: list[RawEvent] = [(42, pack_u8(0))]
    if name is not None:
        events.append((204, pack_text(name)))
    events.append((236, _FLAGS))
    for index in range(10):  # A slot's plugin events come before its index.
        if slots and index in slots:
            internal_name, slot_name = slots[index]
            events += [(201, pack_text(internal_name)), (203, pack_text(slot_name))]
        events.append((98, pack_u16(index)))
    if routing is not None:
        events.append((235, bytes(routing)))
    events += [
        (165, pack_i32(3)),
        (166, pack_i32(1)),
        (49, pack_u8(0)),
        (154, pack_i32(input)),
        (147, pack_i32(output)),
    ]
    return events


def fl2024_mixer(*blocks: list[RawEvent], params: bytes = b"") -> list[RawEvent]:
    """A mixer as FL Studio 24.2.99+ saves it: master first, "current" insert last."""
    events: list[RawEvent] = [(29, pack_u8(1)), (103, pack_u16(len(blocks)))]
    events += itertools.chain.from_iterable(blocks)
    if params:
        events.append((225, params))
    return events


def get_insert(preset: str):
    # Parse as Mixer to get events, because an Insert cannot parse
    # MixerID.Params which holds most of its information.
    mixer = get_model(f"inserts/{preset}", Mixer)

    # A preset stores items only for a single insert, currently thats 32 per
    # insert. Pass these to Insert's constructor. This mimics Mixer's normal
    # behaviour, however that depends on InsertID.Output as a marker to indicate
    # the end of an Insert, which surprisingly isn't a part of presets.
    params = cast(MixerParamsEvent, mixer.events.first(MixerID.Params))
    items = tuple(params.items_.values())[0]
    return Insert(mixer.events, iid=0, max_slots=10, params=items)


def test_insert_bypassed():
    assert get_insert("effects-bypassed.fst").bypassed


def test_insert_channels_swapped():
    assert get_insert("channels-swapped.fst").channels_swapped


def test_insert_color():
    assert get_insert("colored.fst").color == RGBA.from_bytes(bytes((255, 20, 20, 0)))


def test_insert_dock(mixer: Mixer):
    sends = (100, 101, 102, 103)
    for insert in mixer:
        if insert.name in ("Docked left", "Master") or insert.number == -1:
            assert insert.dock == InsertDock.Left
        elif insert.name == "Docked right" or insert.number in sends:
            assert insert.dock == InsertDock.Right
        else:
            assert insert.dock == InsertDock.Middle


def test_insert_enabled():
    assert not get_insert("disabled.fst").enabled


def test_insert_locked():
    assert get_insert("locked.fst").locked


def test_insert_pan():
    assert get_insert(r"100%-left.fst").pan == -6400
    assert get_insert(r"100%-right.fst").pan == 6400


def test_insert_polarity_reversed():
    assert get_insert("polarity-reversed.fst").polarity_reversed


def test_insert_routes(inserts: tuple[Insert, ...]):
    assert not tuple(inserts[5].routes)


def test_insert_stereo_separation():
    assert get_insert(r"100%-merged.fst").stereo_separation == 64
    assert get_insert(r"100%-separated.fst").stereo_separation == -64


def test_insert_eq():
    eq = get_insert("post-eq.fst").eq
    assert eq.low.freq == 0
    assert eq.low.gain == 1800
    assert eq.low.reso == 0
    assert eq.mid.freq == 33145
    assert eq.mid.gain == 0
    assert eq.mid.reso == 17500
    assert eq.high.freq == 65536
    assert eq.high.gain == -1800
    assert eq.high.reso == 65536


def test_mixer(mixer: Mixer):
    assert mixer.apdc
    assert len(mixer) == mixer.max_inserts == 127
    assert mixer.max_slots == 10


def test_inserts_numbered_like_fl_studio(project: Project):
    mixer = project.mixer
    inserts = tuple(mixer)
    assert inserts[0].name == mixer[0].name == "Master"
    assert (inserts[0].number, inserts[0].iid) == (0, -1)
    assert (inserts[1].number, inserts[1].iid) == (1, 0)
    assert (inserts[-1].number, inserts[-1].iid) == (-1, 125)  # "current" insert
    assert mixer[-1] == inserts[-1]

    channel = project.channels["Instrument track"]
    assert isinstance(channel, Sampler) and channel.insert == 2
    assert mixer[2].name == "Instrument track"


def test_insert_output_is_its_own(inserts: tuple[Insert, ...]):
    assert inserts[0].output == 0  # Master
    assert inserts[1].output == -1


def test_fl2024_inserts_end_with_their_output(tmp_path: pathlib.Path):
    blocks = (
        insert_block(name="Master", output=10, input=20),
        insert_block(name="Drums", routing=[1], output=11, input=21),
        insert_block(name="Bass", routing=[1], output=12, input=22),
        insert_block(output=13, input=23),
    )
    mixer = parse(tmp_path, flp_bytes(fl2024_mixer(*blocks))).mixer
    inserts = tuple(mixer)
    assert len(mixer) == len(inserts) == 4
    assert [insert.name for insert in inserts] == ["Master", "Drums", "Bass", None]
    assert [insert.output for insert in inserts] == [10, 11, 12, 13]
    assert [insert.input for insert in inserts] == [20, 21, 22, 23]
    assert [insert.number for insert in inserts] == [0, 1, 2, -1]
    assert [insert.iid for insert in inserts] == [-1, 0, 1, 2]
    assert mixer[2].name == "Bass"
    assert mixer[-1] == inserts[-1]


def test_slot_plugins_come_before_their_index(mixer: Mixer):
    plugin_test = mixer["Plugin Test"]
    assert len(plugin_test) == 10
    assert [slot.internal_name for slot in plugin_test] == [
        "Fruity Balance",
        "Fruity Fast Dist",
        "Fruity Send",
        "Fruity Soft Clipper",
        "Fruity Stereo Enhancer",
        "Soundgoodizer",
        "Fruity Wrapper",
        None,
        None,
        None,
    ]
    assert isinstance(plugin_test[1].plugin, FruityFastDist)
    assert isinstance(plugin_test[6].plugin, VSTPlugin)
    assert plugin_test[7].plugin is None
    assert [slot.name for slot in mixer["Effect slots"]][:3] == ["Colored", "Iconified", None]


def test_insert_preset_slots():
    assert [slot.internal_name for slot in get_insert("effects-bypassed.fst")][:2] == [
        "Fruity NoteBook 2",
        None,
    ]


def test_fl2024_slot_plugins(tmp_path: pathlib.Path):
    slots = {1: ("Fruity Balance", "Gain"), 3: ("Fruity Send", "Send")}
    blocks = (insert_block(), insert_block(slots=slots, routing=[1]), insert_block())
    insert = parse(tmp_path, flp_bytes(fl2024_mixer(*blocks))).mixer[1]
    assert [slot.name for slot in insert] == [None, "Gain", None, "Send", *[None] * 6]
    assert [slot.index for slot in insert] == list(range(10))


def test_insert_params(mixer: Mixer):
    assert mixer[0].volume == 12800
    assert mixer["Zero Volume"].volume == 0
    assert (mixer["100% L"].pan, mixer["100% R"].pan) == (-6400, 6400)
    assert mixer["100% mono"].stereo_separation == 64
    assert mixer["100% separated"].stereo_separation == -64
    assert mixer["Post EQ"].eq.low.gain == 1800


def test_slot_params(mixer: Mixer):
    effect_slots = mixer["Effect slots"]
    assert [slot.mix for slot in effect_slots][:5] == [12800, 12800, 12800, 12800, 0]
    assert all(slot.enabled is True for slot in effect_slots)
    assert mixer["Bypassed"][0].mix == 0


def test_fl2024_mixer_params(tmp_path: pathlib.Path):
    params = b"".join(
        (
            mixer_param(256, 0, 0, 0, 12800),  # Not an insert's
            mixer_param(448, 0, 192, 31, 12000),  # Master
            mixer_param(449, 0, 192, 31, 11000),
            mixer_param(449, 0, 193, 31, -3200),
            mixer_param(449, 0, 194, 31, 20),
            mixer_param(449, 2, 0, 31, 0),
            mixer_param(449, 2, 1, 31, 6400),
            mixer_param(450, 0, 192, 31, 10000),
            mixer_param(450, 0, 1, 32, 5000),  # Send level to insert 1
            mixer_param(949, 0, 192, 31, 9000),  # "Current" insert
        )
    )
    blocks = (insert_block(), insert_block(routing=[1]), insert_block(routing=[1, 1]))
    project = parse(tmp_path, flp_bytes(fl2024_mixer(*blocks, insert_block(), params=params)))
    mixer = project.mixer
    assert [insert.volume for insert in mixer] == [12000, 11000, 10000, 9000]
    assert (mixer[1].pan, mixer[1].stereo_separation) == (-3200, 20)
    assert (mixer[1][2].enabled, mixer[1][2].mix) == (False, 6400)
    assert (mixer[1][0].enabled, mixer[1][0].mix) == (None, None)
    assert mixer[2][0].mix is None

    mixer[1][2].enabled = True
    mixer[1][2].mix = 12800
    mixer[1].volume = 8000
    event = bytes(project.events.first(MixerID.Params))
    for item in (
        mixer_param(449, 2, 0, 31, 1),
        mixer_param(449, 2, 1, 31, 12800),
        mixer_param(449, 0, 192, 31, 8000),
    ):
        assert item in event
