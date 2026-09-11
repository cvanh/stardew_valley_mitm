# Stardew Valley network client & protocol notes

Reverse engineering of the Stardew Valley (PC, 1.6.x) multiplayer protocol and a
small, dependency-free Python client that can join a game over IP, chat and walk.

* [docs/protocol.md](docs/protocol.md) - the protocol (Lidgren transport, Stardew
  message envelope, Netcode deltas) with examples from `star.pcapng`
* [notes.md](notes.md) - the original raw reverse engineering notes
* `sdvclient/` - the client library (Python 3.9+, standard library only)
* `client.py` - command line front-end for the library
* `tools/pcap_dump.py` - decode a capture into Lidgren and game messages (needs tshark)
* `mitm.py` - the earlier mitmproxy addon (`./mitmweb --mode reverse:udp://127.0.0.1:24642 -s ./mitm.py`)

## Client usage

```sh
# list the farmhands you can join as
python3 client.py 10.1.110.27:24642 --list

# join the first farmhand, say hello, walk 3 tiles right, print chat for 30 s, leave
python3 client.py 10.1.110.27:24642 --say "hello from python" --walk 3,0 --listen 30

# interactive: type to chat, /walk DX DY, /goto X Y, /warp Town 30 60, /players, /world, /quit
python3 client.py 10.1.110.27:24642 --farmhand NAME --interactive
# other players can send the same commands in game chat as .walk, .goto, ... (the game eats /);
# /quit is local only; replies are whispered back
```

As a library:

```python
import asyncio
from sdvclient import StardewClient

async def main():
    client = StardewClient("10.1.110.27", 24642)
    client.on_chat = lambda msg, sender: print(sender.name if sender else msg.sender_id, msg.text)
    await client.connect()                  # discovery + handshake + farmhand list
    print(client.server_version, [f.name for f in client.farmhands])
    me = await client.join()                # or join("name"), join(index)
    client.chat("hello")
    await client.walk_to(me.tile[0] + 3, me.tile[1])
    await client.warp("Town", 30, 60)
    print(client.world, client.players)
    await client.disconnect()

asyncio.run(main())
```

`StardewClient` exposes `server_version`, `farmhands`, `me`, `host_player`,
`players` (positions/locations of everyone, updated from farmer deltas),
`world` (year/season/day/time) and callbacks `on_chat`, `on_chat_info`,
`on_player_joined/left/updated`, `on_world_updated`, `on_location`,
`on_connection_message`, `on_message` (raw) and `on_disconnected`.
`send_raw(type, data)` sends any other game message.

Limitations (see the docs): joins only as an *existing* farmhand, does not
answer the new-day/ready handshake (leave before the host sleeps), no collision
checks, location/team state is not decoded.

## Tests and tools

```sh
python3 -m unittest tests.test_sdvclient -v
python3 tools/pcap_dump.py star.pcapng --quiet-lib          # decode the capture
python3 tools/pcap_dump.py star.pcapng --out /tmp/msgs       # also dump message bodies
```
