"""High level Stardew Valley client: connect, join as a farmhand, chat, walk."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple, Union

from . import netcode
from .location import (
    Location,
    apply_location_delta,
    build_location_removal_delta,
    parse_location_snapshot,
    read_location_delta_version,
    read_location_intro_version,
)
from .inventory import (
    DROPS,
    INVENTORY_SIZE,
    InvItem,
    build_set_slot_body,
    parse_inventory_xml,
)
from .lidgren import LidgrenConnection, Status
from .netcode import (
    FARMER_FIELD_COUNT,
    NetVersion,
    build_farmer_delta,
    build_team_delta,
    parse_farmer_delta,
    parse_team_delta,
    parse_world_delta,
)
from .protocol import (
    ALL_PLAYERS,
    DEFAULT_PORT,
    SEASONS,
    Farmhand,
    FarmerInfo,
    GameMessage,
    LocationIntroduction,
    MessageType,
    build_chat_message,
    build_player_introduction,
    build_warp_farmer,
    decode_game_messages,
    message_type_name,
    encode_game_message,
    parse_available_farmhands,
    parse_chat_info_message,
    parse_chat_message,
    parse_location_introduction,
    parse_string,
    parse_user_name_update,
    pixel_to_tile,
    read_farmer_packet,
    tile_to_pixel,
)

log = logging.getLogger(__name__)

# Facing directions used by the game.
UP, RIGHT, DOWN, LEFT = 0, 1, 2, 3


class StardewError(Exception):
    pass


class JoinRejected(StardewError):
    """The server answered our farmhand request with a fresh farmhand list."""


class NotJoined(StardewError):
    pass


@dataclass
class Player:
    unique_id: int
    name: str
    user_name: str = ""
    farm_name: str = ""
    position: Optional[Tuple[float, float]] = None
    facing: Optional[int] = None
    speed: Optional[int] = None
    location: Optional[str] = None
    is_host: bool = False
    is_me: bool = False
    info: Optional[FarmerInfo] = None

    @property
    def tile(self) -> Optional[Tuple[int, int]]:
        return pixel_to_tile(*self.position) if self.position is not None else None

    def __str__(self) -> str:
        where = f" @ {self.location}" if self.location else ""
        tile = f" {self.tile}" if self.position is not None else ""
        return f"{self.name} ({self.unique_id}){where}{tile}"


@dataclass
class WorldState:
    year: Optional[int] = None
    season: Optional[int] = None
    day_of_month: Optional[int] = None
    time_of_day: Optional[int] = None  # e.g. 1900 for 7:00 pm, 2430 for 12:30 am
    days_played: Optional[int] = None
    is_paused: Optional[bool] = None
    is_time_paused: Optional[bool] = None

    @property
    def season_name(self) -> Optional[str]:
        return SEASONS[self.season] if self.season is not None and 0 <= self.season < 4 else None

    @property
    def clock(self) -> Optional[str]:
        if self.time_of_day is None:
            return None
        hours, minutes = divmod(self.time_of_day, 100)
        suffix = "am" if hours % 24 < 12 else "pm"
        return f"{(hours % 12) or 12}:{minutes:02d} {suffix}"

    def __str__(self) -> str:
        return f"year {self.year} {self.season_name} {self.day_of_month}, {self.clock or '??:??'}"


@dataclass
class ChatMessage:
    sender_id: int
    recipient_id: int
    language: int
    text: str

    @property
    def is_private(self) -> bool:
        return self.recipient_id != ALL_PLAYERS


FarmhandSelector = Union[None, int, str, Farmhand]


class StardewClient:
    """Async client for a Stardew Valley multiplayer game reachable over IP.

    Callbacks (all optional, plain callables invoked on the event loop):

    * ``on_chat(message: ChatMessage, sender: Optional[Player])``
    * ``on_chat_info(key: str, args: List[str])`` - system chat lines (``Strings\\UI:Chat_<key>``)
    * ``on_player_joined(player)``, ``on_player_left(player)``, ``on_player_updated(player)``
    * ``on_world_updated(world: WorldState)``
    * ``on_location(intro: LocationIntroduction)`` - a location the server sent us
    * ``on_location_changed(location: Location)`` - the decoded map of things around us
      (objects and terrain features by tile) after a snapshot or delta; see ``self.location``
    * ``on_connection_message(text_key: str)`` - e.g. ``Strings\\UI:Client_WaitForHostLoad``
    * ``on_message(message: GameMessage)`` - every raw game message, before it is interpreted
    * ``on_disconnected(reason: str)``
    """

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        *,
        farmer_field_count: int = FARMER_FIELD_COUNT,
    ) -> None:
        self.host = host
        self.port = port
        self._conn = LidgrenConnection(host, port)
        self._conn.on_data = self._on_data
        self._conn.on_disconnected = self._on_disconnected

        self.server_version: Optional[str] = None
        self.server_name: Optional[str] = None
        self.connection_message: Optional[str] = None
        self.farmhands: List[Farmhand] = []
        self.farmer_field_count = farmer_field_count

        self.me: Optional[Player] = None
        self.host_player: Optional[Player] = None
        self.players: Dict[int, Player] = {}
        self.world = WorldState()
        self.location: Optional[Location] = None
        self.inventory: List = []
        self._item_slots: Dict[str, Tuple[int, int]] = {}
        self._locations: Dict[str, Location] = {}
        self._location_versions: Dict[str, NetVersion] = {}
        self._location_version: Optional[NetVersion] = None
        self._location_is_structure = False
        self.joined = False
        self.disconnect_reason: Optional[str] = None

        self.on_chat: Optional[Callable[[ChatMessage, Optional[Player]], None]] = None
        self.on_chat_info: Optional[Callable[[str, List[str]], None]] = None
        self.on_player_joined: Optional[Callable[[Player], None]] = None
        self.on_player_left: Optional[Callable[[Player], None]] = None
        self.on_player_updated: Optional[Callable[[Player], None]] = None
        self.on_world_updated: Optional[Callable[[WorldState], None]] = None
        self.on_location: Optional[Callable[[LocationIntroduction], None]] = None
        self.on_location_changed: Optional[Callable[[Location], None]] = None
        self.on_connection_message: Optional[Callable[[str], None]] = None
        self.on_message: Optional[Callable[[GameMessage], None]] = None
        self.on_disconnected: Optional[Callable[[str], None]] = None

        self._farmhands_event: Optional[asyncio.Event] = None
        self._closed_event: Optional[asyncio.Event] = None
        self._join_future: Optional[asyncio.Future] = None
        self._location_future: Optional[asyncio.Future] = None
        self._version = NetVersion([0, 0])

        # Shared-wallet (FarmerTeam) state, learned from the first incoming
        # teamDelta (message 13): the root version vector and net-field count.
        # The money field index stays at the module default until pinned.
        self._team_version: Optional[NetVersion] = None
        self.team_field_count: Optional[int] = netcode.FARMER_TEAM_FIELD_COUNT
        self.team_money_index: Optional[int] = netcode.F_TEAM_MONEY
        self.on_team_delta: Optional[Callable[[netcode.TeamDeltaProbe], None]] = None

        #: When set, every game message sent and received is printed to stdout
        #: (decoded envelope + hex preview), like tools/pcap_dump.py but live.
        self.trace = False

    # ------------------------------------------------------------------ connection

    @property
    def connected(self) -> bool:
        return self._conn.status == Status.CONNECTED

    @property
    def ping(self) -> Optional[float]:
        """Round-trip time to the server in seconds, once measured."""
        return self._conn.average_rtt

    async def connect(self, timeout: float = 15.0, wait_for_farmhands: bool = True) -> None:
        """Discover the server, complete the Lidgren handshake and (by default) wait for the farmhand list."""
        self._farmhands_event = asyncio.Event()
        self._closed_event = asyncio.Event()
        await self._conn.open()
        strings = await self._conn.discover(timeout=min(5.0, timeout))
        self.server_version = strings[0] if strings else None
        self.server_name = strings[1] if len(strings) > 1 else None
        log.info("server %s protocol %s", self.server_name, self.server_version)
        await self._conn.connect(timeout=timeout)
        if wait_for_farmhands:
            await self.wait_for_farmhands(timeout)

    async def wait_for_farmhands(self, timeout: float = 30.0) -> List[Farmhand]:
        """Wait until the server sends the list of farmhands we may join as."""
        assert self._farmhands_event is not None, "call connect() first"
        try:
            await asyncio.wait_for(self._farmhands_event.wait(), timeout)
        except asyncio.TimeoutError:
            hint = f" (server says: {self.connection_message})" if self.connection_message else ""
            raise StardewError(f"no farmhand list received within {timeout}s{hint}") from None
        return self.farmhands

    async def disconnect(self) -> None:
        """Leave the game politely (message 19) and close the connection."""
        if self.joined and self.me is not None and self.connected:
            self._send(MessageType.DISCONNECTING)
        self.joined = False
        await self._conn.disconnect("")
        if self._closed_event is not None:
            self._closed_event.set()

    async def wait_closed(self) -> None:
        assert self._closed_event is not None, "call connect() first"
        await self._closed_event.wait()

    # ------------------------------------------------------------------ joining

    def find_farmhand(self, selector: FarmhandSelector = None) -> Farmhand:
        if isinstance(selector, Farmhand):
            return selector
        if not self.farmhands:
            raise StardewError("no farmhands available (is the host in a menu or is the farm full?)")
        if selector is None:
            return self.farmhands[0]
        if isinstance(selector, int):
            return self.farmhands[selector]
        for fh in self.farmhands:
            if fh.name.lower() == selector.lower() or str(fh.unique_id) == selector:
                return fh
        names = ", ".join(repr(f.name) for f in self.farmhands)
        raise StardewError(f"no farmhand named {selector!r}; available: {names}")

    async def join(self, farmhand: FarmhandSelector = None, timeout: float = 60.0, force: bool = False) -> Player:
        """Join the game as ``farmhand`` (default: the first available one).

        Returns our :class:`Player` once the server has accepted us and sent
        the server introduction.  Raises :class:`JoinRejected` if the server
        answers with a new farmhand list instead.
        """
        if not self.farmhands:
            await self.wait_for_farmhands(timeout)
        fh = self.find_farmhand(farmhand)
        if fh.ambiguous and not force:
            raise StardewError(
                f"farmhand {fh.name!r}: could not determine its data boundary uniquely; "
                "pass force=True to send it anyway"
            )
        loop = asyncio.get_running_loop()
        self._join_future = loop.create_future()
        self._version = NetVersion([0, 0])
        info = fh.info
        self.me = Player(
            unique_id=info.unique_id,
            name=info.name,
            farm_name=info.farm_name,
            position=info.position,
            facing=info.facing_direction,
            location=info.disconnect_location or info.last_sleep_location or info.home_location,
            is_me=True,
            info=info,
        )
        log.info("requesting farmhand %s (%d)", info.name, info.unique_id)
        self._send(MessageType.PLAYER_INTRODUCTION, build_player_introduction(fh.blob), farmer_id=info.unique_id)
        try:
            await asyncio.wait_for(self._join_future, timeout)
        finally:
            self._join_future = None
        self.joined = True
        self.players[self.me.unique_id] = self.me
        # read our starting inventory so add_item can pick empty slots and stack
        self.inventory = parse_inventory_xml(info.xml)
        self._item_slots = {}  # item_id -> (slot, running stack) for items we added
        return self.me

    # ------------------------------------------------------------------ actions

    def chat(self, text: str, to: int = ALL_PLAYERS) -> None:
        """Send a chat message to everyone (default) or privately to one farmer id."""
        self._require_joined()
        self._send(MessageType.CHAT_MESSAGE, build_chat_message(text, to))

    def give_money(self, amount: int) -> None:
        """Add ``amount`` gold to the shared ``FarmerTeam`` wallet (may be negative).

        This host uses a shared wallet, so there is one communal pot and no
        per-player balance to target.  ``money`` is a ``NetIntDelta`` synced via
        ``teamDelta`` (message 13); we send the signed delta.

        Requires the ``FarmerTeam`` field count and money field index to be known
        (pinned for 1.6.15 in :mod:`sdvclient.netcode`).  To re-pin on another
        version, run the client with ``--trace`` and change money at a shop; the
        money field is the dirty teamDelta index whose payload is a 4-byte int32
        equal to the gold delta.  Until then this raises rather than guess.
        """
        self._require_joined()
        if self.team_field_count is None or self.team_money_index is None:
            raise StardewError(
                "FarmerTeam money field is not pinned yet; run with --trace and "
                "change money at a shop in-game to learn the field count and money "
                "index, then set netcode.FARMER_TEAM_FIELD_COUNT and netcode.F_TEAM_MONEY"
            )
        version = self._next_team_version()
        data = build_team_delta(version, self.team_field_count, self.team_money_index, int(amount))
        self._send(MessageType.TEAM_DELTA, data)

    def _next_team_version(self) -> NetVersion:
        """The team root version to stamp on our next teamDelta, priority-bumped."""
        base = list(self._team_version.vector) if self._team_version else [0, 0]
        version = NetVersion(base)
        version.bump(0)
        self._team_version = version
        return version

    def set_position(self, x: float, y: float, *, facing: Optional[int] = None, moving: bool = False,
                     speed: Optional[int] = None) -> None:
        """Teleport our farmer to a pixel position within the current location."""
        self._require_joined()
        assert self.me is not None
        self.me.position = (float(x), float(y))
        if facing is not None:
            self.me.facing = facing
        if speed is not None:
            self.me.speed = speed
        self._send_farmer_delta(position=self.me.position, moving=moving, facing=facing, speed=speed)

    def set_tile(self, tile_x: int, tile_y: int, *, facing: Optional[int] = None) -> None:
        """Teleport our farmer onto a tile within the current location."""
        self.set_position(*tile_to_pixel(tile_x, tile_y), facing=facing)

    def face(self, direction: int) -> None:
        """Turn to face UP(0), RIGHT(1), DOWN(2) or LEFT(3)."""
        self._require_joined()
        assert self.me is not None
        self.me.facing = direction
        self._send_farmer_delta(facing=direction)

    async def walk_to(self, tile_x: int, tile_y: int, *, speed: float = 5.0, updates_per_second: int = 20) -> None:
        """Walk to a tile in the current location, axis-aligned (x first, then y).

        ``speed`` is in pixels per game tick (60 ticks/s); the game's default
        walking speed is 5.  Movement is not collision checked.
        """
        self._require_joined()
        assert self.me is not None
        if self.me.position is None:
            raise StardewError("current position unknown; call set_tile() first")
        target = tile_to_pixel(tile_x, tile_y)
        x, y = self.me.position
        step = speed * 60.0 / updates_per_second
        interval = 1.0 / updates_per_second
        while (x, y) != target:
            dx, dy = target[0] - x, target[1] - y
            if dx != 0:
                move = max(-step, min(step, dx))
                x += move
                facing = RIGHT if move > 0 else LEFT
            else:
                move = max(-step, min(step, dy))
                y += move
                facing = DOWN if move > 0 else UP
            self.me.position = (x, y)
            self.me.facing = facing
            self.me.speed = int(speed)
            self._send_farmer_delta(position=(x, y), moving=True, facing=facing, speed=int(speed))
            await asyncio.sleep(interval)
        self._send_farmer_delta(position=target, moving=False)

    async def walk(self, dx_tiles: int, dy_tiles: int, **kwargs) -> None:
        """Walk relative to the current tile."""
        self._require_joined()
        assert self.me is not None and self.me.tile is not None
        tx, ty = self.me.tile
        await self.walk_to(tx + dx_tiles, ty + dy_tiles, **kwargs)

    async def warp(self, location: str, tile_x: int, tile_y: int, *, is_structure: bool = False,
                   timeout: float = 15.0) -> Optional[LocationIntroduction]:
        """Ask the server to move us to another location (e.g. ``"Town"``, ``"Farm"``, ``"Beach"``).

        Returns the location introduction the server sends back, or ``None``
        if none arrived within ``timeout``.
        """
        self._require_joined()
        assert self.me is not None
        loop = asyncio.get_running_loop()
        self._location_future = loop.create_future()
        self._send(MessageType.WARP_FARMER, build_warp_farmer(tile_x, tile_y, location, is_structure))
        self.me.location = location
        self.me.position = tile_to_pixel(tile_x, tile_y)
        # tell everybody else where we are now; the server only rebroadcasts what we send
        self._send_farmer_delta(position=self.me.position, moving=False, location=(location, is_structure))
        try:
            return await asyncio.wait_for(self._location_future, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._location_future = None
            # the server may not re-send an introduction for a location we were
            # told about at join; switch to the cached decode so self.location
            # tracks where we are and map edits target the right map.
            cached = self._locations.get(location)
            if cached is not None:
                self.location = cached
                self._location_version = self._location_versions.get(location)
                self._location_is_structure = is_structure

    def send_raw(self, msg_type: int, data: bytes = b"", farmer_id: Optional[int] = None) -> None:
        """Send an arbitrary game message (escape hatch for messages this client does not model)."""
        self._send(msg_type, data, farmer_id=farmer_id)

    # --------------------------------------------------------------- map editing

    def _next_location_version(self) -> NetVersion:
        """Location root version to stamp on our next removal: latest seen, our slot bumped."""
        base = self._location_version.vector if self._location_version else [0, 0]
        vec = list(base) or [0, 0]
        if len(vec) < 2:
            vec = vec + [0] * (2 - len(vec))
        vec[-1] += 1  # bump the sender's (last) slot
        return NetVersion(vec)

    def remove_terrain(self, tile: Tuple[int, int]) -> None:
        """Clear the terrain feature (tree, grass, tilled dirt, ...) at ``tile`` in our location."""
        self._remove_tile(tile, objects=False)

    def remove_object(self, tile: Tuple[int, int]) -> None:
        """Clear the object (stone, twig, litter, ...) at ``tile`` in our location."""
        self._remove_tile(tile, objects=True)

    def _remove_tile(self, tile: Tuple[int, int], *, objects: bool) -> None:
        self._require_joined()
        if self.location is None:
            raise StardewError("no location decoded yet; walk into the map first")
        data = build_location_removal_delta(
            self.location.name, self._location_is_structure,
            self._next_location_version(), (int(tile[0]), int(tile[1])), objects=objects,
        )
        self._send(MessageType.LOCATION_DELTA, data)
        # reflect it locally too
        (self.location.objects if objects else self.location.terrain).pop((int(tile[0]), int(tile[1])), None)

    def add_item(self, item_id: str, name: str, count: int = 1, quality: int = 0) -> None:
        """Add ``count`` of an item to our inventory (net field 39).

        Puts the item in the slot it already occupies (bumping the stack) or the
        first empty backpack slot, and syncs a farmer delta the host accepts.
        """
        self._require_joined()
        assert self.me is not None
        item_id = str(item_id)
        if item_id in self._item_slots:
            slot, stack = self._item_slots[item_id]
            stack += count
        else:
            slot = self._first_empty_slot()
            if slot is None:
                raise StardewError("inventory full")
            stack = count
        self._item_slots[item_id] = (slot, stack)
        item = InvItem(item_id, name, stack, quality)
        if slot < len(self.inventory):
            self.inventory[slot] = item
        self._version.bump(0)
        body = build_set_slot_body(slot, item, version=NetVersion(list(self._version.vector)))
        data = build_farmer_delta(self.me.unique_id, self._version, self.farmer_field_count,
                                  item_field=body)
        self._send(MessageType.FARMER_DELTA, data)

    def _first_empty_slot(self) -> Optional[int]:
        used = {s for s, _ in self._item_slots.values()}
        for i in range(INVENTORY_SIZE):
            occupied = i < len(self.inventory) and self.inventory[i] is not None
            if not occupied and i not in used:
                return i
        return None

    def _drop_for(self, thing: object) -> Optional[Tuple[str, str]]:
        """The (item_id, name) a cleared object/terrain yields, or None."""
        key = getattr(thing, "name", None) or getattr(thing, "kind", None)
        return DROPS.get(key) if key else None

    async def clear_area(self, center: Tuple[int, int], radius: int = 3, *,
                         delay: float = 0.15, collect: bool = True) -> int:
        """Remove every object and terrain feature within ``radius`` tiles of ``center``.

        Sends one removal per thing, pacing them by ``delay`` seconds so the host
        is not flooded.  With ``collect`` (default), each cleared thing's drop is
        added to our inventory.  Returns the count removed.
        """
        self._require_joined()
        if self.location is None:
            raise StardewError("no location decoded yet")
        things = self.location.things_near(center, radius)
        drops: Dict[Tuple[str, str], int] = {}
        sent = 0
        for thing in things:
            tile = thing.tile
            in_objects = tile in self.location.objects
            self._remove_tile(tile, objects=in_objects)
            if collect and (drop := self._drop_for(thing)) is not None:
                drops[drop] = drops.get(drop, 0) + 1
            sent += 1
            if delay:
                await asyncio.sleep(delay)
        for (item_id, name), count in drops.items():
            try:
                self.add_item(item_id, name, count)
            except StardewError:
                break  # inventory full
            if delay:
                await asyncio.sleep(delay)
        return sent

    # ------------------------------------------------------------------ internals: sending

    def _require_joined(self) -> None:
        if not self.joined or self.me is None:
            raise NotJoined("join() first")

    def _send(self, msg_type: int, data: bytes = b"", farmer_id: Optional[int] = None) -> None:
        if farmer_id is None:
            farmer_id = self.me.unique_id if self.me is not None else 0
        if self.trace:
            self._trace("C->S", int(msg_type), farmer_id, data, compressed=False)
        self._conn.send_reliable(encode_game_message(int(msg_type), farmer_id, data))

    @staticmethod
    def _trace(direction: str, msg_type: int, farmer_id: int, data: bytes,
               *, compressed: bool) -> None:
        """Print one decoded game-message line to stdout (both directions)."""
        preview = data[:32].hex()
        if len(data) > 32:
            preview += "..."
        tag = " lz4" if compressed else ""
        print(f"{direction} {msg_type:>3} {message_type_name(msg_type):<24} "
              f"farmer={farmer_id} len={len(data)}{tag} {preview}")

    def _send_farmer_delta(self, **fields) -> None:
        assert self.me is not None
        self._version.bump(0)
        data = build_farmer_delta(self.me.unique_id, self._version, self.farmer_field_count, **fields)
        self._send(MessageType.FARMER_DELTA, data)

    # ------------------------------------------------------------------ internals: receiving

    def _on_disconnected(self, reason: str) -> None:
        self.disconnect_reason = reason
        self.joined = False
        for fut in (self._join_future, self._location_future):
            if fut is not None and not fut.done():
                fut.set_exception(StardewError(f"disconnected: {reason}"))
        if self._closed_event is not None:
            self._closed_event.set()
        self._emit(self.on_disconnected, reason)

    def _on_data(self, payload: bytes) -> None:
        try:
            messages = decode_game_messages(payload)
        except Exception:
            log.exception("could not decode game message payload (%d bytes)", len(payload))
            return
        for msg in messages:
            if self.trace:
                self._trace("S->C", msg.type, msg.farmer_id, msg.data, compressed=msg.compressed)
            self._emit(self.on_message, msg)
            try:
                self._dispatch(msg)
            except Exception:
                log.exception("error handling %s from %d", msg.type_name, msg.farmer_id)

    def _dispatch(self, msg: GameMessage) -> None:
        t = msg.type
        if t == MessageType.AVAILABLE_FARMHANDS:
            available = parse_available_farmhands(msg.data)
            self.farmhands = available.farmhands
            self.world.year, self.world.season, self.world.day_of_month = (
                available.year, available.season, available.day_of_month,
            )
            log.info("%d farmhand(s) available: %s", len(self.farmhands),
                     ", ".join(f.name or "<unnamed>" for f in self.farmhands))
            if self._join_future is not None and not self._join_future.done():
                self._join_future.set_exception(JoinRejected(
                    "server rejected the farmhand request (already in use, not customized, or unavailable)"))
            if self._farmhands_event is not None:
                self._farmhands_event.set()
            self._emit(self.on_world_updated, self.world)

        elif t == MessageType.CONNECTION_MESSAGE:
            self.connection_message = parse_string(msg.data)
            log.info("server: %s", self.connection_message)
            self._emit(self.on_connection_message, self.connection_message)

        elif t == MessageType.SERVER_INTRODUCTION:
            packet = read_farmer_packet(msg.reader)
            host = self._player_from_info(packet.info, is_host=True)
            self.host_player = host
            log.info("joined game hosted by %s (farm %r, game %s)", host.name, host.farm_name,
                     packet.info.game_version)
            if self._join_future is not None and not self._join_future.done():
                self._join_future.set_result(True)

        elif t == MessageType.PLAYER_INTRODUCTION:
            r = msg.reader
            user_name = r.string()
            packet = read_farmer_packet(r)
            player = self._player_from_info(packet.info)
            player.user_name = user_name
            log.info("player joined: %s", player)
            self._emit(self.on_player_joined, player)

        elif t == MessageType.FARMER_DELTA:
            delta = parse_farmer_delta(msg.data)
            if not delta.root.reassigned and delta.field_count and delta.field_count != self.farmer_field_count:
                log.info("server farmer has %d net fields (was assuming %d)", delta.field_count,
                         self.farmer_field_count)
                self.farmer_field_count = delta.field_count
            player = self.players.get(delta.farmer_id)
            if player is None or player.is_me:
                return
            changed = False
            if delta.position is not None:
                player.position = delta.position
                changed = True
            facing = delta.get(netcode.F_FACING_DIRECTION)
            if facing is not None:
                player.facing = facing
                changed = True
            speed = delta.get(netcode.F_SPEED)
            if speed is not None:
                player.speed = speed
                changed = True
            name = delta.get(netcode.F_NAME)
            if name:
                player.name = name
                changed = True
            if delta.location:
                player.location = delta.location
                changed = True
            if changed:
                self._emit(self.on_player_updated, player)

        elif t == MessageType.LOCATION_INTRODUCTION:
            intro = parse_location_introduction(msg.data)
            log.debug("location introduction: %s (force_current=%s)", intro.display_name, intro.force_current)
            # the server front-loads an introduction for every location at join; cache them all
            decoded = parse_location_snapshot(msg.data)
            key = decoded.name or intro.display_name
            self._locations[key] = decoded
            ver = read_location_intro_version(msg.data)
            if ver is not None:
                self._location_versions[key] = ver
            # the server marks the active location force_current only sometimes; at
            # join it front-loads every farm map as force=False, so also treat an
            # introduction whose name matches where we already are as "entering".
            here = self.me is not None and self.me.location in (key, intro.display_name)
            entering = intro.force_current or self._location_future is not None or here
            if self.me is not None and entering:
                self.me.location = intro.display_name
            if entering:
                self.location = decoded
                self._location_version = self._location_versions.get(key)
                log.debug("decoded location: %s", self.location)
                self._emit(self.on_location_changed, self.location)
            if self._location_future is not None and not self._location_future.done():
                self._location_future.set_result(intro)
            self._emit(self.on_location, intro)

        elif t == MessageType.LOCATION_DELTA:
            head = read_location_delta_version(msg.data)
            if head is not None:
                self._location_versions[head[1]] = head[2]
                if self.location is not None and head[1] == self.location.name:
                    self._location_is_structure = head[0]
                    self._location_version = head[2]
            if self.location is not None and apply_location_delta(self.location, msg.data):
                self._emit(self.on_location_changed, self.location)

        elif t == MessageType.CHAT_MESSAGE:
            recipient, language, text = parse_chat_message(msg.data)
            chat = ChatMessage(msg.farmer_id, recipient, language, text)
            self._emit(self.on_chat, chat, self.players.get(msg.farmer_id))

        elif t == MessageType.CHAT_INFO_MESSAGE:
            key, args = parse_chat_info_message(msg.data)
            self._emit(self.on_chat_info, key, args)

        elif t == MessageType.WORLD_DELTA:
            delta = parse_world_delta(msg.data)
            values = delta.values
            mapping = {
                netcode.W_YEAR: "year", netcode.W_SEASON: "season", netcode.W_DAY_OF_MONTH: "day_of_month",
                netcode.W_TIME_OF_DAY: "time_of_day", netcode.W_DAYS_PLAYED: "days_played",
                netcode.W_IS_PAUSED: "is_paused", netcode.W_IS_TIME_PAUSED: "is_time_paused",
            }
            changed = False
            for index, attr in mapping.items():
                if index in values:
                    setattr(self.world, attr, values[index])
                    changed = True
            if changed:
                self._emit(self.on_world_updated, self.world)

        elif t == MessageType.TEAM_DELTA:
            probe = parse_team_delta(msg.data)
            if not probe.reassigned:
                self._team_version = probe.version
                if probe.field_count:
                    if self.team_field_count is None:
                        log.info("FarmerTeam has %d net fields", probe.field_count)
                    self.team_field_count = probe.field_count
            if self.trace and not probe.reassigned:
                log.info("  teamDelta %s dirty=%s tail=%s", probe.version, probe.dirty,
                         probe.tail.hex())
            self._emit(self.on_team_delta, probe)

        elif t == MessageType.USER_NAME_UPDATE:
            farmer_id, user_name = parse_user_name_update(msg.data)
            player = self.players.get(farmer_id)
            if player is not None:
                player.user_name = user_name

        elif t == MessageType.DISCONNECTING:
            player = self.players.pop(msg.farmer_id, None)
            if player is not None:
                log.info("player left: %s", player)
                self._emit(self.on_player_left, player)

        elif t == MessageType.FORCE_KICK:
            log.warning("kicked by the server")
            asyncio.ensure_future(self.disconnect())

        elif t == MessageType.SERVER_TO_CLIENTS_MESSAGE:
            log.info("server message: %s", parse_string(msg.data))

    def _player_from_info(self, info: FarmerInfo, is_host: bool = False) -> Player:
        player = self.players.get(info.unique_id)
        if player is None:
            player = Player(unique_id=info.unique_id, name=info.name)
            self.players[info.unique_id] = player
        player.name = info.name or player.name
        player.farm_name = info.farm_name
        player.position = info.position
        player.facing = info.facing_direction
        player.is_host = is_host
        player.info = info
        if player.location is None:
            player.location = info.disconnect_location or info.last_sleep_location or info.home_location or None
        return player

    @staticmethod
    def _emit(callback, *args) -> None:
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:
            log.exception("callback %r failed", callback)
