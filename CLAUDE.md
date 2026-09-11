# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A reverse-engineered Python client for the Stardew Valley (PC, 1.6.x) multiplayer
protocol. It joins a running game over IP, chats, and walks — no game install
needed. The library is standard-library-only (Python 3.9+); `.venv` here is
Python 3.14 but nothing outside `pip` is installed.

## Commands

```sh
# run the client against a live host (see readme.md for the full flag set)
python3 client.py 10.1.110.27:24642 --list
python3 client.py 10.1.110.27:24642 --say "hi" --walk 3,0 --listen 30
python3 client.py HOST:PORT --farmhand NAME --interactive

# tests (unittest, not pytest; they assert against bytes captured in star.pcapng)
python3 -m unittest tests.test_sdvclient -v
python3 -m unittest tests.test_sdvclient.ClassName.test_method   # single test

# decode a capture into Lidgren + game messages (needs tshark on PATH)
python3 tools/pcap_dump.py star.pcapng --quiet-lib
python3 tools/pcap_dump.py star.pcapng --out /tmp/msgs
```

There is no lint/build/typecheck setup and no `pip`-installable dependencies.

## Architecture

Three protocol layers, each its own module under `sdvclient/`, wrapped by a
high-level client. **`docs/protocol.md` is the authoritative spec** — read it
before touching any wire format; every layer below maps 1:1 to a section there.

- `sdvclient/lidgren.py` — Lidgren.Network gen3 UDP transport: discovery,
  handshake, reliable-ordered delivery (type 67), acks, fragmentation,
  keep-alive. `LidgrenConnection` is the async socket layer.
- `sdvclient/protocol.py` — the Stardew message envelope: one
  `(type, farmerId, data)` record per game message, LZ4 wrapper for bodies
  ≥1 KiB, and the `MessageType` catalogue. Only the handful of message bodies
  the client actually uses are parsed/built here.
- `sdvclient/netcode.py` — Netcode object sync: `NetVersion` vector clocks and
  per-field deltas for `Farmer` / `NetWorldState`. `FARMER_FIELD_COUNT` and the
  field indices are game-version-specific (158 on 1.6.15).
- `sdvclient/binary.py` — `Reader`/`Writer` matching .NET `BinaryWriter`
  (7-bit varint-prefixed strings, little-endian). `sdvclient/lz4.py` — pure-Python
  LZ4 block decompress.
- `sdvclient/client.py` — `StardewClient`: connect → farmhand list → join →
  chat/walk/warp, plus `on_*` callbacks. This is the public API (re-exported
  from `sdvclient/__init__.py`).

`client.py` (repo root) is the CLI front-end. `mitm.py` is the older mitmproxy
addon used during reverse engineering (`./mitmweb --mode reverse:udp://127.0.0.1:24642 -s ./mitm.py`).

## Working in this repo

- **Scope is deliberately narrow: join / walk / chat only.** Keep the client
  simple; do not add game-state decoding, collision, or the new-day handshake
  unless asked. Protocol findings and design notes belong in `docs/*.md`, not
  inline.
- The protocol is version-sensitive. Field counts and layouts are tied to the
  server's game version (verified against 1.6.15). `NetFields.Read` throws if a
  BitArray's length ≠ the receiver's field count, so the client learns the count
  from the first farmer delta rather than hardcoding beyond the known default.
- Deltas must bump `v[0]` of the sender's `NetVersion` every send, or the server
  rejects the field (priority check).
- Known limitations are listed in `docs/protocol.md` §5 (joins only as an
  existing farmhand; no new-day/ready handshake, so leave before the host
  sleeps; no collision; location/team state undecoded).
- `notes.md` is the raw original reverse-engineering log; `docs/protocol.md` is
  the cleaned-up version. Prefer the latter.
- Tests are golden-byte assertions from real captures (`star.pcapng`,
  `star2.pcapng`) — when changing wire code, cross-check against these captures
  rather than inventing bytes.
