# PyFLP - An FL Studio project file (.flp) parser
# Copyright (C) 2022 demberto
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. This program is distributed in the hope that it will be
# useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General
# Public License for more details. You should have received a copy of the
# GNU General Public License along with this program. If not, see
# <https://www.gnu.org/licenses/>.

"""The :attr:`pyflp.mixer.MixerID.Params` event, which holds the parameters of all inserts."""

from __future__ import annotations

import dataclasses
import enum
from collections import defaultdict
from typing import Any, DefaultDict

import construct as c
import construct_typed as ct

from pyflp._adapters import StdEnum
from pyflp._events import ListEventBase


@enum.unique
class _MixerParamsID(ct.EnumBase):
    SlotEnabled = 0
    SlotMix = 1
    RouteVolStart = 64  # 64 - 191 are send levels to inserts 0 - 127, before 24.2.99
    Volume = 192
    Pan = 193
    StereoSeparation = 194
    LowGain = 208
    MidGain = 209
    HighGain = 210
    LowFreq = 216
    MidFreq = 217
    HighFreq = 218
    LowQ = 224
    MidQ = 225
    HighQ = 226


@dataclasses.dataclass
class _InsertItems:
    slots: DefaultDict[int, dict[int, dict[str, Any]]] = dataclasses.field(
        default_factory=lambda: defaultdict(dict)
    )
    own: dict[int, dict[str, Any]] = dataclasses.field(default_factory=dict)
    sends: dict[int, dict[str, Any]] = dataclasses.field(default_factory=dict)
    """Send levels by destination :attr:`Insert.number`."""


_KIND_SEND_LEVEL = 32
"""``MixerParamsEvent`` item kind of send levels since FL Studio 24.2.99."""

# Items are grouped by insert, under a key: ``channel_data >> 6``.
_KEY_MASTER = 128
"""Key of master before FL Studio 24.2.99; insert *n* uses ``_KEY_MASTER + n``."""

_KEY_MASTER_24_2 = 448
"""Key of master since FL Studio 24.2.99; insert *n* uses ``_KEY_MASTER_24_2 + n``."""

_KEY_CURRENT_24_2 = 949
"""Key of the "current" insert since FL Studio 24.2.99.

Before, the "current" insert is keyed like the others, by its position.
"""


class MixerParamsEvent(ListEventBase):
    """Parameters of all inserts and their slots: 12 bytes each.

    ``channel_data`` holds the insert's key (upper 10 bits, see
    :class:`pyflp.mixer.Mixer` for its two layouts) and the slot index (lower
    6 bits). ``kind`` is 31 for insert and slot parameters and 32 for send
    levels since FL Studio 24.2.99, whose ``id`` is the destination insert.
    One item, of kind 0 and key 256, belongs to no insert; its meaning is
    unknown.
    """

    STRUCT = c.GreedyRange(
        c.Struct(
            "_u4" / c.Bytes(4),  # 4
            "id" / StdEnum[_MixerParamsID](c.Byte),  # 5
            "kind" / c.Byte,  # 6
            "channel_data" / c.Int16ul,  # 8
            "msg" / c.Int32sl,  # 12
        )
    )

    def __init__(self, id: Any, data: bytearray) -> None:
        super().__init__(id, data)
        self.items_: DefaultDict[int, _InsertItems] = defaultdict(_InsertItems)
        """Items by insert key (``channel_data >> 6``)."""

        for item in self.data:
            insert = self.items_[item["channel_data"] >> 6]
            id = item["id"]

            if item["kind"] == _KIND_SEND_LEVEL:
                insert.sends[int(id)] = item
            elif id in (_MixerParamsID.SlotEnabled, _MixerParamsID.SlotMix):
                insert.slots[item["channel_data"] & 0x3F][id] = item
            elif _MixerParamsID.RouteVolStart <= id < _MixerParamsID.Volume:
                insert.sends[id - _MixerParamsID.RouteVolStart] = item
            else:
                insert.own[id] = item
