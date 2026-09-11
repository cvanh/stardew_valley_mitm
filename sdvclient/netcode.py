"""The small part of Stardew Valley's ``Netcode`` serialisation this client needs.

Netcode syncs object trees ("net fields") as *deltas*: a bit array marks which
fields changed, followed by each changed field in declaration order.  A root
object (``NetRoot<T>``) prefixes that with a version vector (one counter per
peer) used for conflict resolution.

Only the leading fields of ``Farmer`` (which come from ``Character``) and of
``NetWorldState`` are decoded here; parsing stops at the first field whose
encoding is not known.  That is enough for positions, names, locations and
the in-game clock.  Everything is documented in docs/protocol.md.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .binary import Reader, Writer


@dataclass
class NetVersion:
    """Netcode.NetVersion: a vector clock, serialised as ``byte count`` + ``uint32[count]``."""

    vector: List[int] = field(default_factory=list)

    @classmethod
    def read(cls, r: Reader) -> "NetVersion":
        n = r.u8()
        return cls([r.u32() for _ in range(n)])

    def write(self, w: Writer) -> None:
        w.u8(len(self.vector))
        for v in self.vector:
            w.u32(v)

    def bump(self, peer: int = 0) -> None:
        while len(self.vector) <= peer:
            self.vector.append(0)
        self.vector[peer] += 1

    def __str__(self) -> str:
        return "v" + ",".join(str(v) for v in self.vector) if self.vector else "v0"


# ---------------------------------------------------------------- Farmer net fields

#: Number of net fields in ``Farmer`` on the 1.6.15 server the pcap was taken
#: against (the 1.6.8 decompile has 157).  The client learns the real value
#: from the first farmer delta the server sends and overrides this default.
FARMER_FIELD_COUNT = 158

# Character.initNetFields() order - identical in every 1.6.x build seen so far.
F_SPRITE = 0
F_POSITION = 1
F_FACING_DIRECTION = 2
F_SPEED = 3
F_ADDED_SPEED = 4
F_NAME = 5
F_SCALE = 6
F_CURRENT_LOCATION = 7
F_SWIMMING = 8
F_COLLIDES_WITH_OTHER_CHARACTERS = 9
F_FACING_DIRECTION_BEFORE_SPEAKING = 10
F_FACE_TOWARD_FARMER_RADIUS = 11
F_FACE_AWAY_FROM_FARMER = 12
F_WHO_TO_FACE = 13
F_FACE_TOWARD_FARMER_EVENT = 14
F_WILL_DESTROY_OBJECTS_UNDERFOOT = 15
F_FORCE_ONE_TILE_WIDE = 16
F_SIMPLE_NON_VILLAGER_NPC = 17
F_HIDE_FROM_ANIMAL_SOCIAL_MENU = 18
F_NET_EVENT_ACTOR = 19
F_MOD_DATA = 20
CHARACTER_FIELD_COUNT = 21

# Farmer.initNetFields() continues at index 21.
F_UNIQUE_MULTIPLAYER_ID = 21
F_USER_ID = 22
F_PLATFORM_TYPE = 23
F_PLATFORM_ID = 24
F_HAS_MENU_OPEN = 25
F_FARMER_RENDERER = 26
F_GENDER = 27
F_BATHING_CLOTHES = 28
F_SHIRT = 29
F_PANTS = 30
F_HAIR = 31
F_SKIN = 32
F_SHOES = 33
F_ACCESSORY = 34
F_FACIAL_HAIR = 35
F_HAIRSTYLE_COLOR = 36
F_PANTS_COLOR = 37
F_EYE_COLOR = 38
F_ITEMS = 39
F_CURRENT_TOOL_INDEX = 40
F_TEMPORARY_ITEM = 41
F_CURSOR_SLOT_ITEM = 42
F_FIRE_TOOL_EVENT = 43
F_BEGIN_USING_TOOL_EVENT = 44
F_END_USING_TOOL_EVENT = 45
F_HAT = 46
F_BOOTS = 47
F_LEFT_RING = 48
F_RIGHT_RING = 49
F_HIDDEN = 50
F_USING_TOOL = 51
F_IS_IN_BED = 52
F_BOBBER_STYLE = 53
F_CAVE_CHOICE = 54
F_HOUSE_UPGRADE_LEVEL = 55
F_DAYS_UNTIL_HOUSE_UPGRADE = 56
F_SPOUSE = 57
F_MAIL_RECEIVED = 58
F_MAIL_FOR_TOMORROW = 59
F_MAILBOX = 60
F_TRIGGER_ACTIONS_RUN = 61
F_EVENTS_SEEN = 62
F_LOCATIONS_VISITED = 63
F_SECRET_NOTES_SEEN = 64
F_MOUNT = 65
F_DANCE_PARTNER = 66
F_DIVORCE_TONIGHT = 67
F_CHANGE_WALLET_TYPE_TONIGHT = 68
F_IS_CUSTOMIZED = 69
F_HOME_LOCATION = 70
F_FARM_NAME = 71
F_FAVORITE_THING = 72
F_HORSE_NAME = 73
F_MILLISECONDS_PLAYED = 74

FIELD_NAMES: Dict[int, str] = {
    0: "sprite", 1: "position", 2: "facingDirection", 3: "speed", 4: "addedSpeed", 5: "name",
    6: "scale", 7: "currentLocation", 8: "swimming", 9: "collidesWithOtherCharacters",
    10: "facingDirectionBeforeSpeakingToPlayer", 11: "faceTowardFarmerRadius",
    12: "faceAwayFromFarmer", 13: "whoToFace", 14: "faceTowardFarmerEvent",
    15: "willDestroyObjectsUnderfoot", 16: "forceOneTileWide", 17: "simpleNonVillagerNPC",
    18: "hideFromAnimalSocialMenu", 19: "netEventActor", 20: "modData",
    21: "uniqueMultiplayerID", 22: "userID", 23: "platformType", 24: "platformID",
    25: "hasMenuOpen", 26: "farmerRenderer", 27: "gender", 28: "bathingClothes", 29: "shirt",
    30: "pants", 31: "hair", 32: "skin", 33: "shoes", 34: "accessory", 35: "facialHair",
    36: "hairstyleColor", 37: "pantsColor", 38: "eyeColor", 39: "items", 40: "currentToolIndex",
    41: "temporaryItem", 42: "cursorSlotItem", 43: "fireToolEvent", 44: "beginUsingToolEvent",
    45: "endUsingToolEvent", 46: "hat", 47: "boots", 48: "leftRing", 49: "rightRing",
    50: "hidden", 51: "usingTool", 52: "isInBed", 53: "bobberStyle", 54: "caveChoice",
    55: "houseUpgradeLevel", 56: "daysUntilHouseUpgrade", 57: "spouse", 58: "mailReceived",
    59: "mailForTomorrow", 60: "mailbox", 61: "triggerActionsRun", 62: "eventsSeen",
    63: "locationsVisited", 64: "secretNotesSeen", 65: "mount", 66: "dancePartner",
    67: "divorceTonight", 68: "changeWalletTypeTonight", 69: "isCustomized", 70: "homeLocation",
    71: "farmName", 72: "favoriteThing", 73: "horseName", 74: "millisecondsPlayed",
}

# ---------------------------------------------------------------- field decoders

Decoder = Callable[[Reader], Any]


def _d_bool(r: Reader) -> bool:
    return r.bool_()


def _d_i16(r: Reader) -> int:
    return r.i16()


def _d_i32(r: Reader) -> int:
    return r.i32()


def _d_u32(r: Reader) -> int:
    return r.u32()


def _d_i64(r: Reader) -> int:
    return r.i64()


def _d_f32(r: Reader) -> float:
    return r.f32()


def _d_opt_string(r: Reader) -> Optional[str]:
    """NetString delta: bool has-value, then the string."""
    return r.string() if r.bool_() else None


def _d_ref(r: Reader) -> None:
    """NetRef delta: a delta-type byte followed by a length-prefixed (skippable) body."""
    r.u8()
    r.skippable()
    return None


def _d_event0(r: Reader) -> int:
    """NetEvent0 is a NetInt counter."""
    return r.i32()


def _event1(arg: Decoder) -> Decoder:
    """AbstractNetEvent1: 7-bit count, then (uint32 delay, argument) per event."""

    def decode(r: Reader) -> List[Tuple[int, Any]]:
        count = r.varint()
        return [(r.u32(), arg(r)) for _ in range(count)]

    return decode


def _d_position(r: Reader) -> Dict[str, Any]:
    """NetPosition.NetFields = [Field: NetVector2, pauseEvent: NetEvent1Field<bool>, moving: NetBool]."""
    bits = r.bitarray()
    out: Dict[str, Any] = {}
    if len(bits) > 0 and bits[0]:
        out["position"] = (r.f32(), r.f32())
    if len(bits) > 1 and bits[1]:
        out["pause_events"] = _event1(_d_bool)(r)
    if len(bits) > 2 and bits[2]:
        out["moving"] = r.bool_()
    return out


def _d_location_ref(r: Reader) -> Dict[str, Any]:
    """NetLocationRef.NetFields = [locationName: NetString, isStructure: NetBool]."""
    bits = r.bitarray()
    out: Dict[str, Any] = {}
    if len(bits) > 0 and bits[0]:
        out["name"] = _d_opt_string(r)
    if len(bits) > 1 and bits[1]:
        out["is_structure"] = r.bool_()
    return out


def _d_farmer_ref(r: Reader) -> Dict[str, Any]:
    """NetFarmerRef.NetFields = [defined: NetBool, uid: NetLong]."""
    bits = r.bitarray()
    out: Dict[str, Any] = {}
    if len(bits) > 0 and bits[0]:
        out["defined"] = r.bool_()
    if len(bits) > 1 and bits[1]:
        out["uid"] = r.i64()
    return out


def _d_dance_partner(r: Reader) -> Dict[str, Any]:
    """NetDancePartner.NetFields = [farmer.NetFields, villager: NetString]."""
    bits = r.bitarray()
    out: Dict[str, Any] = {}
    if len(bits) > 0 and bits[0]:
        out["farmer"] = _d_farmer_ref(r)
    if len(bits) > 1 and bits[1]:
        out["villager"] = _d_opt_string(r)
    return out


def _hashset(value: Decoder) -> Decoder:
    """NetHashSet delta: 7-bit count, then (bool removal, value) per change."""

    def decode(r: Reader) -> List[Tuple[bool, Any]]:
        count = r.varint()
        return [(r.bool_(), value(r)) for _ in range(count)]

    return decode


def _d_string_list(r: Reader) -> int:
    """NetList<T> delta: count (NetInt) followed by the backing NetArray ref delta."""
    count = r.i32()
    _d_ref(r)
    return count


def _dictionary(key: Decoder, value_full: Decoder) -> Decoder:
    """NetDictionary delta: additions/removals, then updates of existing entries."""

    def decode(r: Reader) -> Dict[str, Any]:
        changes = []
        for _ in range(r.varint()):
            removal = r.u8() != 0
            k = key(r)
            NetVersion.read(r)
            changes.append((removal, k, None if removal else value_full(r)))
        updates = []
        for _ in range(r.varint()):
            k = key(r)
            NetVersion.read(r)
            r.skippable()  # field delta; contents depend on the value type
            updates.append(k)
        return {"changes": changes, "updates": updates}

    return decode


def _d_string_key(r: Reader) -> str:
    return r.string()


FARMER_DECODERS: Dict[int, Decoder] = {
    F_SPRITE: _d_ref,
    F_POSITION: _d_position,
    F_FACING_DIRECTION: _d_i32,
    F_SPEED: _d_i32,
    F_ADDED_SPEED: _d_f32,
    F_NAME: _d_opt_string,
    F_SCALE: _d_f32,
    F_CURRENT_LOCATION: _d_location_ref,
    F_SWIMMING: _d_bool,
    F_COLLIDES_WITH_OTHER_CHARACTERS: _d_bool,
    F_FACING_DIRECTION_BEFORE_SPEAKING: _d_i32,
    F_FACE_TOWARD_FARMER_RADIUS: _d_i32,
    F_FACE_AWAY_FROM_FARMER: _d_bool,
    F_WHO_TO_FACE: _d_farmer_ref,
    F_FACE_TOWARD_FARMER_EVENT: _event1(_d_i32),
    F_WILL_DESTROY_OBJECTS_UNDERFOOT: _d_bool,
    F_FORCE_ONE_TILE_WIDE: _d_bool,
    F_SIMPLE_NON_VILLAGER_NPC: _d_bool,
    F_HIDE_FROM_ANIMAL_SOCIAL_MENU: _d_bool,
    F_NET_EVENT_ACTOR: _d_bool,
    F_MOD_DATA: _dictionary(_d_string_key, _d_opt_string),
    F_UNIQUE_MULTIPLAYER_ID: _d_i64,
    F_USER_ID: _d_opt_string,
    F_PLATFORM_TYPE: _d_opt_string,
    F_PLATFORM_ID: _d_opt_string,
    F_HAS_MENU_OPEN: _d_bool,
    F_FARMER_RENDERER: _d_ref,
    F_GENDER: _d_i16,
    F_BATHING_CLOTHES: _d_bool,
    F_SHIRT: _d_opt_string,
    F_PANTS: _d_opt_string,
    F_HAIR: _d_i32,
    F_SKIN: _d_i32,
    F_SHOES: _d_opt_string,
    F_ACCESSORY: _d_i32,
    F_FACIAL_HAIR: _d_i32,
    F_HAIRSTYLE_COLOR: _d_u32,
    F_PANTS_COLOR: _d_u32,
    F_EYE_COLOR: _d_u32,
    F_ITEMS: _d_ref,
    F_CURRENT_TOOL_INDEX: _d_i32,
    F_TEMPORARY_ITEM: _d_ref,
    F_CURSOR_SLOT_ITEM: _d_ref,
    F_FIRE_TOOL_EVENT: _d_event0,
    F_BEGIN_USING_TOOL_EVENT: _d_event0,
    F_END_USING_TOOL_EVENT: _d_event0,
    F_HAT: _d_ref,
    F_BOOTS: _d_ref,
    F_LEFT_RING: _d_ref,
    F_RIGHT_RING: _d_ref,
    F_HIDDEN: _d_bool,
    F_USING_TOOL: _d_bool,
    F_IS_IN_BED: _d_bool,
    F_BOBBER_STYLE: _d_i32,
    F_CAVE_CHOICE: _d_i32,
    F_HOUSE_UPGRADE_LEVEL: _d_i32,
    F_DAYS_UNTIL_HOUSE_UPGRADE: _d_i32,
    F_SPOUSE: _d_opt_string,
    F_MAIL_RECEIVED: _hashset(_d_opt_string),
    F_MAIL_FOR_TOMORROW: _hashset(_d_opt_string),
    F_MAILBOX: _d_string_list,
    F_TRIGGER_ACTIONS_RUN: _hashset(_d_opt_string),
    F_EVENTS_SEEN: _hashset(_d_opt_string),
    F_LOCATIONS_VISITED: _hashset(_d_opt_string),
    F_SECRET_NOTES_SEEN: _hashset(_d_i32),
    F_MOUNT: _d_ref,
    F_DANCE_PARTNER: _d_dance_partner,
    F_DIVORCE_TONIGHT: _d_bool,
    F_CHANGE_WALLET_TYPE_TONIGHT: _d_bool,
    F_IS_CUSTOMIZED: _d_bool,
    F_HOME_LOCATION: _d_opt_string,
    F_FARM_NAME: _d_opt_string,
    F_FAVORITE_THING: _d_opt_string,
    F_HORSE_NAME: _d_opt_string,
    F_MILLISECONDS_PLAYED: _d_i64,
}

# ---------------------------------------------------------------- NetWorldState

# NetWorldState.initNetFields() order (1.6.8 decompile; the first 17 are all simple types).
W_UNIQUE_ID_FOR_THIS_GAME = 0
W_SERVER_PRIVACY = 1
W_WHICH_FARM = 2
W_WHICH_MOD_FARM = 3
W_SHUFFLE_MINE_CHESTS = 4
W_MINES_DIFFICULTY = 5
W_SKULL_CAVES_DIFFICULTY = 6
W_HIGHEST_PLAYER_LIMIT = 7
W_CURRENT_PLAYER_LIMIT = 8
W_YEAR = 9
W_SEASON = 10
W_DAY_OF_MONTH = 11
W_TIME_OF_DAY = 12
W_DAYS_PLAYED = 13
W_VISITS_UNTIL_Y1_GUARANTEE = 14
W_IS_PAUSED = 15
W_IS_TIME_PAUSED = 16

WORLD_DECODERS: Dict[int, Decoder] = {
    W_UNIQUE_ID_FOR_THIS_GAME: _d_i64,
    W_SERVER_PRIVACY: _d_i16,
    W_WHICH_FARM: _d_i32,
    W_WHICH_MOD_FARM: _d_opt_string,
    W_SHUFFLE_MINE_CHESTS: _d_bool,
    W_MINES_DIFFICULTY: _d_i32,
    W_SKULL_CAVES_DIFFICULTY: _d_i32,
    W_HIGHEST_PLAYER_LIMIT: _d_i32,
    W_CURRENT_PLAYER_LIMIT: _d_i32,
    W_YEAR: _d_i32,
    W_SEASON: _d_i16,
    W_DAY_OF_MONTH: _d_i32,
    W_TIME_OF_DAY: _d_i32,
    W_DAYS_PLAYED: _d_i32,
    W_VISITS_UNTIL_Y1_GUARANTEE: _d_i32,
    W_IS_PAUSED: _d_bool,
    W_IS_TIME_PAUSED: _d_bool,
}

WORLD_FIELD_NAMES: Dict[int, str] = {
    0: "uniqueIDForThisGame", 1: "serverPrivacy", 2: "whichFarm", 3: "whichModFarm",
    4: "shuffleMineChests", 5: "minesDifficulty", 6: "skullCavesDifficulty",
    7: "highestPlayerLimit", 8: "currentPlayerLimit", 9: "year", 10: "season",
    11: "dayOfMonth", 12: "timeOfDay", 13: "daysPlayed", 14: "visitsUntilY1Guarantee",
    15: "isPaused", 16: "isTimePaused",
}

# ---------------------------------------------------------------- root deltas


@dataclass
class RootDelta:
    """A decoded ``NetRoot<T>.Write`` payload (version vector + net-field delta)."""

    version: NetVersion
    reassigned: bool  # True when the root value itself was replaced (not decoded further)
    field_count: int
    dirty: List[int]
    values: Dict[int, Any]
    complete: bool  # False if decoding stopped at a field with unknown encoding


def parse_root_delta(r: Reader, decoders: Dict[int, Decoder]) -> RootDelta:
    version = NetVersion.read(r)
    delta_type = r.u8()
    body = r.skippable()
    if delta_type == 1:
        return RootDelta(version, True, 0, [], {}, False)
    br = Reader(body)
    bits = br.bitarray()
    dirty = [i for i, b in enumerate(bits) if b]
    values: Dict[int, Any] = {}
    complete = True
    for index in dirty:
        decoder = decoders.get(index)
        if decoder is None:
            complete = False
            break
        try:
            values[index] = decoder(br)
        except (EOFError, ValueError, UnicodeDecodeError):
            complete = False
            break
    return RootDelta(version, False, len(bits), dirty, values, complete)


@dataclass
class FarmerDelta:
    farmer_id: int
    root: RootDelta

    @property
    def field_count(self) -> int:
        return self.root.field_count

    def get(self, index: int, default: Any = None) -> Any:
        return self.root.values.get(index, default)

    @property
    def position(self) -> Optional[Tuple[float, float]]:
        pos = self.root.values.get(F_POSITION)
        return pos.get("position") if pos else None

    @property
    def moving(self) -> Optional[bool]:
        pos = self.root.values.get(F_POSITION)
        return pos.get("moving") if pos else None

    @property
    def location(self) -> Optional[str]:
        loc = self.root.values.get(F_CURRENT_LOCATION)
        return loc.get("name") if loc else None


def parse_farmer_delta(data: bytes) -> FarmerDelta:
    """Decode a ``farmerDelta`` (message type 0) payload: int64 farmer id + root delta."""
    r = Reader(data)
    farmer_id = r.i64()
    return FarmerDelta(farmer_id, parse_root_delta(r, FARMER_DECODERS))


def parse_world_delta(data: bytes) -> RootDelta:
    """Decode a ``worldDelta`` (message type 12) payload."""
    return parse_root_delta(Reader(data), WORLD_DECODERS)


# ---------------------------------------------------------------- FarmerTeam net fields (message 13)

#: ``FarmerTeam.initNetFields()`` field count and the index of the shared-wallet
#: ``money`` field (a ``NetIntDelta``), on the 1.6.15 server.  Both are
#: UNVERIFIED: no ``teamDelta`` appears in the captures, and the ``FarmerTeam``
#: full packet inside ``serverIntroduction`` cannot be reached (it trails the
#: still-undecoded full-farmer binary).  Pin them from one live ``teamDelta``
#: with ``client.py --trace`` (change money at a shop in-game);
#: while ``None`` the client refuses to build a teamDelta so it never sprays a
#: guessed field write at the host.
FARMER_TEAM_FIELD_COUNT: Optional[int] = 77  # confirmed from a live 1.6.15 teamDelta
F_TEAM_MONEY: Optional[int] = 0  # confirmed: a -100 shop spend serialised as int32 at index 0


@dataclass
class TeamDeltaProbe:
    """A ``teamDelta`` decoded only far enough to learn its shape.

    The ``FarmerTeam`` schema is not implemented, so field payloads are left
    raw: ``dirty`` is the list of changed field indices, ``field_count`` the
    length of the dirty-field bitarray, and ``tail`` the undecoded bytes that
    follow it (the changed fields' payloads, in index order).
    """

    version: NetVersion
    reassigned: bool
    field_count: int
    dirty: List[int]
    tail: bytes


def parse_team_delta(data: bytes) -> TeamDeltaProbe:
    """Decode a ``teamDelta`` (message type 13) payload's version + dirty bits."""
    r = Reader(data)
    version = NetVersion.read(r)
    delta_type = r.u8()
    body = r.skippable()
    if delta_type == 1:
        return TeamDeltaProbe(version, True, 0, [], b"")
    br = Reader(body)
    bits = br.bitarray()
    dirty = [i for i, b in enumerate(bits) if b]
    return TeamDeltaProbe(version, False, len(bits), dirty, br.read(br.remaining()))


def build_team_delta(version: NetVersion, field_count: int, money_index: int,
                     money_delta: int) -> bytes:
    """Build a ``teamDelta`` (message type 13) that adds ``money_delta`` gold to
    the shared ``FarmerTeam`` wallet.

    ``money`` is a ``NetIntDelta``, so the wire value is the signed amount to
    *add* (the receiver does ``value += delta``), encoded as a single int32.
    ``field_count`` must equal the host's ``FarmerTeam`` net-field count or the
    server rejects the whole delta, exactly as for the farmer delta.
    """
    field = Writer()
    field.i32(money_delta)

    inner = Writer()
    inner.bitarray([i == money_index for i in range(field_count)])
    inner.raw(field.getvalue())

    w = Writer()
    version.write(w)
    w.u8(0)  # RefDeltaType.ChildDelta
    w.skippable(inner.getvalue())
    return w.getvalue()


def build_farmer_delta(
    farmer_id: int,
    version: NetVersion,
    field_count: int,
    *,
    position: Optional[Tuple[float, float]] = None,
    moving: Optional[bool] = None,
    facing: Optional[int] = None,
    speed: Optional[int] = None,
    name: Optional[str] = None,
    location: Optional[Tuple[str, bool]] = None,
    item_field: Optional[bytes] = None,
) -> bytes:
    """Build a ``farmerDelta`` (message type 0) payload for our own farmer.

    Only fields the server accepts from a client and whose encoding is stable
    across 1.6.x are supported.  ``field_count`` must match the server's
    ``Farmer`` net-field count or the server rejects the whole delta.
    ``item_field`` is a pre-built netItems (field 39) ``NetRef`` child payload
    from :mod:`sdvclient.inventory`.
    """
    fields: Dict[int, bytes] = {}
    if item_field is not None:
        fw = Writer()
        fw.u8(0)  # netItems NetRef child delta
        fw.skippable(item_field)
        fields[F_ITEMS] = fw.getvalue()
    if position is not None or moving is not None:
        fw = Writer()
        fw.bitarray([position is not None, False, moving is not None])
        if position is not None:
            fw.f32(float(position[0]))
            fw.f32(float(position[1]))
        if moving is not None:
            fw.bool_(moving)
        fields[F_POSITION] = fw.getvalue()
    if facing is not None:
        fields[F_FACING_DIRECTION] = struct.pack("<i", facing)
    if speed is not None:
        fields[F_SPEED] = struct.pack("<i", speed)
    if name is not None:
        fw = Writer()
        fw.bool_(True)
        fw.string(name)
        fields[F_NAME] = fw.getvalue()
    if location is not None:
        loc_name, is_structure = location
        fw = Writer()
        fw.bitarray([True, True])
        fw.bool_(True)
        fw.string(loc_name)
        fw.bool_(is_structure)
        fields[F_CURRENT_LOCATION] = fw.getvalue()

    inner = Writer()
    inner.bitarray([i in fields for i in range(field_count)])
    for index in sorted(fields):
        inner.raw(fields[index])

    w = Writer()
    w.i64(farmer_id)
    version.write(w)
    w.u8(0)  # RefDeltaType.ChildDelta
    w.skippable(inner.getvalue())
    return w.getvalue()
