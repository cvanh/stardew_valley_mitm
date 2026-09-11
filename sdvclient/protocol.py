"""Stardew Valley's message layer on top of Lidgren.

Every Lidgren data payload holds one or more game messages::

    byte    message type            (StardewValley.Multiplayer constants, below)
    int64   farmer id               (UniqueMultiplayerID of the sender)
    uint32  data length
    byte[]  data                    (BinaryWriter-serialised arguments)

Messages larger than 1 KiB are LZ4 compressed and replaced by::

    byte    0x7F
    int32   compressed size
    int32   decompressed size
    byte[]  LZ4 block

This module knows the framing plus the handful of message bodies the client
uses.  See docs/protocol.md for the full catalogue.
"""

from __future__ import annotations

import re
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional, Tuple

from .binary import Reader, Writer
from .lz4 import block_decompress
from .netcode import NetVersion

DEFAULT_PORT = 24642
APP_IDENTIFIER = "StardewValley"
ALL_PLAYERS = 0  # Multiplayer.AllPlayers
COMPRESSED_MARKER = 127
SEASONS = ("spring", "summer", "fall", "winter")
TILE_SIZE = 64


class ProtocolError(Exception):
    pass


class MessageType(IntEnum):
    FARMER_DELTA = 0
    SERVER_INTRODUCTION = 1
    PLAYER_INTRODUCTION = 2
    LOCATION_INTRODUCTION = 3
    FORCE_EVENT = 4
    WARP_FARMER = 5
    LOCATION_DELTA = 6
    LOCATION_SPRITES = 7
    CHARACTER_WARP = 8
    AVAILABLE_FARMHANDS = 9
    CHAT_MESSAGE = 10
    CONNECTION_MESSAGE = 11
    WORLD_DELTA = 12
    TEAM_DELTA = 13
    NEW_DAY_SYNC = 14
    CHAT_INFO_MESSAGE = 15
    USER_NAME_UPDATE = 16
    FARMER_GAIN_EXPERIENCE = 17
    SERVER_TO_CLIENTS_MESSAGE = 18
    DISCONNECTING = 19
    SHARED_ACHIEVEMENT = 20
    GLOBAL_MESSAGE = 21
    PARTY_WIDE_MAIL = 22
    FORCE_KICK = 23
    REMOVE_LOCATION_FROM_LOOKUP = 24
    FARMER_KILLED_MONSTER = 25
    REQUEST_GRANDPA_REEVALUATION = 26
    DIG_BURIED_NUT = 27
    REQUEST_PASSOUT = 28
    PASSOUT = 29
    START_NEW_DAY_SYNC = 30
    READY_SYNC = 31
    CHEST_HIT_SYNC = 32
    COMPRESSED = 127


def message_type_name(value: int) -> str:
    try:
        return MessageType(value).name
    except ValueError:
        return f"UNKNOWN_{value}"


# ------------------------------------------------------------------ envelope


@dataclass
class GameMessage:
    type: int
    farmer_id: int
    data: bytes
    compressed: bool = False

    @property
    def type_name(self) -> str:
        return message_type_name(self.type)

    @property
    def reader(self) -> Reader:
        return Reader(self.data)


def encode_game_message(msg_type: int, farmer_id: int, data: bytes = b"") -> bytes:
    w = Writer()
    w.u8(msg_type)
    w.i64(farmer_id)
    w.skippable(data)
    return w.getvalue()


def _decode_one(r: Reader, compressed: bool) -> GameMessage:
    msg_type = r.u8()
    farmer_id = r.i64()
    data = r.skippable()
    return GameMessage(msg_type, farmer_id, data, compressed)


def decode_game_messages(payload: bytes) -> List[GameMessage]:
    """Split one Lidgren data payload into game messages, decompressing where needed."""
    messages: List[GameMessage] = []
    r = Reader(payload)
    while r.remaining() >= 1:
        if r.peek_u8() == COMPRESSED_MARKER:
            r.u8()
            compressed_size = r.i32()
            decompressed_size = r.i32()
            block = r.read(compressed_size)
            inner = block_decompress(block, decompressed_size)
            messages.append(_decode_one(Reader(inner), True))
        else:
            messages.append(_decode_one(r, False))
    return messages


# ------------------------------------------------------------------ farmer XML


def _text(root: ET.Element, tag: str, default: Optional[str] = None) -> Optional[str]:
    el = root.find(tag)
    return el.text if el is not None and el.text is not None else default


@dataclass
class FarmerInfo:
    """The interesting bits of a ``Farmer`` XML document (SaveGame.farmerSerializer)."""

    unique_id: int
    name: str
    farm_name: str = ""
    home_location: str = ""
    is_customized: bool = False
    user_id: str = ""
    position: Tuple[float, float] = (0.0, 0.0)
    facing_direction: int = 2
    money: int = 0
    game_version: str = ""
    last_sleep_location: str = ""
    disconnect_location: str = ""
    disconnect_day: int = -1
    xml: bytes = field(default=b"", repr=False)

    @classmethod
    def from_xml(cls, xml: bytes) -> "FarmerInfo":
        root = ET.fromstring(xml)
        if root.tag != "Farmer":
            raise ProtocolError(f"expected <Farmer>, got <{root.tag}>")
        pos = root.find("Position")
        position = (0.0, 0.0)
        if pos is not None:
            position = (float(_text(pos, "X", "0") or 0), float(_text(pos, "Y", "0") or 0))
        return cls(
            unique_id=int(_text(root, "UniqueMultiplayerID", "0") or 0),
            name=_text(root, "name", "") or "",
            farm_name=_text(root, "farmName", "") or "",
            home_location=_text(root, "homeLocation", "") or "",
            is_customized=(_text(root, "isCustomized", "false") or "").lower() == "true",
            user_id=_text(root, "userID", "") or "",
            position=position,
            facing_direction=int(_text(root, "FacingDirection", "2") or 2),
            money=int(_text(root, "money", "0") or 0),
            game_version=_text(root, "gameVersion", "") or "",
            last_sleep_location=_text(root, "lastSleepLocation", "") or "",
            disconnect_location=_text(root, "disconnectLocation", "") or "",
            disconnect_day=int(_text(root, "disconnectDay", "-1") or -1),
            xml=xml,
        )

    @property
    def tile(self) -> Tuple[int, int]:
        return pixel_to_tile(*self.position)


def tile_to_pixel(tile_x: int, tile_y: int) -> Tuple[float, float]:
    """Farmer.Position for a farmer standing on a tile (matches GameServer.warpFarmer)."""
    return float(tile_x * TILE_SIZE), float(tile_y * TILE_SIZE + 16)


def pixel_to_tile(x: float, y: float) -> Tuple[int, int]:
    """Tile under the centre of the farmer's bounding box (Position + (32, 16))."""
    return int((x + 32) // TILE_SIZE), int((y + 16) // TILE_SIZE)


# ------------------------------------------------------------------ available farmhands (type 9)


@dataclass
class Farmhand:
    info: FarmerInfo
    #: exact ``NetRef<Farmer>.WriteFull`` bytes as sent by the server: reassigned version,
    #: int32 XML length, XML, then the binary net-field state.  Re-sent verbatim when joining.
    blob: bytes = field(repr=False)
    #: True when the boundary with the neighbouring farmhand could not be determined uniquely.
    ambiguous: bool = False

    @property
    def unique_id(self) -> int:
        return self.info.unique_id

    @property
    def name(self) -> str:
        return self.info.name


@dataclass
class AvailableFarmhands:
    year: int
    season: int
    day_of_month: int
    farmhands: List[Farmhand]

    @property
    def season_name(self) -> str:
        return SEASONS[self.season] if 0 <= self.season < 4 else str(self.season)


_XML_START = re.compile(rb'<\?xml version="1\.0"[^>]*\?>\s*<Farmer[\s>]')


def _version_size_at(data: bytes, xml_start: int, k: int) -> Optional[int]:
    """Offset of a k-entry NetVersion right before the int32 XML length, if the bytes fit."""
    start = xml_start - 4 - 1 - 4 * k
    if start < 0 or data[start] != k:
        return None
    return start


def _farmer_xml_end(data: bytes, xml_start: int) -> Optional[int]:
    """End offset of the length-prefixed <Farmer> document starting at ``xml_start``, or None."""
    if xml_start < 4:
        return None
    (length,) = struct.unpack_from("<i", data, xml_start - 4)
    end = xml_start + length
    if length <= 0 or end > len(data) or not data[xml_start:end].rstrip().endswith(b"</Farmer>"):
        return None
    return end


def parse_available_farmhands(data: bytes) -> AvailableFarmhands:
    """Decode message type 9.

    The farmhands are ``NetRef<Farmer>.WriteFull`` blobs written back to back
    without length prefixes, and the binary net-field state after each XML
    document cannot be parsed without the full ``Farmer`` schema.  Boundaries
    are therefore located by finding each XML document and working backwards
    over the int32 length and the (usually empty) reassigned version vector.
    """
    r = Reader(data)
    year = r.i32()
    season = r.i32()
    day = r.i32()
    count = r.u8()
    if count == 0:
        return AvailableFarmhands(year, season, day, [])

    # The binary state after each farmer can itself contain XML documents (items etc.), so only
    # accept <Farmer> documents whose int32 length prefix matches their content.
    xml_starts = [
        m.start() for m in _XML_START.finditer(data, r.pos) if _farmer_xml_end(data, m.start()) is not None
    ]
    if len(xml_starts) != count:
        raise ProtocolError(f"expected {count} farmhands, found {len(xml_starts)} Farmer XML documents")

    def xml_end(xml_start: int) -> int:
        end = _farmer_xml_end(data, xml_start)
        if end is None:
            raise ProtocolError("farmhand XML length does not match its content")
        return end

    # first blob starts right after the count byte, so its version size is known
    first_start = r.pos
    first_k = data[first_start]
    if first_start + 1 + 4 * first_k + 4 != xml_starts[0]:
        raise ProtocolError("unexpected layout before the first farmhand XML")

    starts: List[Tuple[int, bool]] = [(first_start, False)]
    prev_end = xml_end(xml_starts[0])
    for xml_start in xml_starts[1:]:
        candidates = [
            k for k in range(0, 16)
            if (off := _version_size_at(data, xml_start, k)) is not None and off >= prev_end
        ]
        if not candidates:
            raise ProtocolError("could not locate the start of a farmhand blob")
        chosen = first_k if first_k in candidates else candidates[0]
        starts.append((_version_size_at(data, xml_start, chosen) or 0, len(candidates) > 1))
        prev_end = xml_end(xml_start)

    farmhands: List[Farmhand] = []
    for i, (start, ambiguous) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(data)
        xml_start = xml_starts[i]
        info = FarmerInfo.from_xml(data[xml_start : xml_end(xml_start)])
        farmhands.append(Farmhand(info, data[start:end], ambiguous))
    return AvailableFarmhands(year, season, day, farmhands)


# ------------------------------------------------------------------ farmer connection packets (types 1, 2)


@dataclass
class FarmerPacket:
    """``NetRoot<Farmer>.CreateConnectionPacket``: peer id, version, then the farmer."""

    peer_id: int
    version: NetVersion
    reassigned: NetVersion
    info: FarmerInfo
    net_fields_offset: int  # where the undecoded binary net-field state starts


def read_farmer_packet(r: Reader) -> FarmerPacket:
    peer_id = r.u8()
    version = NetVersion.read(r)
    reassigned = NetVersion.read(r)
    length = r.i32()
    xml = r.read(length)
    return FarmerPacket(peer_id, version, reassigned, FarmerInfo.from_xml(xml), r.pos)


def build_player_introduction(farmhand_blob: bytes) -> bytes:
    """Message type 2 body: our peer id (1) + a two-peer version vector + the farmhand blob."""
    w = Writer()
    w.u8(1)
    NetVersion([0, 0]).write(w)
    w.raw(farmhand_blob)
    return w.getvalue()


# ------------------------------------------------------------------ chat (types 10, 15)


def build_chat_message(text: str, recipient: int = ALL_PLAYERS, language: int = 0) -> bytes:
    w = Writer()
    w.i64(recipient)
    w.i16(language)  # LocalizedContentManager.LanguageCode (0 = en)
    w.string(text)
    return w.getvalue()


def parse_chat_message(data: bytes) -> Tuple[int, int, str]:
    r = Reader(data)
    return r.i64(), r.i16(), r.string()


def parse_chat_info_message(data: bytes) -> Tuple[str, List[str]]:
    r = Reader(data)
    key = r.string()
    return key, [r.string() for _ in range(r.u8())]


# ------------------------------------------------------------------ misc bodies


#: Flag bit the server requires on a warpFarmer message; without it the warp is
#: silently ignored.  Real 1.6.15 clients always set it (their trailing byte is
#: 0x04 OR-ed with per-destination bits we do not need); bit 0 carries isStructure.
WARP_FLAG = 0x04


def build_warp_farmer(tile_x: int, tile_y: int, location_name: str, is_structure: bool = False) -> bytes:
    """Build a ``warpFarmer`` (message type 5) body: ``short x, short y, string name, byte flags``.

    The trailing byte is a flags field, not a plain ``isStructure`` bool: the
    server only acts on the warp when :data:`WARP_FLAG` is set (verified live),
    which is why sending 0/1 there left the farmer standing still.
    """
    w = Writer()
    w.i16(tile_x)
    w.i16(tile_y)
    w.string(location_name)
    w.u8(WARP_FLAG | (0x01 if is_structure else 0x00))
    return w.getvalue()


def parse_user_name_update(data: bytes) -> Tuple[int, str]:
    r = Reader(data)
    return r.i64(), r.string()


def parse_string(data: bytes) -> str:
    return Reader(data).string()


@dataclass
class LocationIntroduction:
    force_current: bool
    type_name: str
    map_path: Optional[str]
    unique_name: Optional[str]
    name: Optional[str]

    @property
    def display_name(self) -> str:
        return self.unique_name or self.name or self.type_name


def parse_location_introduction(data: bytes) -> LocationIntroduction:
    """Decode the head of message type 3 (the location's net-field body is not decoded)."""
    r = Reader(data)
    force_current = r.bool_()
    r.u8()  # peer id
    NetVersion.read(r)
    mark = r.pos
    try:
        NetVersion.read(r)
        type_name = r.string()
        if not type_name.startswith("StardewValley"):
            raise ValueError
    except (EOFError, ValueError, UnicodeDecodeError):
        # 1.6.15 servers put one extra 0x00 before the reassigned version here
        r.pos = mark
        r.u8()
        NetVersion.read(r)
        type_name = r.string()

    def opt_string() -> Optional[str]:
        return r.string() if r.bool_() else None

    map_path = unique_name = name = None
    try:
        map_path = opt_string()
        unique_name = opt_string()
        name = opt_string()
    except (EOFError, UnicodeDecodeError):
        pass
    return LocationIntroduction(force_current, type_name, map_path, unique_name, name)
