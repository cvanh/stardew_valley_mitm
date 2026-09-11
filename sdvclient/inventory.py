"""Decode and build Stardew Valley farmer inventory (``netItems``) deltas.

The farmer's inventory is ``Farmer.netItems`` - net field 39, a
``NetRef<Inventory>``.  ``Inventory`` is a ``NetList<Item>`` (12 backpack slots
for a starter farmhand), and a change to it rides a message-type-0 farmer delta.

The field-39 delta body (the ``NetRef`` child payload) nests like this, verified
byte-for-byte against captured traffic (see docs/protocol.md section 3.7)::

    bitarray(1) = [True]                 # Inventory net field 0 (the list) dirty
    int32 count                          # the list's element count (12)
    NetRef child: skippable {            # the backing NetArray
        bitarray(15)                     # which slots changed
        per dirty slot:
            byte refDeltaType            # 0 = modify existing item, 1 = set new value
            skippable { payload }        # item field-delta (0) or full value (1)
    }

A *set* (refDeltaType 1) payload is ``NetVersion``, the concrete type name
(``StardewValley.Object``), then the item's full net serialisation.  A *modify*
(refDeltaType 0) payload is the item's net-field delta - stack changes are field
11 (a NetInt), which is how the game counts a growing pickup up.

We fully model the framing (so we can round-trip every captured delta and build
new ones) and build plain ``Object`` items from a captured skeleton; we do not
decode every field of arbitrary items, keeping their payload bytes verbatim.
"""

from __future__ import annotations

import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .binary import Reader, Writer
from .netcode import NetVersion

#: Farmer net-field index of the inventory.
F_ITEMS = 39
#: Backpack slots synced for a starter farmhand (the list count seen on the wire).
INVENTORY_SIZE = 12
#: Length of the backing NetArray's dirty bitarray (as sent by the game).
_SLOT_BITS = 15
_OBJECT_TYPE = "StardewValley.Object"

# The fixed tail of a plain Object's full net serialisation (everything after the
# Item header: modData, tileLocation, owner, type="Basic", flags, price, ...),
# captured identically from real Wood and Stone pickups.  Stack and quality are
# int32s at these offsets; the game leaves them 0 on a fresh add and grows the
# stack with field-11 modify deltas, but the host also accepts them set here.
_OBJECT_TAIL = bytes.fromhex(
    "0100000000000000000000000000000000000000000000000000000000"
    "010542617369630101000000010000000002000000d4feffff"
    "0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
)
_STACK_OFFSET = _OBJECT_TAIL.index(bytes.fromhex("d4feffff")) + 4  # 54
_QUALITY_OFFSET = _STACK_OFFSET + 4  # 58


# ---------------------------------------------------------------- item model


@dataclass
class InvItem:
    """A stackable inventory item (a plain ``Object``)."""

    item_id: str
    name: str
    stack: int = 1
    quality: int = 0
    category: int = -16  # crafting/resource category shared by wood, stone, ...

    def object_body(self) -> bytes:
        """The item's full ``Object`` net serialisation (Item header + fixed tail)."""
        w = Writer()
        w.i32(0)                       # specialVariable
        w.i32(self.category)           # category
        w.bool_(True); w.string(self.name)          # netName
        try:
            psi = int(self.item_id)
        except ValueError:
            psi = -1
        w.i32(psi)                     # parentSheetIndex
        w.bool_(True)                  # hasBeenInInventory
        w.bool_(True); w.string(self.item_id)       # itemId
        tail = bytearray(_OBJECT_TAIL)
        struct.pack_into("<i", tail, _STACK_OFFSET, self.stack)
        struct.pack_into("<i", tail, _QUALITY_OFFSET, self.quality)
        w.raw(bytes(tail))
        return w.getvalue()


# ---------------------------------------------------------------- delta model


@dataclass
class SlotChange:
    """One changed inventory slot within a field-39 delta."""

    slot: int
    ref_type: int          # 0 = modify existing, 1 = set full value
    payload: bytes         # raw item field-delta / full-value bytes (verbatim)


@dataclass
class InventoryDelta:
    list_count: int
    slot_bits: int
    changes: List[SlotChange] = field(default_factory=list)


def decode_inventory_delta(body: bytes) -> Optional[InventoryDelta]:
    """Decode a field-39 (netItems) ``NetRef`` child payload; ``None`` if malformed."""
    try:
        r = Reader(body)
        inv_bits = r.bitarray()
        if not inv_bits or not inv_bits[0]:
            return None
        list_count = r.i32()
        r.u8()               # backing-array NetRef delta-type (child)
        arr = Reader(r.skippable())
        slot_bits = arr.bitarray()
        changes: List[SlotChange] = []
        for slot, dirty in enumerate(slot_bits):
            if not dirty:
                continue
            ref_type = arr.u8()
            payload = arr.skippable()
            changes.append(SlotChange(slot, ref_type, payload))
        return InventoryDelta(list_count, len(slot_bits), changes)
    except (EOFError, ValueError):
        return None


def build_inventory_delta(delta: InventoryDelta) -> bytes:
    """Rebuild a field-39 ``NetRef`` child payload from an :class:`InventoryDelta`."""
    arr = Writer()
    arr.bitarray([any(c.slot == i for c in delta.changes) for i in range(delta.slot_bits)])
    for change in sorted(delta.changes, key=lambda c: c.slot):
        arr.u8(change.ref_type)
        arr.skippable(change.payload)
    ref = Writer()
    ref.u8(0)                # backing-array NetRef child delta
    ref.skippable(arr.getvalue())
    inv = Writer()
    inv.bitarray([True])     # Inventory field 0 (the list) dirty
    inv.i32(delta.list_count)
    inv.raw(ref.getvalue())
    return inv.getvalue()


def _set_value_payload(item: InvItem, version: Optional[NetVersion] = None) -> bytes:
    """The refDeltaType-1 payload that sets a slot to ``item``: version, type, object."""
    w = Writer()
    (version or NetVersion([1, 0])).write(w)
    w.string(_OBJECT_TYPE)
    w.raw(item.object_body())
    return w.getvalue()


def build_set_slot_body(slot: int, item: InvItem, *, list_count: int = INVENTORY_SIZE,
                        version: Optional[NetVersion] = None) -> bytes:
    """Build a field-39 body that sets inventory ``slot`` to ``item`` (full value)."""
    delta = InventoryDelta(list_count, _SLOT_BITS,
                           [SlotChange(slot, 1, _set_value_payload(item, version))])
    return build_inventory_delta(delta)


# ---------------------------------------------------------------- inventory read


def parse_inventory_xml(xml: bytes) -> List[Optional[InvItem]]:
    """Read the occupied slots from a farmhand's ``<items>`` in its Farmer XML.

    Returns a list aligned to slots; ``None`` marks an empty slot.  Best-effort:
    an unreadable document yields an all-empty inventory.
    """
    slots: List[Optional[InvItem]] = []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return slots
    items = root.find("items")
    if items is None:
        return slots
    for el in list(items):
        # an empty slot serialises with no children (or an xsi:nil marker)
        if len(el) == 0:
            slots.append(None)
            continue
        name = el.findtext("Name") or el.findtext("name") or ""
        item_id = el.findtext("ItemId") or el.findtext("itemId") or el.findtext("ParentSheetIndex") or ""
        stack = int(el.findtext("Stack") or el.findtext("stack") or "1")
        quality = int(el.findtext("Quality") or el.findtext("quality") or "0")
        slots.append(InvItem(str(item_id), name, stack, quality))
    return slots


# ---------------------------------------------------------------- drop table

#: What a cleared tile yields, by the thing's in-game name / terrain kind.
#: (item_id, display name).  Unknown things drop nothing.
DROPS: Dict[str, Tuple[str, str]] = {
    "Stone": ("390", "Stone"),
    "Twig": ("388", "Wood"),
    "Tree": ("388", "Wood"),
    "Weeds": ("771", "Fiber"),
    "Grass": ("178", "Hay"),
}
