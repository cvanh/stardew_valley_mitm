#!/usr/bin/env python3
"""Dump the Lidgren and Stardew Valley messages in a packet capture.

Uses ``tshark`` to pull the UDP payloads out of a pcap/pcapng, reassembles
Lidgren fragments per direction, decompresses the game messages and prints
one line per message.  With ``--out DIR`` every decoded game message body is
also written to ``DIR/<frame>_<direction>_t<type>.bin`` for further poking.

    python3 tools/pcap_dump.py star.pcapng
    python3 tools/pcap_dump.py star.pcapng --out /tmp/msgs --port 24642
"""

from __future__ import annotations

import argparse
import collections
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from sdvclient.lidgren import HEADER_SIZE, LibraryType, decode_header, read_fragment_header  # noqa: E402
from sdvclient.protocol import decode_game_messages, message_type_name  # noqa: E402

TSHARK_CANDIDATES = ("tshark", "/Applications/Wireshark.app/Contents/MacOS/tshark")


def find_tshark(explicit: str | None) -> str:
    for candidate in ([explicit] if explicit else []) + list(TSHARK_CANDIDATES):
        if candidate and (shutil.which(candidate) or os.path.exists(candidate)):
            return candidate
    sys.exit("tshark not found; install Wireshark or pass --tshark PATH")


def extract(pcap: str, port: int, tshark: str):
    cmd = [
        tshark, "-r", pcap, "-Y", f"udp.port=={port}", "-T", "fields",
        "-e", "frame.number", "-e", "frame.time_relative", "-e", "ip.src", "-e", "udp.srcport",
        "-e", "ip.dst", "-e", "udp.dstport", "-e", "udp.payload", "-E", "separator=/t",
    ]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    for line in out.splitlines():
        fields = line.split("\t")
        if len(fields) < 7 or not fields[6]:
            continue
        frame, t, src, sport, dst, dport, payload = fields[:7]
        direction = "C->S" if dport == str(port) else "S->C"
        yield int(frame), float(t), f"{src}:{sport}", f"{dst}:{dport}", direction, bytes.fromhex(payload.replace(":", ""))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pcap")
    ap.add_argument("--port", type=int, default=24642)
    ap.add_argument("--tshark")
    ap.add_argument("--out", help="directory to write decoded game message bodies to")
    ap.add_argument("--quiet-lib", action="store_true", help="hide ping/pong/ack lines")
    args = ap.parse_args()

    fragments: dict = collections.defaultdict(dict)
    complete = []
    for frame, t, src, dst, direction, data in extract(args.pcap, args.port, find_tshark(args.tshark)):
        pos = 0
        while len(data) - pos >= HEADER_SIZE:
            msg_type, seq, is_frag, length = decode_header(data, pos)
            pos += HEADER_SIZE
            body = data[pos:pos + length]
            pos += length
            prefix = f"{frame:>6} {t:8.3f} {direction}"
            if msg_type >= LibraryType.LIBRARY_ERROR:
                name = LibraryType(msg_type).name if msg_type in LibraryType._value2member_map_ else str(msg_type)
                if msg_type == LibraryType.ACKNOWLEDGE:
                    acks = [(body[i], body[i + 1] | (body[i + 2] << 8)) for i in range(0, len(body) - 2, 3)]
                    if not args.quiet_lib:
                        print(f"{prefix} ACK {[s for _, s in acks]}")
                elif msg_type in (LibraryType.PING, LibraryType.PONG) and args.quiet_lib:
                    pass
                else:
                    print(f"{prefix} {name} {body.hex()}")
                continue
            if is_frag:
                group, total_bits, chunk_size, chunk_number, hpos = read_fragment_header(body)
                total = (total_bits + 7) // 8
                store = fragments[(direction, group)]
                store[chunk_number] = body[hpos:]
                have = sum(len(v) for v in store.values())
                print(f"{prefix} DATA type={msg_type} seq={seq} fragment group={group} chunk={chunk_number} "
                      f"({have}/{total} bytes)")
                if have >= total:
                    complete.append((frame, direction, b"".join(store[k] for k in sorted(store))))
                    del fragments[(direction, group)]
            else:
                print(f"{prefix} DATA type={msg_type} seq={seq} len={len(body)}")
                complete.append((frame, direction, body))

    print("\n=== game messages ===")
    if args.out:
        os.makedirs(args.out, exist_ok=True)
    for frame, direction, payload in complete:
        try:
            messages = decode_game_messages(payload)
        except Exception as exc:  # noqa: BLE001
            print(f"{frame:>6} {direction} undecodable payload ({len(payload)} bytes): {exc}")
            continue
        for msg in messages:
            print(f"{frame:>6} {direction} {msg.type:>3} {message_type_name(msg.type):<26} farmer={msg.farmer_id:<21} "
                  f"len={len(msg.data):<7}{' lz4' if msg.compressed else '    '} {msg.data[:32].hex()}")
            if args.out:
                name = f"{frame:05d}_{direction.replace('->', '_')}_t{msg.type}.bin"
                with open(os.path.join(args.out, name), "wb") as fh:
                    fh.write(msg.data)


if __name__ == "__main__":
    main()
