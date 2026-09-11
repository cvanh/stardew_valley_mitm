"""Tests for sdvclient.inventory, using real captured field-39 (netItems) deltas.

The hex blobs below are genuine client->server inventory deltas captured from a
live 1.6.15 game (message type 0, net field 39 body): two single-slot stack
changes and the full-value adds of Wood (388) and Stone (390).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from sdvclient.inventory import (  # noqa: E402
    InvItem,
    build_inventory_delta,
    build_set_slot_body,
    decode_inventory_delta,
)

# field-39 NetRef child payloads (the skippable body after the netItems ref byte)
SAMPLE_STACK_A = bytes.fromhex("01010c00000000100000000f0100000800000016000800bd000000")
SAMPLE_STACK_B = bytes.fromhex("01010c00000000120000000f1000010a00000002780200000000000000")

# real full-value slot payloads (NetVersion + type name + object body) captured
# from Wood (388) and Stone (390) pickups; the object body follows the 21-byte
# "StardewValley.Object" type-name string.
WOOD_FULL = bytes.fromhex("023c10000000000000145374617264657756616c6c65792e4f626a65637400000000f0ffffff0104576f6f64840100000101033338380100000000000000000000000000000000000000000000000000000000010542617369630101000000010000000002000000d4feffff0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000")  # noqa: E501
STONE_FULL = bytes.fromhex("026b2b000000000000145374617264657756616c6c65792e4f626a65637400000000f0ffffff010553746f6e65860100000101033339300100000000000000000000000000000000000000000000000000000000010542617369630101000000010000000002000000d4feffff0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000")  # noqa: E501


def _objbody(full):
    from sdvclient.binary import Reader
    from sdvclient.netcode import NetVersion
    r = Reader(full)
    NetVersion.read(r)
    r.string()  # type name
    return full[r.pos:]


WOOD_OBJBODY = _objbody(WOOD_FULL)
STONE_OBJBODY = _objbody(STONE_FULL)


class InventoryDeltaTests(unittest.TestCase):
    def test_round_trip_stack_changes(self):
        for sample in (SAMPLE_STACK_A, SAMPLE_STACK_B):
            delta = decode_inventory_delta(sample)
            self.assertIsNotNone(delta)
            self.assertEqual(delta.list_count, 12)
            self.assertEqual(build_inventory_delta(delta), sample)

    def test_stack_change_structure(self):
        delta = decode_inventory_delta(SAMPLE_STACK_A)
        self.assertEqual(len(delta.changes), 1)
        change = delta.changes[0]
        self.assertEqual(change.slot, 0)
        self.assertEqual(change.ref_type, 0)  # modify existing item

    def test_object_encoder_matches_real_bytes(self):
        # our Object serialiser must reproduce the captured Wood and Stone items
        self.assertEqual(InvItem("388", "Wood", stack=0).object_body(), WOOD_OBJBODY)
        self.assertEqual(InvItem("390", "Stone", stack=0).object_body(), STONE_OBJBODY)

    def test_stack_and_quality_patch(self):
        body = InvItem("390", "Stone", stack=17, quality=2).object_body()
        # differs from the stack-0 template only in the stack/quality int32s
        base = InvItem("390", "Stone", stack=0, quality=0).object_body()
        self.assertEqual(len(body), len(base))
        self.assertNotEqual(body, base)

    def test_build_set_slot_round_trips_through_decoder(self):
        body = build_set_slot_body(3, InvItem("390", "Stone", stack=5))
        delta = decode_inventory_delta(body)
        self.assertIsNotNone(delta)
        self.assertEqual(delta.changes[0].slot, 3)
        self.assertEqual(delta.changes[0].ref_type, 1)  # full value
        self.assertEqual(build_inventory_delta(delta), body)


if __name__ == "__main__":
    unittest.main()
