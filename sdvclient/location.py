"""Decode a Stardew Valley game location: what is on the map and where.

A ``GameLocation`` is synced as one big ``NetRoot`` full-serialisation in a
``locationIntroduction`` (message type 3) and thereafter patched by
``locationDelta`` (message type 6) messages.  The full body is enormous
(~200 KB for a farm) and most of its 51 net fields hold data we do not need.

This module decodes the two fields that describe the *things scattered around
the map*:

* ``netObjects`` (field 16) - the object layer: stone, twigs, placed chests,
  artifact spots, machines, ... keyed by tile.
* ``terrainFeatures`` (field 19) - trees, grass, tilled dirt, ... keyed by tile.

Both are ``NetVector2Dictionary`` fields: a tile ``(x, y)`` maps to a value
whose concrete .NET type name is embedded inline (``StardewValley.Object``,
``StardewValley.TerrainFeatures.Tree`` and so on).  Rather than fully parse
every value's net fields - which would mean re-implementing most of the game's
object graph, including the NPC collection that sits between the two fields we
want - we locate each entry by its embedded type name and recover the tile key
that precedes it.  Each dictionary entry is laid out as::

    key: Vector2 (two float32)   version: NetVersion   refFlag: byte   typeName: string   <value fields...>

The recovery is version-aware, so entries whose ``NetVersion`` vector is longer
than the usual empty one are still found.  See docs/protocol.md section 3.6.

The result is deliberately best-effort: an unparseable stretch is skipped, not
fatal, so a decode never raises on live data.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .binary import Reader, Writer
from .netcode import NetVersion
from .protocol import parse_location_introduction

#: GameLocation net-field indices (1.6.15) for the two tile dictionaries.
FIELD_OBJECTS = 16
FIELD_TERRAIN = 19
GAMELOCATION_FIELD_COUNT = 51

Tile = Tuple[int, int]

# Tree.treeType strings seen in 1.6 save/net data (StardewValley/Data/WildTrees ids).
TREE_NAMES: Dict[str, str] = {
    "1": "oak", "2": "maple", "3": "pine", "4": "winterTree1", "5": "winterTree2",
    "6": "palm", "7": "mushroom", "8": "mahogany", "9": "palm2", "10": "greenRain1",
    "11": "greenRain2", "13": "greenRain3", "12": "mystic",
}


@dataclass
class MapObject:
    """An entry of the object layer (``GameLocation.objects``)."""

    tile: Tile
    type_name: str  # e.g. "StardewValley.Object", "StardewValley.Objects.Chest"
    name: str = ""  # in-game name: "Stone", "Twig", "Chest", "Artifact Spot", ...

    @property
    def is_stone(self) -> bool:
        return self.name == "Stone"

    @property
    def is_twig(self) -> bool:
        return self.name == "Twig"

    @property
    def is_weeds(self) -> bool:
        return self.name in ("Weeds", "Grass")

    @property
    def is_chest(self) -> bool:
        return self.type_name.endswith("Chest")

    def __str__(self) -> str:
        return f"{self.name or self.type_name.rsplit('.', 1)[-1]}@{self.tile}"


@dataclass
class TerrainFeature:
    """An entry of the terrain layer (``GameLocation.terrainFeatures``)."""

    tile: Tile
    kind: str  # short class name: "Tree", "Grass", "HoeDirt", "Flooring", ...
    variant: str = ""  # e.g. Tree.treeType id ("1".."13")

    @property
    def is_tree(self) -> bool:
        return self.kind == "Tree"

    @property
    def is_grass(self) -> bool:
        return self.kind == "Grass"

    @property
    def tree_name(self) -> Optional[str]:
        return TREE_NAMES.get(self.variant) if self.is_tree else None

    def __str__(self) -> str:
        extra = f" {self.tree_name or self.variant}" if self.variant else ""
        return f"{self.kind}{extra}@{self.tile}"


@dataclass
class Location:
    """A decoded map: its objects and terrain features keyed by tile."""

    name: str = ""
    type_name: str = ""
    objects: Dict[Tile, MapObject] = field(default_factory=dict)
    terrain: Dict[Tile, TerrainFeature] = field(default_factory=dict)

    # -- convenience views -------------------------------------------------
    @property
    def trees(self) -> List[TerrainFeature]:
        return [t for t in self.terrain.values() if t.is_tree]

    @property
    def grass(self) -> List[TerrainFeature]:
        return [t for t in self.terrain.values() if t.is_grass]

    @property
    def stones(self) -> List[MapObject]:
        return [o for o in self.objects.values() if o.is_stone]

    @property
    def twigs(self) -> List[MapObject]:
        return [o for o in self.objects.values() if o.is_twig]

    def things_near(self, tile: Tile, radius: int = 5) -> List[object]:
        """All objects and terrain features within ``radius`` tiles of ``tile``.

        Returned nearest-first (Chebyshev distance); mixes ``MapObject`` and
        ``TerrainFeature``.
        """
        cx, cy = tile
        out: List[Tuple[int, object]] = []
        for coll in (self.objects, self.terrain):
            for (x, y), thing in coll.items():
                d = max(abs(x - cx), abs(y - cy))
                if d <= radius:
                    out.append((d, thing))
        out.sort(key=lambda p: p[0])
        return [thing for _, thing in out]

    def __str__(self) -> str:
        return (f"{self.name or self.type_name}: {len(self.objects)} objects "
                f"({len(self.stones)} stone, {len(self.twigs)} twig), "
                f"{len(self.terrain)} terrain ({len(self.trees)} tree, {len(self.grass)} grass)")


# ---------------------------------------------------------------- scanning helpers

_OBJECT_PREFIX = b"StardewValley.Object"
_TERRAIN_PREFIX = b"StardewValley.TerrainFeatures."


def _ascii_run(data: bytes, start: int, limit: int = 96) -> str:
    """Read printable ASCII from ``start`` until the first non-printable byte."""
    end = start
    stop = min(len(data), start + limit)
    while end < stop and 32 <= data[end] < 127:
        end += 1
    return data[start:end].decode("ascii", "replace")


def _key_before(data: bytes, name_start: int) -> Optional[Tile]:
    """Recover the ``Vector2`` tile key that precedes a dictionary entry's type name.

    Entry layout is ``key(8) version(1+4c) refFlag(1) lenByte typeName``; the
    ``NetVersion`` vector length ``c`` varies, so try the small values it takes
    in practice and accept the one whose version count byte matches and whose
    eight preceding bytes read as two integer tile coordinates.
    """
    version_end = name_start - 2  # skip the type-name length byte and the ref flag
    for c in range(0, 4):
        version_start = version_end - (1 + 4 * c)
        if version_start < 8 or data[version_start] != c:
            continue
        kp = version_start - 8
        fx, fy = struct.unpack_from("<ff", data, kp)
        if fx.is_integer() and fy.is_integer() and -4 <= fx < 1000 and -4 <= fy < 1000:
            return (int(fx), int(fy))
    return None


def _scan_objects(data: bytes) -> Dict[Tile, MapObject]:
    out: Dict[Tile, MapObject] = {}
    i = data.find(_OBJECT_PREFIX)
    while i != -1:
        tile = _key_before(data, i)
        if tile is not None:
            type_name = _ascii_run(data, i)
            # the object's in-game name (NetString) follows shortly after the type name
            name = _first_string_after(data, i + len(type_name))
            out[tile] = MapObject(tile, type_name, name)
        i = data.find(_OBJECT_PREFIX, i + 1)
    return out


def _scan_terrain(data: bytes) -> Dict[Tile, TerrainFeature]:
    out: Dict[Tile, TerrainFeature] = {}
    i = data.find(_TERRAIN_PREFIX)
    while i != -1:
        tile = _key_before(data, i)
        if tile is not None:
            type_name = _ascii_run(data, i)
            kind = type_name.rsplit(".", 1)[-1]
            variant = ""
            if kind == "Tree":
                variant = _first_string_after(data, i + len(type_name), max_len=4) or ""
            out[tile] = TerrainFeature(tile, kind, variant)
        i = data.find(_TERRAIN_PREFIX, i + 1)
    return out


def _first_string_after(data: bytes, pos: int, scan: int = 64, max_len: int = 32) -> str:
    """Find the first ``varint-length + printable ASCII`` string at/after ``pos``."""
    for i in range(pos, min(len(data), pos + scan)):
        n = data[i]
        if 1 <= n <= max_len and i + 1 + n <= len(data):
            chunk = data[i + 1:i + 1 + n]
            if all(32 <= c < 127 for c in chunk):
                return chunk.decode("ascii")
    return ""


# ---------------------------------------------------------------- public API


def parse_location_snapshot(data: bytes) -> Location:
    """Decode a ``locationIntroduction`` (message type 3) body into a :class:`Location`.

    Recovers the map name from the header and every tile-keyed object and
    terrain feature from the body.  Never raises on malformed data - whatever
    could be decoded is returned.
    """
    loc = Location()
    try:
        intro = parse_location_introduction(data)
        loc.name = intro.name or intro.unique_name or ""
        loc.type_name = intro.type_name
    except Exception:  # noqa: BLE001 - header quirks must not lose the body
        pass
    loc.objects = _scan_objects(data)
    loc.terrain = _scan_terrain(data)
    return loc


def _apply_vector2dict_delta(r: Reader, loc: Location, objects: bool) -> bool:
    """Apply one ``NetVector2Dictionary`` delta (changes then updates) to ``loc``.

    Handles removals (drop the tile) and updates (existing entry changed - the
    tile stays).  A value-carrying addition cannot be length-measured without a
    full value decoder, so its tile/type is recorded and ``True`` (stop) is
    returned; otherwise the whole delta is consumed and ``False`` is returned.
    """
    coll = loc.objects if objects else loc.terrain
    changes = r.varint()
    for _ in range(changes):
        removal = r.u8() != 0
        tile = (int(r.f32()), int(r.f32()))
        NetVersion.read(r)
        if removal:
            coll.pop(tile, None)
        else:
            # an addition: we can see the tile and its type but not the value length
            type_name = _ascii_run(r.data, _find_type_name(r.data, r.pos))
            if objects:
                coll[tile] = MapObject(tile, type_name or "StardewValley.Object")
            elif type_name:
                coll[tile] = TerrainFeature(tile, type_name.rsplit(".", 1)[-1])
            return True
    updates = r.varint()
    for _ in range(updates):
        r.f32()
        r.f32()
        NetVersion.read(r)
        r.skippable()
    return False


def build_location_removal_delta(
    name: str,
    is_structure: bool,
    root_version: NetVersion,
    tile: Tile,
    *,
    objects: bool,
) -> bytes:
    """Build a ``locationDelta`` (message type 6) body that removes one tile entry.

    Removes the entry at ``tile`` from ``netObjects`` (``objects=True``) or
    ``terrainFeatures`` (``objects=False``).  This is byte-for-byte the delta a
    real 1.6.15 client emits when a tool clears that tile (verified against
    captured traffic): a single ``NetVector2Dictionary`` removal, empty entry
    version, no updates.  ``root_version`` is the location root's version clock
    as last seen from the server, with the sender's own slot bumped.
    """
    field_index = FIELD_OBJECTS if objects else FIELD_TERRAIN
    fb = Writer()
    fb.varint(1)  # one change
    fb.u8(1)      # removal
    fb.f32(float(tile[0]))
    fb.f32(float(tile[1]))
    NetVersion([]).write(fb)  # entry version (empty, as real removals send)
    fb.varint(0)  # no updates
    body = Writer()
    bits = [i == field_index for i in range(GAMELOCATION_FIELD_COUNT)]
    body.bitarray(bits)
    body.raw(fb.getvalue())
    w = Writer()
    w.bool_(is_structure)
    w.string(name)
    root_version.write(w)
    w.u8(0)  # RefDeltaType.ChildDelta
    w.skippable(body.getvalue())
    return w.getvalue()


def read_location_intro_version(data: bytes) -> Optional[NetVersion]:
    """Read the location root version from a ``locationIntroduction`` (message type 3) header."""
    r = Reader(data)
    try:
        r.bool_()  # force_current
        r.u8()     # peer id
        return NetVersion.read(r)
    except (EOFError, ValueError):
        return None


def read_location_delta_version(data: bytes) -> Optional[Tuple[bool, str, NetVersion]]:
    """Read the wrapper of a ``locationDelta`` body: (is_structure, name, root_version)."""
    r = Reader(data)
    try:
        is_structure = r.bool_()
        name = r.string()
        version = NetVersion.read(r)
    except (EOFError, ValueError, UnicodeDecodeError):
        return None
    return is_structure, name, version


def _find_type_name(data: bytes, pos: int, scan: int = 32) -> int:
    for i in range(pos, min(len(data), pos + scan)):
        if data[i:i + 13] == b"StardewValley":
            return i
    return pos


def apply_location_delta(loc: Location, data: bytes) -> bool:
    """Apply a ``locationDelta`` (message type 6) body to ``loc`` in place.

    Only the object (16) and terrain (19) dictionary fields are applied; other
    fields are ignored.  Because net fields are written in ascending order with
    no length prefix, decoding stops at the first field whose type is not one we
    parse.  Returns ``True`` if the delta was for this location and was read,
    ``False`` if it targeted a different map.
    """
    r = Reader(data)
    try:
        r.bool_()  # isStructure
        name = r.string()
        NetVersion.read(r)
        delta_type = r.u8()
        body = r.skippable()
    except (EOFError, ValueError, UnicodeDecodeError):
        return False
    if loc.name and name and name != loc.name:
        return False
    if delta_type != 0:
        return True
    br = Reader(body)
    try:
        bits = br.bitarray()
    except (EOFError, ValueError):
        return True
    dirty = [i for i, b in enumerate(bits) if b]
    for index in dirty:
        if index not in (16, 19):
            break  # unknown field type: cannot skip it, stop here
        try:
            stopped = _apply_vector2dict_delta(br, loc, objects=(index == 16))
        except (EOFError, ValueError, UnicodeDecodeError):
            break
        if stopped:
            break
    return True
