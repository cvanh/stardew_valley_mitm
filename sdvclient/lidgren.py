"""Minimal Lidgren.Network (gen3) client transport over UDP, as used by Stardew Valley.

Only the pieces a game client needs are implemented:

* discovery request / response
* connect handshake (``Connect`` -> ``ConnectResponse`` -> ``ConnectionEstablished``)
* ping / pong keep-alive and connection timeout
* ``ReliableOrdered`` delivery on sequence channel 0 (acks, resends, ordering window)
* fragmentation / reassembly of payloads larger than the MTU
* disconnect

Wire format of every Lidgren message (several may share one UDP datagram)::

    byte    NetMessageType
    byte    (sequence << 1) | isFragment          (low 7 bits of the sequence number)
    byte    sequence >> 7                          (high 8 bits)
    uint16  payload length in *bits*
    byte[]  payload

See docs/protocol.md for the details and captured examples.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import struct
import time
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Deque, Dict, List, Optional, Set, Tuple

from .binary import Reader, Writer

log = logging.getLogger(__name__)


class LibraryType(IntEnum):
    """NetMessageType values >= 128 are Lidgren-internal ("library") messages."""

    LIBRARY_ERROR = 128
    PING = 129
    PONG = 130
    CONNECT = 131
    CONNECT_RESPONSE = 132
    CONNECTION_ESTABLISHED = 133
    ACKNOWLEDGE = 134
    DISCONNECT = 135
    DISCOVERY = 136
    DISCOVERY_RESPONSE = 137
    NAT_PUNCH_MESSAGE = 138
    NAT_INTRODUCTION = 139
    EXPAND_MTU_REQUEST = 140
    EXPAND_MTU_SUCCESS = 141
    NAT_INTRODUCTION_CONFIRM_REQUEST = 142
    NAT_INTRODUCTION_CONFIRMED = 143


class Status(IntEnum):
    NONE = 0
    INITIATED_CONNECT = 1
    CONNECTED = 2
    DISCONNECTED = 3


# NetMessageType values for application data.
UNCONNECTED = 0
USER_UNRELIABLE = 1
USER_RELIABLE_UNORDERED = 34  # first reliable type; everything >= this is acked
USER_RELIABLE_ORDERED = 67  # ReliableOrdered, sequence channel 0 (what Stardew uses)
USER_LAST = 98

HEADER_SIZE = 5
NUM_SEQUENCE_NUMBERS = 1024
WINDOW_SIZE = 64
MAX_FRAGMENT_GROUPS = 65534
DEFAULT_MTU = 1200  # NetPeerConfiguration.MaximumTransmissionUnit in Stardew Valley


class LidgrenError(Exception):
    pass


class HandshakeError(LidgrenError):
    pass


class NotConnected(LidgrenError):
    pass


# --------------------------------------------------------------------------- helpers


def relative_sequence_number(nr: int, expected: int) -> int:
    """NetUtility.RelativeSequenceNumber: signed distance in the 1024 sequence space."""
    half = NUM_SEQUENCE_NUMBERS // 2
    return (nr - expected + NUM_SEQUENCE_NUMBERS + half) % NUM_SEQUENCE_NUMBERS - half


def encode_header(msg_type: int, sequence: int, is_fragment: bool, payload_bits: int) -> bytes:
    return bytes(
        (
            msg_type & 0xFF,
            ((sequence << 1) | (1 if is_fragment else 0)) & 0xFF,
            (sequence >> 7) & 0xFF,
            payload_bits & 0xFF,
            (payload_bits >> 8) & 0xFF,
        )
    )


def decode_header(data: bytes, pos: int = 0) -> Tuple[int, int, bool, int]:
    """Return (msg_type, sequence, is_fragment, payload_length_in_bytes)."""
    msg_type = data[pos]
    low = data[pos + 1]
    high = data[pos + 2]
    is_fragment = bool(low & 1)
    sequence = (low >> 1) | (high << 7)
    payload_bits = data[pos + 3] | (data[pos + 4] << 8)
    return msg_type, sequence, is_fragment, (payload_bits + 7) // 8


def encode_varuint(value: int) -> bytes:
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def decode_varuint(data: bytes, pos: int) -> Tuple[int, int]:
    result = 0
    shift = 0
    while True:
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return result, pos


def fragmentation_header_size(group: int, total_bytes: int, chunk_size: int, num_chunks: int) -> int:
    return (
        len(encode_varuint(group))
        + len(encode_varuint(total_bytes * 8))
        + len(encode_varuint(chunk_size))
        + len(encode_varuint(num_chunks))
    )


def best_chunk_size(group: int, total_bytes: int, mtu: int) -> int:
    """Port of NetFragmentationHelper.GetBestChunkSize (largest chunk that fits the MTU)."""
    try_size = mtu - HEADER_SIZE - 4
    est = fragmentation_header_size(group, total_bytes, try_size, total_bytes // try_size)
    try_size = mtu - HEADER_SIZE - est
    while True:
        try_size -= 1
        num_chunks = total_bytes // try_size
        if num_chunks * try_size < total_bytes:
            num_chunks += 1
        header = fragmentation_header_size(group, total_bytes, try_size, num_chunks)
        if try_size + header + HEADER_SIZE + 1 < mtu:
            return try_size


def write_fragment_header(group: int, total_bits: int, chunk_size: int, chunk_number: int) -> bytes:
    return (
        encode_varuint(group)
        + encode_varuint(total_bits)
        + encode_varuint(chunk_size)
        + encode_varuint(chunk_number)
    )


def read_fragment_header(data: bytes, pos: int = 0) -> Tuple[int, int, int, int, int]:
    """Return (group, total_bits, chunk_size, chunk_number, position_after_header)."""
    group, pos = decode_varuint(data, pos)
    total_bits, pos = decode_varuint(data, pos)
    chunk_size, pos = decode_varuint(data, pos)
    chunk_number, pos = decode_varuint(data, pos)
    return group, total_bits, chunk_size, chunk_number, pos


# --------------------------------------------------------------------------- state


@dataclass
class _StoredMessage:
    sequence: int
    packet: bytes
    last_sent: float
    num_sent: int = 1
    acked: bool = False


@dataclass
class _FragmentGroup:
    data: bytearray
    chunk_size: int
    num_chunks: int
    received: Set[int] = field(default_factory=set)


class _OrderedReceiver:
    """Receiving half of a ReliableOrdered channel (NetReliableOrderedReceiver)."""

    def __init__(self) -> None:
        self.window_start = 0
        self.withheld: Dict[int, Tuple[bytes, bool]] = {}

    def receive(self, sequence: int, payload: bytes, is_fragment: bool) -> List[Tuple[bytes, bool]]:
        relate = relative_sequence_number(sequence, self.window_start)
        if relate == 0:
            released = [(payload, is_fragment)]
            self.window_start = (self.window_start + 1) % NUM_SEQUENCE_NUMBERS
            while self.window_start in self.withheld:
                released.append(self.withheld.pop(self.window_start))
                self.window_start = (self.window_start + 1) % NUM_SEQUENCE_NUMBERS
            return released
        if relate < 0:
            log.debug("dropping duplicate reliable message #%d", sequence)
            return []
        if relate > WINDOW_SIZE:
            log.debug("dropping too-early reliable message #%d (expected %d)", sequence, self.window_start)
            return []
        self.withheld[sequence] = (payload, is_fragment)
        return []


# --------------------------------------------------------------------------- connection


class LidgrenConnection(asyncio.DatagramProtocol):
    """A single client connection to a Lidgren server.

    Set ``on_data`` to receive complete application payloads (already
    reassembled and in order) and ``on_disconnected`` to be told when the
    connection ends for any reason other than a local ``disconnect()``.
    """

    def __init__(
        self,
        host: str,
        port: int,
        *,
        app_identifier: str = "StardewValley",
        mtu: int = DEFAULT_MTU,
        ping_interval: float = 5.0,
        connection_timeout: float = 30.0,
        heartbeat_interval: float = 0.02,
    ) -> None:
        self.host = host
        self.port = port
        self.app_identifier = app_identifier
        self.mtu = mtu
        self.ping_interval = ping_interval
        self.connection_timeout = connection_timeout
        self.heartbeat_interval = heartbeat_interval

        self.unique_identifier = random.getrandbits(63)
        self.remote_unique_identifier: Optional[int] = None
        self.status = Status.NONE
        self.disconnect_reason: Optional[str] = None
        self.average_rtt: Optional[float] = None

        self.on_data: Optional[Callable[[bytes], None]] = None
        self.on_disconnected: Optional[Callable[[str], None]] = None

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._start_time = time.monotonic()
        self._deadline = math.inf

        self._ping_number = 0
        self._ping_sent_at = -math.inf

        self._pending_acks: List[Tuple[int, int]] = []

        # sender side of the ReliableOrdered channel
        self._send_queue: Deque[Tuple[bytes, bool]] = deque()
        self._stored: Dict[int, _StoredMessage] = {}
        self._window_start = 0
        self._send_start = 0
        self._fragment_group = 0

        # receiver side
        self._receivers: Dict[int, _OrderedReceiver] = {}
        self._fragments: Dict[int, _FragmentGroup] = {}

        self._discovery_future: Optional[asyncio.Future] = None
        self._connect_future: Optional[asyncio.Future] = None

    # ------------------------------------------------------------------ lifecycle

    async def open(self) -> None:
        """Bind the UDP socket and start the heartbeat."""
        if self._transport is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._transport, _ = await self._loop.create_datagram_endpoint(
            lambda: self, remote_addr=(self.host, self.port)
        )
        self._heartbeat_task = self._loop.create_task(self._heartbeat())

    def close(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    async def discover(self, timeout: float = 3.0, attempts: int = 3) -> List[str]:
        """Send a discovery request; return the strings in the server's response."""
        assert self._loop is not None, "call open() first"
        for attempt in range(attempts):
            fut: asyncio.Future = self._loop.create_future()
            self._discovery_future = fut
            self._send_library(LibraryType.DISCOVERY)
            done, _ = await asyncio.wait({fut}, timeout=timeout)
            if done:
                self._discovery_future = None
                return fut.result()
            log.debug("discovery attempt %d timed out", attempt + 1)
        self._discovery_future = None
        raise HandshakeError(f"no discovery response from {self.host}:{self.port}")

    async def connect(self, timeout: float = 15.0) -> None:
        """Run the connect handshake until the connection is established."""
        assert self._loop is not None, "call open() first"
        if self.status == Status.CONNECTED:
            return
        fut: asyncio.Future = self._loop.create_future()
        self._connect_future = fut
        self.status = Status.INITIATED_CONNECT
        deadline = time.monotonic() + timeout
        attempts = 0
        try:
            while True:
                w = Writer()
                w.string(self.app_identifier)
                w.i64(self.unique_identifier)
                w.f32(self._now())
                self._send_library(LibraryType.CONNECT, w.getvalue())
                attempts += 1
                wait = min(3.0, deadline - time.monotonic())  # resendHandshakeInterval = 3s
                if wait <= 0:
                    raise HandshakeError("connect timed out")
                done, _ = await asyncio.wait({fut}, timeout=wait)
                if done:
                    fut.result()  # raises HandshakeError on rejection
                    return
                if attempts >= 5:  # maximumHandshakeAttempts
                    raise HandshakeError("no response to connect from server")
                log.debug("resending Connect (attempt %d)", attempts + 1)
        finally:
            self._connect_future = None
            if self.status == Status.INITIATED_CONNECT:
                self.status = Status.NONE

    async def disconnect(self, reason: str = "", flush_timeout: float = 1.0) -> None:
        """Flush outstanding reliable messages, then send a Disconnect and close the socket."""
        if self.status == Status.CONNECTED:
            deadline = time.monotonic() + flush_timeout
            while (self._stored or self._send_queue) and time.monotonic() < deadline:
                await asyncio.sleep(self.heartbeat_interval)
            w = Writer()
            w.string(reason)
            self._send_library(LibraryType.DISCONNECT, w.getvalue())
        self.status = Status.DISCONNECTED
        self.close()

    def send_reliable(self, payload: bytes) -> None:
        """Queue an application payload for ReliableOrdered delivery (fragmenting if needed)."""
        if self.status != Status.CONNECTED:
            raise NotConnected("not connected")
        if HEADER_SIZE + len(payload) <= self.mtu:
            self._send_queue.append((payload, False))
        else:
            self._fragment_group += 1
            if self._fragment_group >= MAX_FRAGMENT_GROUPS:
                self._fragment_group = 1
            group = self._fragment_group
            chunk = best_chunk_size(group, len(payload), self.mtu)
            total_bits = len(payload) * 8
            for number, offset in enumerate(range(0, len(payload), chunk)):
                header = write_fragment_header(group, total_bits, chunk, number)
                self._send_queue.append((header + payload[offset : offset + chunk], True))
        self._flush_send_queue()

    # ------------------------------------------------------------------ asyncio protocol

    def connection_made(self, transport) -> None:  # type: ignore[override]
        self._transport = transport

    def datagram_received(self, data: bytes, addr) -> None:  # type: ignore[override]
        if self.status == Status.DISCONNECTED:
            return
        n = len(data)
        pos = 0
        messages = []
        while n - pos >= HEADER_SIZE:
            msg_type, sequence, is_fragment, length = decode_header(data, pos)
            pos += HEADER_SIZE
            if n - pos < length:
                log.warning("malformed packet: payload %d bytes, %d left", length, n - pos)
                break
            payload = data[pos : pos + length]
            pos += length
            messages.append((msg_type, sequence, is_fragment, payload))
            if USER_RELIABLE_UNORDERED <= msg_type < LibraryType.LIBRARY_ERROR:
                self._pending_acks.append((msg_type, sequence))
        # Ack before handling: the host resends after ~25 ms + 2.1 x RTT, so the
        # ack must not wait on the game-level callbacks (delta parsing etc.).
        if self.status != Status.DISCONNECTED:
            self._flush_acks()
        for msg_type, sequence, is_fragment, payload in messages:
            try:
                if msg_type >= LibraryType.LIBRARY_ERROR:
                    self._handle_library(msg_type, payload)
                elif msg_type == UNCONNECTED:
                    log.debug("ignoring unconnected data (%d bytes)", len(payload))
                else:
                    self._handle_user(msg_type, sequence, is_fragment, payload)
            except Exception:  # keep the transport alive on parse errors
                log.exception("error handling Lidgren message type %d", msg_type)
        self._flush_acks()
        if self.status == Status.CONNECTED:
            self._deadline = time.monotonic() + self.connection_timeout

    def error_received(self, exc: Exception) -> None:  # type: ignore[override]
        log.warning("UDP error: %s", exc)

    def connection_lost(self, exc) -> None:  # type: ignore[override]
        if exc is not None:
            log.warning("UDP socket closed: %s", exc)

    # ------------------------------------------------------------------ library messages

    def _handle_library(self, msg_type: int, payload: bytes) -> None:
        if msg_type == LibraryType.PING:
            # reply with the ping number and our current time
            self._send_library(LibraryType.PONG, bytes([payload[0]]) + struct.pack("<f", self._now()))
        elif msg_type == LibraryType.PONG:
            r = Reader(payload)
            number = r.u8()
            r.f32()  # remote send time; only needed for clock sync
            if number == self._ping_number & 0xFF:
                rtt = time.monotonic() - self._ping_sent_at
                self.average_rtt = rtt if self.average_rtt is None else self.average_rtt * 0.7 + rtt * 0.3
        elif msg_type == LibraryType.ACKNOWLEDGE:
            for i in range(0, len(payload) - 2, 3):
                self._receive_ack(payload[i], payload[i + 1] | (payload[i + 2] << 8))
        elif msg_type == LibraryType.CONNECT_RESPONSE:
            self._handle_connect_response(payload)
        elif msg_type == LibraryType.CONNECTION_ESTABLISHED:
            pass
        elif msg_type == LibraryType.DISCONNECT:
            reason = ""
            try:
                reason = Reader(payload).string()
            except (EOFError, UnicodeDecodeError):
                pass
            self._remote_disconnect(reason or "disconnected by server")
        elif msg_type == LibraryType.DISCOVERY_RESPONSE:
            strings: List[str] = []
            r = Reader(payload)
            try:
                while r.remaining() > 0:
                    strings.append(r.string())
            except (EOFError, UnicodeDecodeError):
                pass
            fut = self._discovery_future
            if fut is not None and not fut.done():
                fut.set_result(strings)
        elif msg_type == LibraryType.EXPAND_MTU_REQUEST:
            self._send_library(LibraryType.EXPAND_MTU_SUCCESS, struct.pack("<i", len(payload)))
        else:
            log.debug("unhandled library message %d (%d bytes)", msg_type, len(payload))

    def _handle_connect_response(self, payload: bytes) -> None:
        r = Reader(payload)
        app = r.string()
        remote_uid = r.i64()
        r.f32()  # remote time
        if app != self.app_identifier:
            self._fail_connect(HandshakeError(f"wrong application identifier {app!r}"))
            return
        self.remote_unique_identifier = remote_uid
        # (re)send ConnectionEstablished; the server resends ConnectResponse if it got lost
        self._send_library(LibraryType.CONNECTION_ESTABLISHED, struct.pack("<f", self._now()))
        if self.status != Status.CONNECTED:
            self.status = Status.CONNECTED
            self._deadline = time.monotonic() + self.connection_timeout * 2
            self._send_ping()
            log.info("connected to %s:%d (remote id %x)", self.host, self.port, remote_uid & 0xFFFFFFFFFFFFFFFF)
            fut = self._connect_future
            if fut is not None and not fut.done():
                fut.set_result(None)

    def _fail_connect(self, exc: Exception) -> None:
        fut = self._connect_future
        if fut is not None and not fut.done():
            fut.set_exception(exc)

    def _remote_disconnect(self, reason: str) -> None:
        was_connected = self.status == Status.CONNECTED
        log.info("disconnected: %s", reason)
        self.status = Status.DISCONNECTED
        self.disconnect_reason = reason
        self._fail_connect(HandshakeError(f"server refused connection: {reason}"))
        if was_connected and self.on_disconnected is not None:
            try:
                self.on_disconnected(reason)
            except Exception:
                log.exception("on_disconnected callback failed")

    # ------------------------------------------------------------------ user messages

    def _handle_user(self, msg_type: int, sequence: int, is_fragment: bool, payload: bytes) -> None:
        # acks for reliable messages are queued in datagram_received, before handling
        if msg_type >= USER_RELIABLE_ORDERED:
            receiver = self._receivers.get(msg_type)
            if receiver is None:
                receiver = self._receivers[msg_type] = _OrderedReceiver()
            for released, frag in receiver.receive(sequence, payload, is_fragment):
                self._release(released, frag)
        else:
            self._release(payload, is_fragment)

    def _release(self, payload: bytes, is_fragment: bool) -> None:
        if not is_fragment:
            self._deliver(payload)
            return
        group, total_bits, chunk_size, chunk_number, pos = read_fragment_header(payload)
        total_bytes = (total_bits + 7) // 8
        num_chunks = total_bytes // chunk_size + (1 if total_bytes % chunk_size else 0)
        fg = self._fragments.get(group)
        if fg is None:
            fg = self._fragments[group] = _FragmentGroup(bytearray(total_bytes), chunk_size, num_chunks)
        offset = chunk_number * chunk_size
        chunk = payload[pos : pos + min(chunk_size, total_bytes - offset)]
        fg.data[offset : offset + len(chunk)] = chunk
        fg.received.add(chunk_number)
        if len(fg.received) >= fg.num_chunks:
            del self._fragments[group]
            self._deliver(bytes(fg.data))

    def _deliver(self, payload: bytes) -> None:
        if self.on_data is None:
            return
        try:
            self.on_data(payload)
        except Exception:
            log.exception("on_data callback failed")

    # ------------------------------------------------------------------ sending

    def _now(self) -> float:
        """Seconds since this peer started, as Lidgren's NetTime.Now (only used for clock sync)."""
        return time.monotonic() - self._start_time

    def _send_packet(self, data: bytes) -> None:
        if self._transport is not None:
            self._transport.sendto(data)

    def _send_library(self, msg_type: int, payload: bytes = b"") -> None:
        self._send_packet(encode_header(msg_type, 0, False, len(payload) * 8) + payload)

    def _send_ping(self) -> None:
        self._ping_number += 1
        self._ping_sent_at = time.monotonic()
        self._send_library(LibraryType.PING, bytes([self._ping_number & 0xFF]))

    def _flush_acks(self) -> None:
        per_packet = max(1, (self.mtu - HEADER_SIZE) // 3)
        while self._pending_acks:
            batch, self._pending_acks = self._pending_acks[:per_packet], self._pending_acks[per_packet:]
            payload = bytearray()
            for msg_type, sequence in batch:
                payload += bytes((msg_type, sequence & 0xFF, (sequence >> 8) & 0xFF))
            self._send_library(LibraryType.ACKNOWLEDGE, bytes(payload))

    def _allowed_sends(self) -> int:
        in_flight = (self._send_start - self._window_start + NUM_SEQUENCE_NUMBERS) % NUM_SEQUENCE_NUMBERS
        return WINDOW_SIZE - in_flight

    def _flush_send_queue(self) -> None:
        now = time.monotonic()
        while self._send_queue and self._allowed_sends() > 0:
            payload, is_fragment = self._send_queue.popleft()
            sequence = self._send_start
            self._send_start = (sequence + 1) % NUM_SEQUENCE_NUMBERS
            packet = encode_header(USER_RELIABLE_ORDERED, sequence, is_fragment, len(payload) * 8) + payload
            self._stored[sequence] = _StoredMessage(sequence, packet, now)
            self._send_packet(packet)

    def _receive_ack(self, msg_type: int, sequence: int) -> None:
        if msg_type != USER_RELIABLE_ORDERED:
            return
        stored = self._stored.get(sequence)
        if stored is None:
            return  # late / duplicate ack
        stored.acked = True
        # advance the window over everything that has been acknowledged in order
        while self._window_start != self._send_start:
            head = self._stored.get(self._window_start)
            if head is None or not head.acked:
                break
            del self._stored[self._window_start]
            self._window_start = (self._window_start + 1) % NUM_SEQUENCE_NUMBERS
        self._flush_send_queue()

    def _resend_delay(self) -> float:
        rtt = self.average_rtt if self.average_rtt is not None and self.average_rtt > 0 else 0.1
        return 0.025 + rtt * 2.1

    # ------------------------------------------------------------------ heartbeat

    async def _heartbeat(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.heartbeat_interval)
                try:
                    self._tick()
                except Exception:
                    log.exception("heartbeat failed")
        except asyncio.CancelledError:
            pass

    def _tick(self) -> None:
        now = time.monotonic()
        if self.status == Status.CONNECTED:
            if now > self._deadline:
                self._remote_disconnect("connection timed out")
                return
            if now - self._ping_sent_at >= self.ping_interval:
                self._send_ping()
            delay = self._resend_delay()
            for stored in self._stored.values():
                if not stored.acked and now - stored.last_sent > delay:
                    self._send_packet(stored.packet)
                    stored.last_sent = now
                    stored.num_sent += 1
            self._flush_send_queue()
        self._flush_acks()

    @property
    def outstanding(self) -> int:
        """Reliable messages sent but not yet acknowledged (plus queued ones)."""
        return len(self._stored) + len(self._send_queue)
