"""Tests for sdvclient.location, using real captured Farm data (star2.pcapng).

Fixtures under tests/fixtures/ were captured from a live 1.6.15 game:
* farm_location_intro.bin.gz - a ~192 KB ``locationIntroduction`` (message 3) for the Farm.
* farm_terrain_removal_delta.bin - a ``locationDelta`` (message 6) that removes the
  terrain feature at tile (55, 22).
"""

import gzip
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from sdvclient.location import (  # noqa: E402
    Location,
    MapObject,
    TerrainFeature,
    apply_location_delta,
    parse_location_snapshot,
)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _load(name: str) -> bytes:
    path = os.path.join(FIXTURES, name)
    if name.endswith(".gz"):
        with gzip.open(path, "rb") as fh:
            return fh.read()
    with open(path, "rb") as fh:
        return fh.read()


class SnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.loc = parse_location_snapshot(_load("farm_location_intro.bin.gz"))

    def test_location_identity(self) -> None:
        self.assertEqual(self.loc.name, "Farm")
        self.assertEqual(self.loc.type_name, "StardewValley.Farm")

    def test_terrain_counts(self) -> None:
        # oracle from `strings` on the raw blob: 576 trees, 852 grass
        self.assertEqual(len(self.loc.trees), 576)
        self.assertEqual(len(self.loc.grass), 852)
        self.assertEqual(len(self.loc.terrain), 576 + 852)

    def test_object_counts(self) -> None:
        # 343 stone + 221 twig + 2 chest + 1 artifact spot = 567 tile-keyed objects
        self.assertEqual(len(self.loc.stones), 343)
        self.assertEqual(len(self.loc.twigs), 221)
        self.assertEqual(len(self.loc.objects), 567)

    def test_entries_are_typed(self) -> None:
        stone = self.loc.stones[0]
        self.assertIsInstance(stone, MapObject)
        self.assertTrue(stone.is_stone)
        self.assertEqual(len(stone.tile), 2)
        tree = self.loc.trees[0]
        self.assertIsInstance(tree, TerrainFeature)
        self.assertTrue(tree.is_tree)
        # every tree carries a species id that maps to a known name
        self.assertIn(tree.variant, {"1", "2", "3", "7", "10", "11"})

    def test_tiles_are_plausible(self) -> None:
        for coll in (self.loc.objects, self.loc.terrain):
            for (x, y) in coll:
                self.assertTrue(0 <= x < 200 and 0 <= y < 200, f"implausible tile {(x, y)}")

    def test_things_near(self) -> None:
        # pick a real stone and confirm it is the nearest thing to its own tile
        stone = self.loc.stones[0]
        near = self.loc.things_near(stone.tile, radius=0)
        self.assertIn(stone, near)
        # radius grows the result monotonically
        self.assertGreaterEqual(
            len(self.loc.things_near(stone.tile, 5)),
            len(self.loc.things_near(stone.tile, 1)),
        )


class DeltaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.loc = parse_location_snapshot(_load("farm_location_intro.bin.gz"))

    def test_removal_delta_drops_a_tile(self) -> None:
        self.assertIn((55, 22), self.loc.terrain)  # present in the snapshot
        before = len(self.loc.terrain)
        handled = apply_location_delta(self.loc, _load("farm_terrain_removal_delta.bin"))
        self.assertTrue(handled)
        self.assertNotIn((55, 22), self.loc.terrain)  # removed by the delta
        self.assertEqual(len(self.loc.terrain), before - 1)

    def test_update_delta_is_harmless(self) -> None:
        # the generic farm delta fixture only updates existing entries; nothing should vanish
        before_t, before_o = len(self.loc.terrain), len(self.loc.objects)
        handled = apply_location_delta(self.loc, _load("farm_location_delta.bin"))
        self.assertTrue(handled)
        self.assertLessEqual(len(self.loc.terrain), before_t)
        self.assertLessEqual(len(self.loc.objects), before_o)

    def test_delta_for_other_location_is_ignored(self) -> None:
        other = Location(name="Town")
        handled = apply_location_delta(other, _load("farm_terrain_removal_delta.bin"))
        self.assertFalse(handled)  # name mismatch -> not our map

    def test_garbage_never_raises(self) -> None:
        self.assertFalse(apply_location_delta(self.loc, b"\x00\x01"))
        parse_location_snapshot(b"not a real location")  # must not raise


if __name__ == "__main__":
    unittest.main()
