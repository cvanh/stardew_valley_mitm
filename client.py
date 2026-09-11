#!/usr/bin/env python3
"""Command line front-end for sdvclient: join a Stardew Valley game, chat and walk.

Examples::

    python3 client.py 10.1.110.27:24642 --list
    python3 client.py 10.1.110.27:24642 --say "hello from python" --walk 3,0 --listen 30
    python3 client.py 10.1.110.27:24642 --farmhand dsf` --interactive

Interactive mode reads lines from stdin: plain text is sent as chat, and the
commands ``/walk X Y`` (tiles, relative), ``/goto X Y`` (tiles, absolute),
``/warp LOCATION X Y``, ``/face 0-3``, ``/follow [NAME]``, ``/unfollow``,
``/players``, ``/world``, ``/things [RADIUS]``, ``/clear [RADIUS]`` and ``/quit``
are understood.  ``/clear`` removes every object and terrain feature around us.
Commands may also be prefixed with ``.`` instead of ``/``.  Other players can
send the same commands in game chat (except ``/quit``); use the ``.`` prefix
there, since the game's chat box intercepts anything starting with ``/``.  The
result is whispered back to them.
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
            # print(f"[world] {world}")

    client.on_world_updated = on_world


def resolve_target(client: StardewClient, name: str | None):
    """Pick the player to follow: the one matching ``name``, else the only other player."""
    others = [p for p in client.players.values() if not p.is_me]
    if name:
        for p in others:
            if p.name.lower() == name.lower() or str(p.unique_id) == name:
                return p
        return None
    if not others:
        return None
    if len(others) > 1:
        print(f"[follow] {len(others)} other players; following {others[0].name} - pass a name to pick another")
    return others[0]


async def follow(client: StardewClient, name: str | None = None, *,
                 stop_distance: int = 1, poll: float = 0.3) -> None:
    """Walk after another player until they leave, we disconnect, or we are cancelled.

    Takes one axis-aligned tile step per iteration toward the target's current
    tile, re-reading its position (kept live by the server's farmer deltas)
    each time, and idles while within ``stop_distance`` tiles or in another
    location.
    """
    target = resolve_target(client, name)
    if target is None:
        print("[follow] no player to follow" + (f" named {name!r}" if name else ""))
        return
    print(f"[follow] following {target.name} (ctrl-c or /unfollow to stop)")
    here = target.location
    try:
        while client.joined:
            target = resolve_target(client, name or target.name)
            if target is None or target.unique_id not in client.players:
                print("[follow] target is gone")
                return
            me = client.me
            if me is None or target.tile is None:
                await asyncio.sleep(poll)
                continue
            # in another location: warp to them instead of walking there.
            # use a tiny timeout - this server sends no warp confirmation, so
            # waiting the default 15s would freeze the follow loop.
            if target.location and target.location != me.location:
                if target.location != here:
                    print(f"[follow] {target.name} moved to {target.location}, warping")
                    here = target.location
                await client.warp(target.location, *target.tile, timeout=0.1)
                await asyncio.sleep(poll)
                continue
            if me.tile is None:
                await asyncio.sleep(poll)
                continue
            (mx, my), (tx, ty) = me.tile, target.tile
            if abs(tx - mx) + abs(ty - my) <= stop_distance:
                await asyncio.sleep(poll)
                continue
            # one tile toward the target along the axis we are furthest off on
            if abs(tx - mx) >= abs(ty - my):
                await client.walk((tx > mx) - (tx < mx), 0)
            else:
                await client.walk(0, (ty > my) - (ty < my))
    except asyncio.CancelledError:
        print("[follow] stopped")
        raise


COMMAND_PREFIXES = ("/", ".")

HELP = ("/walk DX DY | /goto X Y | /warp LOCATION X Y | /face DIR | "
        "/follow [NAME] | /unfollow | /players | /world | /things [R] | "
        "/clear [R] | /quit  (prefix with . instead of / in game chat)")


class Session:
    """Shared command dispatcher for interactive mode.

    Commands arrive from two sources: lines typed on stdin and chat messages
    from other players that start with ``/``.  Both go through :meth:`run`;
    only ``reply`` differs (print locally vs. whisper back to the sender).
    """

    def __init__(self, client: StardewClient) -> None:
        self.client = client
        self.follow_task: asyncio.Task | None = None

    async def stop_follow(self) -> None:
        if self.follow_task is not None and not self.follow_task.done():
            self.follow_task.cancel()
            try:
                await self.follow_task
            except asyncio.CancelledError:
                pass
        self.follow_task = None

    async def run(self, line: str, reply, *, remote: bool = False) -> bool:
        """Execute one ``/command`` line; returns False when the session should end."""
        client = self.client
        cmd, *args = line[1:].split()
        try:
            if cmd in ("quit", "exit"):
                if remote:
                    reply("quit is only available locally")
                    return True
                return False
            elif cmd == "help":
                reply(HELP)
            elif cmd == "follow":
                await self.stop_follow()
                self.follow_task = asyncio.ensure_future(follow(client, args[0] if args else None))
                reply(f"following {args[0] if args else 'the nearest player'}")
            elif cmd == "unfollow":
                await self.stop_follow()
                reply("stopped following")
            elif cmd == "walk" and len(args) == 2:
                await self.stop_follow()
                await client.walk(int(args[0]), int(args[1]))
                reply(f"now at tile {client.me.tile}")
            elif cmd == "goto" and len(args) == 2:
                await self.stop_follow()
                await client.walk_to(int(args[0]), int(args[1]))
                reply(f"now at tile {client.me.tile}")
            elif cmd == "warp" and len(args) == 3:
                await self.stop_follow()
                intro = await client.warp(args[0], int(args[1]), int(args[2]))
                reply(f"warped to {intro.display_name}" if intro
                      else f"warped to {args[0]} (no confirmation)")
            elif cmd == "face" and len(args) == 1:
                client.face(int(args[0]))
                reply(f"facing {args[0]}")
            elif cmd == "players":
                for p in client.players.values():
                    reply(f"  {'*' if p.is_me else ' '} {p}{' [host]' if p.is_host else ''}")
            elif cmd == "world":
                reply(f"  {client.world}  ping={client.ping and round(client.ping * 1000)}ms")
            elif cmd == "things":
                if client.location is None or client.me is None or client.me.tile is None:
                    reply("  no map decoded yet")
                else:
                    radius = int(args[0]) if args else 5
                    reply(f"  {client.location}")
                    for thing in client.location.things_near(client.me.tile, radius):
                        reply(f"    {thing}")
            elif cmd == "clear":
                if client.location is None or client.me is None or client.me.tile is None:
                    reply("  no map decoded yet")
                else:
                    radius = int(args[0]) if args else 3
                    sent = await client.clear_area(client.me.tile, radius)
                    reply(f"  cleared {sent} thing(s) within {radius} tiles of {client.me.tile}")
            else:
                reply("unknown command; /help")
        except (StardewError, ValueError) as exc:
            reply(f"error: {exc}")
        return True


async def interactive(client: StardewClient) -> None:
    loop = asyncio.get_running_loop()
    print("interactive mode - type text to chat, /help for commands "
          "(other players can also send .commands in chat)")
    session = Session(client)
    # remote commands land here from the on_chat callback; stdin is polled lazily
    # (one readline in flight at a time) so quitting never leaves a reader thread
    # blocked on the terminal.
    queue: asyncio.Queue = asyncio.Queue()
    stdin_future: asyncio.Future | None = None

    def on_chat(message, sender) -> None:
        printer(message, sender)
        me = client.me
        if me is not None and message.sender_id == me.unique_id:
            return  # our own chat echoed back
        text = message.text.strip()
        if not text.startswith(COMMAND_PREFIXES):
            return
        name = sender.name if sender is not None and sender.name else str(message.sender_id)

        def reply(line: str) -> None:
            print(f"[cmd from {name}] {line}")
            try:
                client.chat(line.strip(), to=message.sender_id)
            except StardewError as exc:
                print(f"error replying to {name}: {exc}")

        print(f"[cmd from {name}] {text}")
        queue.put_nowait((text, reply, True))

    printer = client.on_chat
    client.on_chat = on_chat
    try:
        while client.joined:
            if stdin_future is None:
                stdin_future = loop.run_in_executor(None, sys.stdin.readline)
            queue_get = asyncio.ensure_future(queue.get())
            done, _ = await asyncio.wait({stdin_future, queue_get}, return_when=asyncio.FIRST_COMPLETED)
            if stdin_future in done:
                raw = stdin_future.result()
                stdin_future = None
                if not raw:
                    queue_get.cancel()
                    break  # EOF on stdin
                item = (raw.strip(), print, False)
                if queue_get in done:
                    queue.put_nowait(queue_get.result())  # keep the remote command for next round
                else:
                    queue_get.cancel()
            else:
                item = queue_get.result()
            line, reply, remote = item
            if not line:
                continue
            if not line.startswith(COMMAND_PREFIXES):
                if not remote:
                    try:
                        client.chat(line)
                    except StardewError as exc:
                        print(f"error: {exc}")
                continue
            if not await session.run(line, reply, remote=remote):
                break
    finally:
        client.on_chat = printer
        await session.stop_follow()


async def main(args: argparse.Namespace) -> int:
    host, port = parse_address(args.address)
    client = StardewClient(host, port)
    attach_printers(client)

    print(f"connecting to {host}:{port} ...")
    try:
        await client.connect(timeout=args.timeout)
    except Exception as exc:  # noqa: BLE001 - report and exit
        print(f"connection failed: {exc}")
        await client.disconnect()
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

    if not client.farmhands:
        print("=" * 70)
        print("!! CANNOT JOIN: the server offered no available farmhands.")
        print("   The most likely cause is that the farmhand is already in use -")
        print("   e.g. another bot from an earlier run is still connected and")
        print("   holding it, or you are logged into that farmhand yourself, or")
        print("   the host is sitting in a menu / the farm is full.")
        print("   Fixes: stop any running bot ('pkill -f client.py'), wait a few")
        print("   seconds for the server to drop it, or restart the host.")
        print("=" * 70)
        await client.disconnect()
        return 2

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
        elif args.follow is not None:
            name = args.follow or None
            print("following (ctrl-c to stop) ...")
            await follow(client, name)
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
    p.add_argument("--follow", nargs="?", const="", metavar="NAME",
                   help="follow another player (default: the only other player) until ctrl-c: "
                        "warp to their location when it differs, else walk toward them")
    p.add_argument("--listen", type=float, default=0, metavar="SECONDS", help="stay connected and print events")
    p.add_argument("--interactive", "-i", action="store_true", help="read chat/commands from stdin")
    p.add_argument("--timeout", type=float, default=15.0, help="connect timeout in seconds")
    p.add_argument("--force", action="store_true", help="join even if the farmhand data boundary is ambiguous")
    p.add_argument("-v", "--verbose", action="count", default=0, help="-v for info, -vv for debug logging")
    return p


if __name__ == "__main__":
    ns = build_parser().parse_args()
    level = logging.NOTSET - 10 * min(ns.verbose, 2)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        sys.exit(asyncio.run(main(ns)))
    except KeyboardInterrupt:
        print()
