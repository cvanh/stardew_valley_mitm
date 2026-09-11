"""Unit tests for sdvclient, using byte strings captured from a real 1.6.15 game (star.pcapng)."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from sdvclient import netcode, protocol  # noqa: E402
from sdvclient.binary import Reader, Writer  # noqa: E402
from sdvclient.lidgren import (  # noqa: E402
    HEADER_SIZE,
    LibraryType,
    USER_RELIABLE_ORDERED,
    _OrderedReceiver,
    best_chunk_size,
    decode_header,
    encode_header,
    read_fragment_header,
    relative_sequence_number,
    write_fragment_header,
)
from sdvclient.lz4 import block_decompress  # noqa: E402

# --- captured packets -------------------------------------------------------------

# discovery response: "1.6.15", "StardewValley"
DISCOVERY_RESPONSE = bytes.fromhex("890000a80006312e362e31350d5374617264657756616c6c6579")
# client Connect: app id, unique id, time
CONNECT = bytes.fromhex("830000d0000d5374617264657756616c6c6579d977bad617443e7dc03dad44")
# first fragment of the server's availableFarmhands message (group 7, chunk 0 of 8)
FRAGMENT0_HEAD = bytes.fromhex("430100482507f0ad04a20900")
# ack for reliable-ordered messages 0..7
ACK = bytes.fromhex("860000c000430000430100430200430300430400430500430600430700")
# worldDelta (type 12) body: timeOfDay -> 1900
WORLD_DELTA = bytes.fromhex("02f454010000000000000c00000038001000000000006c070000")
# farmerDelta (type 0) body sent by the joining client (position, speed, isInBed, msPlayed, ...)
FARMER_DELTA = bytes.fromhex(
    "36afc82b698a35a5"                          # farmer id
    "02" "01000000" "00000000"                  # version vector [1, 0]
    "00" "17010000"                             # ChildDelta, 279 byte body
    "9e01" "0a00000000001000000400000000000000800200"  # 158 dirty bits: 1,3,52,74,143,145
    "0305000010440000184400"                    # position: (576, 608), moving=false
    "05000000"                                  # speed 5
    "01"                                        # isInBed
    "d043560100000000"                          # millisecondsPlayed
    # field 143 (buffs net fields) and 145 (companions list): two freshly allocated NetArrays
    "020100000000014a000000020000000000000000124e6574636f64652e4e6574417272617960320d53797374"
    "656d2e537472696e67114e6574636f64652e4e6574537472696e670a000000000000000000000000000000000000"
    "018b000000020000000000000000124e6574636f64652e4e657441727261796032225374617264657756616c6c"
    "65792e436f6d70616e696f6e732e436f6d70616e696f6e104e6574636f64652e4e65745265666031225374617264"
    "657756616c6c65792e436f6d70616e696f6e732e436f6d70616e696f6e0a0000000000000000000000000000000000"
    "0000000000"
)
# chat message (type 10) body from notes.md: to everyone, english, "kaas"
CHAT = bytes.fromhex("0000000000000000" "0000" "046b616173")
# complete game message envelope for that chat message
CHAT_ENVELOPE = bytes.fromhex("0a" "ef54e8a0f1fb93db" "0f000000") + CHAT


class BinaryTests(unittest.TestCase):
    def test_roundtrip(self):
        w = Writer()
        w.u8(1); w.i16(-2); w.i32(3); w.i64(-4); w.f32(1.5); w.bool_(True)
        w.varint(300); w.string("héllo"); w.bitarray([True, False, False, True, False, False, False, False, True])
        w.skippable(b"xyz")
        r = Reader(w.getvalue())
        self.assertEqual(r.u8(), 1)
        self.assertEqual(r.i16(), -2)
        self.assertEqual(r.i32(), 3)
        self.assertEqual(r.i64(), -4)
        self.assertEqual(r.f32(), 1.5)
        self.assertTrue(r.bool_())
        self.assertEqual(r.varint(), 300)
        self.assertEqual(r.string(), "héllo")
        self.assertEqual(r.bitarray(), [True, False, False, True, False, False, False, False, True])
        self.assertEqual(r.skippable(), b"xyz")
        self.assertTrue(r.eof())

    def test_bitarray_matches_game(self):
        # 158 fields, bits 1,3,52,74,143,145 set (from the captured farmer delta)
        raw = bytes.fromhex("9e010a00000000001000000400000000000000800200")
        bits = Reader(raw).bitarray()
        self.assertEqual(len(bits), 158)
        self.assertEqual([i for i, b in enumerate(bits) if b], [1, 3, 52, 74, 143, 145])
        w = Writer(); w.bitarray(bits)
        self.assertEqual(w.getvalue(), raw)


class LZ4Tests(unittest.TestCase):
    def test_literals_and_match(self):
        # 5 literals "abcde", then a match of length 4 at offset 5 -> "abcdeabcd"
        block = bytes([0x50]) + b"abcde" + bytes([5, 0])
        self.assertEqual(block_decompress(block, 9), b"abcdeabcd")

    def test_overlapping_match(self):
        # 1 literal "a", then a match of length 4+11 at offset 1 -> "a" * 16
        block = bytes([0x1B]) + b"a" + bytes([1, 0])
        self.assertEqual(block_decompress(block, 16), b"a" * 16)

    def test_size_mismatch(self):
        with self.assertRaises(ValueError):
            block_decompress(bytes([0x10]) + b"a", 5)


class LidgrenTests(unittest.TestCase):
    def test_header(self):
        msg_type, seq, frag, length = decode_header(FRAGMENT0_HEAD)
        self.assertEqual((msg_type, seq, frag, length), (USER_RELIABLE_ORDERED, 0, True, 1193))
        self.assertEqual(encode_header(USER_RELIABLE_ORDERED, 0, True, 0x2548), FRAGMENT0_HEAD[:HEADER_SIZE])
        # seq 79 unfragmented, 312 bits
        self.assertEqual(decode_header(bytes.fromhex("439e003801")), (0x43, 79, False, 39))

    def test_discovery_response(self):
        msg_type, seq, frag, length = decode_header(DISCOVERY_RESPONSE)
        self.assertEqual(msg_type, LibraryType.DISCOVERY_RESPONSE)
        r = Reader(DISCOVERY_RESPONSE[HEADER_SIZE:HEADER_SIZE + length])
        self.assertEqual((r.string(), r.string()), ("1.6.15", "StardewValley"))

    def test_connect_layout(self):
        r = Reader(CONNECT[HEADER_SIZE:])
        self.assertEqual(r.string(), "StardewValley")
        r.i64(); r.f32()
        self.assertTrue(r.eof())

    def test_fragment_header(self):
        group, total_bits, chunk, number, pos = read_fragment_header(FRAGMENT0_HEAD, HEADER_SIZE)
        self.assertEqual((group, total_bits, chunk, number), (7, 71408, 1186, 0))
        self.assertEqual(pos, HEADER_SIZE + 7)
        self.assertEqual(write_fragment_header(7, 71408, 1186, 0), FRAGMENT0_HEAD[HEADER_SIZE:])

    def test_best_chunk_size_matches_server(self):
        self.assertEqual(best_chunk_size(7, 8926, 1200), 1186)
        self.assertEqual(best_chunk_size(9, 1639, 1200), 1187)
        self.assertEqual(best_chunk_size(8, 59580, 1200), 1186)

    def test_ack_layout(self):
        msg_type, _, _, length = decode_header(ACK)
        self.assertEqual(msg_type, LibraryType.ACKNOWLEDGE)
        body = ACK[HEADER_SIZE:]
        acks = [(body[i], body[i + 1] | body[i + 2] << 8) for i in range(0, length, 3)]
        self.assertEqual(acks, [(0x43, s) for s in range(8)])

    def test_relative_sequence(self):
        self.assertEqual(relative_sequence_number(5, 5), 0)
        self.assertEqual(relative_sequence_number(6, 5), 1)
        self.assertEqual(relative_sequence_number(4, 5), -1)
        self.assertEqual(relative_sequence_number(0, 1023), 1)

    def test_ordered_receiver_reorders(self):
        rx = _OrderedReceiver()
        self.assertEqual(rx.receive(1, b"b", False), [])
        self.assertEqual(rx.receive(0, b"a", False), [(b"a", False), (b"b", False)])
        self.assertEqual(rx.receive(0, b"a", False), [])  # duplicate
        self.assertEqual(rx.receive(2, b"c", False), [(b"c", False)])


class ProtocolTests(unittest.TestCase):
    def test_envelope_roundtrip(self):
        host_id = -2624477142621596433  # 0xdb93fbf1a0e854ef, the host farmer in the capture
        data = protocol.encode_game_message(10, host_id, CHAT)
        self.assertEqual(data, CHAT_ENVELOPE)
        msgs = protocol.decode_game_messages(CHAT_ENVELOPE + CHAT_ENVELOPE)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].type, protocol.MessageType.CHAT_MESSAGE)
        self.assertEqual(msgs[0].farmer_id, -2624477142621596433)
        self.assertEqual(protocol.parse_chat_message(msgs[0].data), (0, 0, "kaas"))

    def test_compressed_envelope(self):
        # build an LZ4 block by hand: all literals
        inner = CHAT_ENVELOPE
        block = bytes([0xF0, len(inner) - 15]) + inner
        payload = bytes([127]) + struct.pack("<ii", len(block), len(inner)) + block
        msgs = protocol.decode_game_messages(payload)
        self.assertEqual(len(msgs), 1)
        self.assertTrue(msgs[0].compressed)
        self.assertEqual(msgs[0].data, CHAT)

    def test_chat_build(self):
        self.assertEqual(protocol.build_chat_message("kaas"), CHAT)
        self.assertEqual(protocol.parse_chat_message(protocol.build_chat_message("hi", 42, 6)), (42, 6, "hi"))

    def test_chat_info(self):
        w = Writer(); w.string("PlayerJoined"); w.u8(2); w.string("a"); w.string("b")
        self.assertEqual(protocol.parse_chat_info_message(w.getvalue()), ("PlayerJoined", ["a", "b"]))

    def test_warp(self):
        # trailing byte carries the mandatory WARP_FLAG (0x04), not a plain isStructure bool
        r = Reader(protocol.build_warp_farmer(30, 60, "Town"))
        self.assertEqual((r.i16(), r.i16(), r.string(), r.u8()), (30, 60, "Town", protocol.WARP_FLAG))
        r = Reader(protocol.build_warp_farmer(6, 6, "UndergroundMine1", is_structure=True))
        self.assertEqual((r.i16(), r.i16(), r.string(), r.u8()),
                         (6, 6, "UndergroundMine1", protocol.WARP_FLAG | 0x01))

    def test_tiles(self):
        self.assertEqual(protocol.tile_to_pixel(10, 9), (640.0, 592.0))
        self.assertEqual(protocol.pixel_to_tile(640, 576), (10, 9))
        self.assertEqual(protocol.pixel_to_tile(*protocol.tile_to_pixel(3, 7)), (3, 7))

    def _farmhand_xml(self, name, uid):
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n<Farmer xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f"<name>{name}</name><isCustomized>true</isCustomized><homeLocation>Cabin1</homeLocation>"
            f"<Position><X>640</X><Y>576</Y></Position><FacingDirection>1</FacingDirection>"
            f"<UniqueMultiplayerID>{uid}</UniqueMultiplayerID><money>7</money></Farmer>"
        ).encode()

    def test_available_farmhands(self):
        xml1 = self._farmhand_xml("alice", 11)
        xml2 = self._farmhand_xml("bob", 22)
        blob1 = b"\x00" + struct.pack("<i", len(xml1)) + xml1 + b"\x01\x02\x03\x04\x05\x06"  # fake net fields
        blob2 = b"\x00" + struct.pack("<i", len(xml2)) + xml2 + b"\x07\x08"
        data = struct.pack("<iiiB", 2, 1, 15, 2) + blob1 + blob2
        available = protocol.parse_available_farmhands(data)
        self.assertEqual((available.year, available.season_name, available.day_of_month), (2, "summer", 15))
        self.assertEqual([f.name for f in available.farmhands], ["alice", "bob"])
        self.assertEqual(available.farmhands[0].blob, blob1)
        self.assertEqual(available.farmhands[1].blob, blob2)
        self.assertEqual(available.farmhands[0].info.tile, (10, 9))
        self.assertFalse(any(f.ambiguous for f in available.farmhands))
        intro = protocol.build_player_introduction(available.farmhands[1].blob)
        self.assertEqual(intro[:10], bytes.fromhex("01020000000000000000"))
        self.assertEqual(intro[10:], blob2)


class NetcodeTests(unittest.TestCase):
    def test_parse_world_delta(self):
        delta = netcode.parse_world_delta(WORLD_DELTA)
        self.assertEqual(delta.version.vector, [87284, 0])
        self.assertEqual(delta.field_count, 56)
        self.assertEqual(delta.dirty, [netcode.W_TIME_OF_DAY])
        self.assertEqual(delta.values[netcode.W_TIME_OF_DAY], 1900)
        self.assertTrue(delta.complete)

    def test_parse_farmer_delta(self):
        delta = netcode.parse_farmer_delta(FARMER_DELTA)
        self.assertEqual(delta.farmer_id, -6542170699375005898)
        self.assertEqual(delta.root.version.vector, [1, 0])
        self.assertEqual(delta.field_count, 158)
        self.assertEqual(delta.root.dirty, [1, 3, 52, 74, 143, 145])
        self.assertEqual(delta.position, (576.0, 608.0))
        self.assertIs(delta.moving, False)
        self.assertEqual(delta.get(netcode.F_SPEED), 5)
        self.assertIs(delta.get(netcode.F_IS_IN_BED), True)
        self.assertEqual(delta.get(netcode.F_MILLISECONDS_PLAYED), 22430672)
        self.assertFalse(delta.root.complete)  # fields 143/145 are beyond the known schema

    def test_build_farmer_delta_matches_capture(self):
        version = netcode.NetVersion([1, 0])
        data = netcode.build_farmer_delta(-6542170699375005898, version, 158, position=(576.0, 608.0),
                                          moving=False, speed=5)
        r = Reader(data)
        self.assertEqual(r.i64(), -6542170699375005898)
        self.assertEqual(netcode.NetVersion.read(r).vector, [1, 0])
        self.assertEqual(r.u8(), 0)
        body = Reader(r.skippable())
        bits = body.bitarray()
        self.assertEqual(len(bits), 158)
        self.assertEqual([i for i, b in enumerate(bits) if b], [1, 3])
        # position field bytes exactly as the real client sends them
        self.assertEqual(body.read(11), bytes.fromhex("0305000010440000184400"))
        self.assertEqual(body.i32(), 5)
        self.assertTrue(body.eof())
        # and it parses back
        parsed = netcode.parse_farmer_delta(data)
        self.assertEqual(parsed.position, (576.0, 608.0))
        self.assertTrue(parsed.root.complete)

    def test_build_with_location_and_name(self):
        data = netcode.build_farmer_delta(5, netcode.NetVersion([3, 0]), 158, name="bot",
                                          location=("Town", False), facing=1)
        parsed = netcode.parse_farmer_delta(data)
        self.assertEqual(parsed.get(netcode.F_NAME), "bot")
        self.assertEqual(parsed.get(netcode.F_FACING_DIRECTION), 1)
        self.assertEqual(parsed.location, "Town")
        self.assertEqual(parsed.root.values[netcode.F_CURRENT_LOCATION]["is_structure"], False)

    def test_build_team_delta_money(self):
        # Anchored to a live 1.6.15 teamDelta captured while buying grass starter
        # (100g) at Pierre: field_count=77, dirty=[0] (money), tail=9cffffff (-100).
        data = netcode.build_team_delta(netcode.NetVersion([71943, 0]),
                                        netcode.FARMER_TEAM_FIELD_COUNT,
                                        netcode.F_TEAM_MONEY, -100)
        r = Reader(data)
        self.assertEqual(netcode.NetVersion.read(r).vector, [71943, 0])
        self.assertEqual(r.u8(), 0)  # RefDeltaType.ChildDelta
        body = Reader(r.skippable())
        bits = body.bitarray()
        self.assertEqual(len(bits), 77)
        self.assertEqual([i for i, b in enumerate(bits) if b], [0])
        self.assertEqual(body.read(4).hex(), "9cffffff")  # int32 -100, as captured
        self.assertTrue(body.eof())
        # and it parses back, positive deltas (adding gold) too
        probe = netcode.parse_team_delta(data)
        self.assertEqual(probe.field_count, 77)
        self.assertEqual(probe.dirty, [0])
        self.assertEqual(struct.unpack("<i", probe.tail)[0], -100)
        probe = netcode.parse_team_delta(
            netcode.build_team_delta(netcode.NetVersion([1, 0]), 77, 0, 1000))
        self.assertEqual(struct.unpack("<i", probe.tail)[0], 1000)


if __name__ == "__main__":
    unittest.main()
