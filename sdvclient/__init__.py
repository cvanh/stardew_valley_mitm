"""sdvclient - a small, dependency-free Stardew Valley multiplayer client.

Speaks the Lidgren.Network UDP transport used by the PC version of the game and
the Stardew Valley message envelope on top of it.  Enough is implemented to
discover a server, join as an existing farmhand, chat, and move around.

Typical use::

    import asyncio
    from sdvclient import StardewClient

    async def main():
        client = StardewClient("10.1.120.13", 24642)
        client.on_chat = lambda msg, sender: print(sender.name if sender else msg.sender_id, msg.text)
        await client.connect()
        me = await client.join()          # first available farmhand
        client.chat("hello from python")
        await client.walk_to(me.tile[0] + 3, me.tile[1])
        await client.disconnect()

    asyncio.run(main())
"""

from .client import (
    ChatMessage,
    JoinRejected,
    Player,
    StardewClient,
    StardewError,
    WorldState,
)
from .protocol import (
    ALL_PLAYERS,
    DEFAULT_PORT,
    Farmhand,
    FarmerInfo,
    GameMessage,
    MessageType,
    SEASONS,
)

__all__ = [
    "ALL_PLAYERS",
    "ChatMessage",
    "DEFAULT_PORT",
    "Farmhand",
    "FarmerInfo",
    "GameMessage",
    "JoinRejected",
    "MessageType",
    "Player",
    "SEASONS",
    "StardewClient",
    "StardewError",
    "WorldState",
]
