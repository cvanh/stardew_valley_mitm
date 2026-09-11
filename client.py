#!/usr/bin/env python3
"""Command line front-end for sdvclient: join a Stardew Valley game, chat and walk.

Examples::

    python3 client.py 10.1.120.13:24642 --list
    python3 client.py 10.1.120.13:24642 --say "hello from python" --walk 3,0 --listen 30
    python3 client.py 10.1.120.13:24642 --farmhand dsf --interactive

Interactive mode reads lines from stdin: plain text is sent as chat, and the
commands ``/walk X Y`` (tiles, relative), ``/goto X Y`` (tiles, absolute),
``/warp LOCATION X Y``, ``/face 0-3``, ``/players``, ``/world`` and ``/quit``
are understood.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sdvclient import DEFAULT_PORT, JoinRejected, StardewClient, StardewError


def parse_address(value: str):
    if ":" in value:
        host, port = value.rsplit(":", 1)
        return host, int(port)
    return value, DEFAULT_PORT


def parse_pair(value: str):
    parts = value.replace(" ", "").split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("expected X,Y")
    return int(parts[0]), int(parts[1])


def attach_printers(client: StardewClient) -> None:
    def who(sender, farmer_id):
        return sender.name if sender is not None and sender.name else str(farmer_id)

    client.on_chat = lambda m, s: print(f"[chat] {who(s, m.sender_id)}{' (private)' if m.is_private else ''}: {m.text}")
    client.on_chat_info = lambda key, args: print(f"[info] {key} {' '.join(args)}".rstrip())
    client.on_player_joined = lambda p: print(f"[join] {p}")
    client.on_player_left = lambda p: print(f"[left] {p}")
    client.on_connection_message = lambda key: print(f"[server] {key}")
    client.on_disconnected = lambda reason: print(f"[disconnected] {reason}")

    last_clock = {"value": None}

    def on_world(world):
        if world.clock != last_clock["value"]:
            last_clock["value"] = world.clock
            print(f"[world] {world}")

    client.on_world_updated = on_world


async def interactive(client: StardewClient) -> None:
    loop = asyncio.get_running_loop()
    print("interactive mode - type text to chat, /help for commands")
    while client.joined:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            if not line.startswith("/"):
                client.chat(line)
                continue
            cmd, *args = line[1:].split()
            if cmd in ("quit", "exit"):
                break
            elif cmd == "help":
                print("/walk DX DY | /goto X Y | /warp LOCATION X Y | /face DIR | /players | /world | /quit")
            elif cmd == "walk" and len(args) == 2:
                await client.walk(int(args[0]), int(args[1]))
                print(f"now at tile {client.me.tile}")
            elif cmd == "goto" and len(args) == 2:
                await client.walk_to(int(args[0]), int(args[1]))
                print(f"now at tile {client.me.tile}")
            elif cmd == "warp" and len(args) == 3:
                intro = await client.warp(args[0], int(args[1]), int(args[2]))
                print(f"warped to {intro.display_name if intro else args[0]} (no confirmation)" if not intro
                      else f"warped to {intro.display_name}")
            elif cmd == "face" and len(args) == 1:
                client.face(int(args[0]))
            elif cmd == "players":
                for p in client.players.values():
                    print(f"  {'*' if p.is_me else ' '} {p}{' [host]' if p.is_host else ''}")
            elif cmd == "world":
                print(f"  {client.world}  ping={client.ping and round(client.ping * 1000)}ms")
            else:
                print("unknown command; /help")
        except StardewError as exc:
            print(f"error: {exc}")


async def main(args: argparse.Namespace) -> int:
    host, port = parse_address(args.address)
    client = StardewClient(host, port)
    attach_printers(client)

    print(f"connecting to {host}:{port} ...")
    try:
        await client.connect(timeout=args.timeout)
    except Exception as exc:  # noqa: BLE001 - report and exit
        print(f"connection failed: {exc}")
        return 1
    print(f"server: {client.server_name} (protocol {client.server_version}), {client.world}")
    print("available farmhands:")
    for i, fh in enumerate(client.farmhands):
        info = fh.info
        flags = []
        if not info.is_customized:
            flags.append("not customized")
        if fh.ambiguous:
            flags.append("ambiguous blob boundary")
        print(f"  [{i}] {info.name or '<unnamed>'}  id={info.unique_id}  home={info.home_location}"
              f"  last={info.disconnect_location or info.last_sleep_location}  tile={info.tile}"
              f"  money={info.money}{'  (' + ', '.join(flags) + ')' if flags else ''}")
    if args.list:
        await client.disconnect()
        return 0

    try:
        selector = args.farmhand
        if selector is not None and selector.isdigit() and int(selector) < len(client.farmhands):
            selector = int(selector)
        me = await client.join(selector, force=args.force)
    except JoinRejected as exc:
        print(f"join rejected: {exc}")
        await client.disconnect()
        return 2
    except StardewError as exc:
        print(f"join failed: {exc}")
        await client.disconnect()
        return 2
    print(f"joined as {me.name} (id {me.unique_id}) in {me.location} at tile {me.tile}; "
          f"host is {client.host_player.name if client.host_player else '?'}")

    try:
        if args.say:
            client.chat(args.say)
            print(f"[chat] {me.name}: {args.say}")
        if args.goto:
            await client.walk_to(*args.goto)
            print(f"walked to tile {me.tile}")
        if args.walk:
            await client.walk(*args.walk)
            print(f"walked to tile {me.tile}")
        if args.warp:
            name, x, y = args.warp.split(",")
            intro = await client.warp(name.strip(), int(x), int(y))
            print(f"warped to {intro.display_name if intro else name} (no confirmation)" if not intro
                  else f"warped to {intro.display_name}")
        if args.interactive:
            await interactive(client)
        elif args.listen:
            print(f"listening for {args.listen}s (ctrl-c to stop) ...")
            try:
                await asyncio.wait_for(client.wait_closed(), args.listen)
            except asyncio.TimeoutError:
                pass
    finally:
        if client.connected:
            print("disconnecting")
            await client.disconnect()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("address", help="host or host:port of the game (default port 24642)")
    p.add_argument("--farmhand", "-f", help="farmhand name, id or list index to join as (default: first)")
    p.add_argument("--list", "-l", action="store_true", help="only list farmhands, do not join")
    p.add_argument("--say", "-s", help="chat message to send after joining")
    p.add_argument("--walk", type=parse_pair, metavar="DX,DY", help="walk relative tiles after joining")
    p.add_argument("--goto", type=parse_pair, metavar="X,Y", help="walk to an absolute tile after joining")
    p.add_argument("--warp", metavar="LOCATION,X,Y", help="warp to a location and tile, e.g. Town,30,60")
    p.add_argument("--listen", type=float, default=0, metavar="SECONDS", help="stay connected and print events")
    p.add_argument("--interactive", "-i", action="store_true", help="read chat/commands from stdin")
    p.add_argument("--timeout", type=float, default=15.0, help="connect timeout in seconds")
    p.add_argument("--force", action="store_true", help="join even if the farmhand data boundary is ambiguous")
    p.add_argument("-v", "--verbose", action="count", default=0, help="-v for info, -vv for debug logging")
    return p


if __name__ == "__main__":
    ns = build_parser().parse_args()
    level = logging.WARNING - 10 * min(ns.verbose, 2)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        sys.exit(asyncio.run(main(ns)))
    except KeyboardInterrupt:
        print()
