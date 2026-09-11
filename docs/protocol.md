# Stardew Valley multiplayer protocol (PC, LAN/IP)

Everything below was verified against the decompiled 1.6.8 game source
([Dannode36/StardewValleyDecompiled](https://github.com/Dannode36/StardewValleyDecompiled)),
the Lidgren sources ([lidgren/lidgren-network-gen3](https://github.com/lidgren/lidgren-network-gen3))
and the capture `star.pcapng` of a 1.6.15 client joining a 1.6.15 host.
Byte offsets are hexadecimal, integers are little endian unless stated otherwise.

The stack has three layers:

| Layer | Implemented in | Job |
|---|---|---|
| Lidgren.Network gen3 over UDP (port 24642) | `sdvclient/lidgren.py` | discovery, handshake, reliability, ordering, fragmentation, keep-alive |
| Stardew message envelope (+ LZ4) | `sdvclient/protocol.py` | one `(type, farmerId, data)` record per game message |
| Netcode object sync | `sdvclient/netcode.py` | version vectors and field deltas for `Farmer`, `NetWorldState`, ... |

## 1. Lidgren transport

### 1.1 Message header

A UDP datagram holds one or more Lidgren messages back to back. Each one starts
with a 5 byte header:

```
byte    NetMessageType
byte    low  = (sequenceNumber << 1) | isFragment
byte    high = sequenceNumber >> 7
uint16  payload length in BITS
byte[]  payload   (ceil(bits / 8) bytes)
```

`NetMessageType` values:

| Value | Meaning |
|---|---|
| 0 | Unconnected (application data without a connection) |
| 1 | UserUnreliable |
| 2..33 | UserSequenced channel 0..31 |
| 34 | UserReliableUnordered |
| 35..66 | UserReliableSequenced channel 0..31 |
| 67..98 | UserReliableOrdered channel 0..31  (**Stardew only uses 67**) |
| 128 | LibraryError |
| 129 | Ping |
| 130 | Pong |
| 131 | Connect |
| 132 | ConnectResponse |
| 133 | ConnectionEstablished |
| 134 | Acknowledge |
| 135 | Disconnect |
| 136 | Discovery |
| 137 | DiscoveryResponse |
| 138..143 | NAT punch-through (unused) |
| 140 | ExpandMTURequest |
| 141 | ExpandMTUSuccess |

Library messages (>= 128) carry sequence number 0 and are never fragmented.
Sequence numbers live in `[0, 1024)`; the send/receive window is 64 messages.

Lidgren strings are a 7-bit variable-length byte count followed by UTF-8, the
same encoding .NET's `BinaryWriter.Write(string)` uses.

### 1.2 Session setup

The Stardew server configures Lidgren with app identifier `"StardewValley"`,
MTU 1200, ping interval 5 s and connection timeout 30 s. A client session looks
like this (all examples are real bytes from `star.pcapng`):

```
C->S  Discovery              88 0000 0000
S->C  DiscoveryResponse      89 0000 a800  06 "1.6.15"  0d "StardewValley"
C->S  Connect                83 0000 d000  0d "StardewValley"  <int64 clientUniqueId>  <float time>
S->C  ConnectResponse        84 0000 d000  0d "StardewValley"  <int64 serverUniqueId>  <float time>
C->S  ConnectionEstablished  85 0000 2000  <float time>
C<>S  Ping / Pong            81 0000 0800 <byte n>      82 0000 2800 <byte n> <float time>
```

* `DiscoveryResponse` payload = `Multiplayer.protocolVersion` (the game version,
  e.g. `1.6.15`) then `"StardewValley"`. The real client refuses to connect if
  the version differs from its own; this client only records it.
* `Connect` = app identifier, the client's random 64-bit unique id and
  `NetTime.Now` as a float (only used for clock offset estimation).
* The server has `ConnectionApproval` enabled and approves when IP connections
  are allowed (`Game1.options.ipConnectionsEnabled`), otherwise it answers with
  `Disconnect`.
* Each side pings every 5 s and answers pings with pongs. A side that hears
  nothing for 30 s drops the connection with the reason `Connection timed out`.
* `Disconnect` carries a reason string (`""` on a normal leave, `"KICKED"` on a kick).

### 1.3 Reliable ordered delivery (type 67)

Every received message of type 34..98 must be acknowledged. Acks are batched
into one `Acknowledge` message, 3 bytes per ack:

```
86 0000 c000  43 0000  43 0100  43 0200 ... 43 0700     <- acks for seq 0..7 of type 0x43
              ^type ^seq (uint16, NOT shifted like the header)
```

The receiver delivers type 67 messages strictly in sequence order, withholding
early ones (up to 64 ahead) and dropping duplicates. The sender keeps unacked
messages and resends them after `25 ms + 2.1 x RTT` (RTT defaults to 100 ms).

### 1.4 Fragmentation

If `5 + len(payload) > MTU` the payload is split. Every fragment is a normal
reliable-ordered message (own sequence number, own ack) whose payload starts
with four Lidgren varuints:

```
varuint group          (per sender, starts at 1)
varuint totalBits      (size of the whole message in bits)
varuint chunkByteSize  (size of every chunk except the last)
varuint chunkNumber    (0-based)
byte[]  chunk
```

Capture example, first fragment of an 8926 byte message:

```
43 01 00 48 25 | 07 f0ad04 a209 00 | <1186 bytes>
^0x43 seq=0 frag=1, 0x2548 bits = 1193 bytes
                 group=7 totalBits=71408 chunk=1186 number=0
```

Chunk size follows `NetFragmentationHelper.GetBestChunkSize`; for MTU 1200 it
is 1186 or 1187 bytes (`best_chunk_size()` reproduces it exactly).

## 2. Stardew message envelope

Each Lidgren data payload contains one or more game messages
(`LidgrenMessageUtils.ReadStreamToMessage`), serialised with `BinaryWriter`:

```
byte    messageType
int64   farmerId          UniqueMultiplayerID of the sending farmer (host id for server messages)
uint32  dataLength
byte[]  data              messageType-specific arguments
```

Messages whose raw size is >= 1024 bytes are LZ4 (block format, `LZ4_compress_default`)
compressed and sent as:

```
byte    0x7F              Multiplayer.compressed
int32   compressedSize
int32   decompressedSize
byte[]  LZ4 block         decompresses to exactly one envelope as above
```

Clients may send uncompressed messages of any size; the server only
decompresses when the first byte is `0x7F`.

### 2.1 Message types (`StardewValley.Multiplayer`)

| # | Name | Direction | Data |
|---|---|---|---|
| 0 | farmerDelta | both | `int64 farmerId` + root delta (section 3.3) |
| 1 | serverIntroduction | S->C | host farmer connection packet + `FarmerTeam` packet + `NetWorldState` packet |
| 2 | playerIntroduction | both | C->S: farmer connection packet. S->C: `string userName` + farmer connection packet |
| 3 | locationIntroduction | S->C | `bool forceCurrent` + `GameLocation` connection packet |
| 4 | forceEvent | both | `string eventId, bool useLocalFarmer, int32 x, int32 y, byte isStructure, string location` |
| 5 | warpFarmer | C->S | `int16 tileX, int16 tileY, string locationName, byte isStructure` |
| 6 | locationDelta | both | `byte isStructure, string locationName` + root delta |
| 7 | locationSprites | both | location + `int32 count` + sprites |
| 8 | characterWarp | S->C | NPC ref + location + `Vector2` |
| 9 | availableFarmhands | S->C | `int32 year, int32 season, int32 dayOfMonth, byte count`, then `count` x `NetRef<Farmer>.WriteFull` |
| 10 | chatMessage | both | `int64 recipient (0 = everyone), int16 language (0 = en), string text` |
| 11 | connectionMessage | S->C | `string translationKey` e.g. `Strings\UI:Client_WaitForHostLoad` |
| 12 | worldDelta | both | `NetWorldState` root delta |
| 13 | teamDelta | both | `FarmerTeam` root delta |
| 14 | newDaySync | both | new-day handshake |
| 15 | chatInfoMessage | both | `string key, byte argc, string[argc]` -> `Strings\UI:Chat_<key>` |
| 16 | userNameUpdate | S->C | `int64 farmerId, string userName` |
| 17 | farmerGainExperience | both | |
| 18 | serverToClientsMessage | S->C | `string` (`festivalEvent`, `endFest`, `trainApproach`) |
| 19 | disconnecting | both | empty; sent before leaving |
| 20..32 | achievements, mail, kick (23), nut dig, passout, ready sync, chest hit | | see `Multiplayer.processIncomingMessage` |
| 127 | compressed | | marker byte of a compressed envelope |

The server re-broadcasts client messages of type 0, 2, 4, 6, 7, 12, 13, 14, 15,
19, 20, 21, 22, 24, 26 to the other clients (`isClientBroadcastType`), and
chat (10) to its recipient(s).

### 2.2 Join flow

```
S->C  9  availableFarmhands      (or 11 connectionMessage while the host is busy)
C->S  2  playerIntroduction      farmerId = chosen farmhand's UniqueMultiplayerID
S->C  3  locationIntroduction    always-active locations (Farm, FarmHouse, ...) and
                                 the farmhand's last location with forceCurrent = 1
S->C  1  serverIntroduction      host farmer, team, world state  => we are in
S->C  2  playerIntroduction      one per other connected farmhand
S->C  0/6/12/13 ...              deltas from now on
```

If the request is rejected (farmhand in use, not customized while
`enableFarmhandCreation` is off, cabin unavailable) the server simply sends a
new type 9 list instead of type 1.

`availableFarmhands` writes each farmhand with `NetRef<Farmer>.WriteFull`:

```
NetVersion reassigned      byte count + uint32[count]      (usually 00)
int32      xmlLength
byte[]     xml             <?xml version="1.0" encoding="utf-8"?><Farmer ...>...</Farmer>
byte[]     netFieldsFull   every Farmer net field, undelimited (needs the full schema to parse)
```

The client does not need to understand the binary part: it re-sends the exact
blob in its `playerIntroduction`, wrapped as a connection packet:

```
byte       peerId          1
NetVersion version         02 00000000 00000000
byte[]     blob            the farmhand bytes from message 9, verbatim
```

`Farmer` XML is `SaveGame.farmerSerializer` output; useful elements are `name`,
`UniqueMultiplayerID`, `farmName`, `homeLocation`, `isCustomized`, `userID`,
`Position/X|Y`, `FacingDirection`, `money`, `lastSleepLocation`,
`disconnectLocation`, `disconnectDay`, `gameVersion`. Beware: the binary part
can contain nested XML documents of other types.

## 3. Netcode

### 3.1 Primitives

| Type | Delta / full encoding |
|---|---|
| NetBool | byte |
| NetByte | byte |
| NetInt, NetDirection, NetIntDelta | int32 |
| NetLong | int64 |
| NetFloat, NetRotation | float |
| NetDouble | double |
| NetEnum<T> | int16 |
| NetString | bool hasValue, then string |
| NetColor | uint32 packed RGBA |
| NetPoint | int32 x, int32 y |
| NetVector2 | float x, float y |
| NetRectangle | int32 x, y, w, h |
| NetGuid | 16 bytes |
| NetEvent0 | int32 counter |
| NetEvent1Field<T> / NetEvent1 | varuint count, then per event `uint32 delay` + argument |
| NetFields (a nested object) | BitArray of dirty fields, then each dirty field's delta |
| NetRef<T> delta | `byte deltaType` (0 child, 1 reassigned) + `uint32 length` + body  (**skippable**) |
| NetRef<T> full | NetVersion reassigned + (XML `int32 len + bytes` if a serializer is set, else type name string) + `T.NetFields.WriteFull` |
| NetHashSet<T> delta | varuint count, then `bool removal` + value |
| NetList<T> delta | int32 count, then the backing NetArray as a NetRef delta |
| NetArray<T> delta | BitArray + element deltas; full: int32 size + element fulls |
| NetDictionary delta | varuint changes (`byte removal, key, NetVersion, [value full]`), varuint updates (`key, NetVersion, skippable delta`) |

BitArray = 7-bit encoded length + bytes, bit `i` is bit `i % 8` of byte `i / 8`.

`NetVersion` is a vector clock: `byte count` + `uint32[count]`. Entry `i`
belongs to peer `i`; the server is peer 0 in roots it owns, a client is peer 0
in its own farmer root and the server is peer 1 there.

### 3.2 Connection packet (full state of a root)

`NetRoot<T>.CreateConnectionPacket`:

```
byte       peerId          id the receiver gets in the sender's clock
NetVersion version         the sender's clock
NetRef<T>.WriteFull        (see above)
```

Capture: host farmer in message 1 = `01 | 02 6f540100 00000000 | 01 00000000 | be6d0000 <xml> <net fields>`.
On 1.6.15 servers `GameLocation` packets contain one extra `00` between the
version and the reassigned vector (`00 01 02 0..0 00 01 00000000 12 "StardewValley.Farm" ...`);
the parser tolerates both layouts.

### 3.3 Root delta (`NetRoot<T>.Write`)

```
NetVersion version         sender's clock (v[0] must increase per delta)
byte       deltaType       0 = ChildDelta
uint32     length
BitArray   dirty           one bit per net field of T
...        field deltas    in declaration order
```

Capture, message 12 (`worldDelta`): `02 f4540100 00000000 | 00 | 0c000000 | 38 00100000000000 | 6c070000`
= 56 fields, only bit 12 (`timeOfDay`) set, value 1900 (7:00 pm).

Capture, message 0 (`farmerDelta`) sent by the joining client:

```
36afc82b698a35a5                 farmer id
02 01000000 00000000             version [1, 0]
00 17010000                      ChildDelta, 279 bytes
9e01 0a00...800200               158 fields; dirty 1,3,52,74,143,145
03 05 0000104400001844 00        field 1 position.NetFields: bits {Field, moving}; (576, 608); moving = false
05000000                         field 3 speed = 5
01                               field 52 isInBed = true
d043560100000000                 field 74 millisecondsPlayed
...                              fields 143 (buffs), 145 (companions)
```

A field is only accepted by the receiver when the delta's version has priority
over the field's last change (`NetVersion.IsPriorityOver`, compared entry by
entry from index 0), so a client must bump `v[0]` for every delta it sends.
`NetFields.Read` throws when the BitArray length differs from the receiver's
field count, so the count must match the server's game version exactly
(158 on 1.6.15, 157 in the 1.6.8 decompile). The client learns the count from
the first farmer delta it receives.

### 3.4 Farmer net fields (declaration order)

`Character.initNetFields` (0..20) then `Farmer.initNetFields` (21..). Indices
verified on 1.6.15 up to 145:

| # | Field | Type |
|---|---|---|
| 0 | sprite | NetRef\<AnimatedSprite\> |
| 1 | position.NetFields | NetPosition = [Field: NetVector2, pauseEvent: NetEvent1Field\<bool\>, moving: NetBool] |
| 2 | facingDirection | NetDirection (int32; 0 up, 1 right, 2 down, 3 left) |
| 3 | netSpeed | NetInt |
| 4 | netAddedSpeed | NetFloat |
| 5 | name | NetString |
| 6 | scale | NetFloat |
| 7 | currentLocationRef.NetFields | NetLocationRef = [locationName: NetString, isStructure: NetBool] |
| 8..12 | swimming, collidesWithOtherCharacters, facingDirectionBeforeSpeakingToPlayer, faceTowardFarmerRadius, faceAwayFromFarmer | bool, bool, int, int, bool |
| 13 | whoToFace.NetFields | NetFarmerRef = [defined: NetBool, uid: NetLong] |
| 14 | faceTowardFarmerEvent | NetEvent1Field\<int\> |
| 15..19 | _willDestroyObjectsUnderfoot, forceOneTileWide, simpleNonVillagerNPC, hideFromAnimalSocialMenu, netEventActor | NetBool |
| 20 | modData | NetStringDictionary\<string, NetString\> |
| 21 | uniqueMultiplayerID | NetLong |
| 22..24 | userID, platformType, platformID | NetString |
| 25 | hasMenuOpen | NetBool |
| 26 | farmerRenderer | NetRef |
| 27 | netGender | NetEnum |
| 28..38 | bathingClothes, shirt, pants, hair, skin, shoes, accessory, facialHair, hairstyleColor, pantsColor, newEyeColor | bool, str, str, int, int, str, int, int, color, color, color |
| 39..49 | netItems, currentToolIndex, temporaryItem, cursorSlotItem, fireToolEvent, beginUsingToolEvent, endUsingToolEvent, hat, boots, leftRing, rightRing | ref, int, ref, ref, event0, event0, event0, ref, ref, ref, ref |
| 50..52 | hidden, usingTool, isInBed | NetBool |
| 53..56 | bobberStyle, caveChoice, houseUpgradeLevel, daysUntilHouseUpgrade | NetInt |
| 57 | netSpouse | NetString |
| 58..64 | mailReceived, mailForTomorrow, mailbox, triggerActionsRun, eventsSeen, locationsVisited, secretNotesSeen | string sets, mailbox is a NetStringList, secretNotesSeen an int set |
| 65 | netMount.NetFields | NetRef\<Horse\> |
| 66 | dancePartner.NetFields | [farmer: NetFarmerRef, villager: NetString] |
| 67..69 | divorceTonight, changeWalletTypeTonight, isCustomized | NetBool |
| 70..73 | homeLocation, farmName, favoriteThing, horseName | NetString |
| 74 | netMillisecondsPlayed | NetLong |
| 75.. | friendshipData, events, questLog, skills, ... buffs (143), trinketItems (144), companions (145), ... | see `Farmer.initNetFields` |

### 3.5 NetWorldState net fields

0 uniqueIDForThisGame (long), 1 serverPrivacy (enum), 2 whichFarm (int), 3 whichModFarm (string),
4 shuffleMineChests (bool), 5 minesDifficulty, 6 skullCavesDifficulty, 7 highestPlayerLimit,
8 currentPlayerLimit (int), **9 year (int), 10 season (enum: 0 spring .. 3 winter), 11 dayOfMonth (int),
12 timeOfDay (int, e.g. 1900), 13 daysPlayed (int)**, 14 visitsUntilY1Guarantee (int),
15 isPaused (bool), 16 isTimePaused (bool), 17 locationWeather (dictionary) ... 56 fields in total.

### 3.6 GameLocation net fields and the object/terrain layers

A `GameLocation` is sent whole in a `locationIntroduction` (message 3) and then
patched by `locationDelta` (message 6) messages. Both wrap the same
`NetRoot<GameLocation>`; on a farm the introduction is ~192 KB.

`GameLocation.initNetFields` declares **51 fields** on the 1.6.15 server (the
1.5 decompile has 38). The leading order is unchanged from 1.5 and is verified
against captured farm data:

| Index | Field | Type |
|---|---|---|
| 0..2 | mapPath, uniqueName, name | NetString |
| 3 | lightLevel | NetFloat |
| 4 | sharedLights | NetIntDictionary |
| 5..11 | isFarm, isOutdoors, isStructure, ignoreDebrisWeather, ignoreOutdoorLighting, ignoreLights, treatAsOutdoors | NetBool |
| 12 | warps | NetObjectList\<Warp\> |
| 13..14 | doors, interiorDoors | NetPointDictionary |
| 15 | waterColor | NetColor |
| **16** | **netObjects** | **NetVector2Dictionary\<Object\>** |
| 17 | projectiles | NetCollection |
| 18 | largeTerrainFeatures | NetCollection |
| **19** | **terrainFeatures** | **NetVector2Dictionary\<TerrainFeature\>** |
| 20 | characters | NetCollection\<NPC\> |
| 21 | debris | NetCollection |
| 22 | netAudio.NetFields | NetFields |
| ... | ... 33 resourceClumps, 34 furniture, ... modData | ... |

Field indices past 19 are shifted from the 1.5 order by the extra 1.6 fields and
are not all mapped. The two tile-keyed layers we decode - **16 netObjects** and
**19 terrainFeatures** - both sit *before* the `characters` collection, so they
can be read without decoding NPCs.

**Message 3 body:** `bool force_current`, `byte peerId`, `NetVersion`, then the
`NetRoot` value: a `NetVersion`, `string typeName` ("StardewValley.Farm"), and
the **full** field serialisation (each field written in order, *no* leading
dirty bitarray). 1.6.15 servers sometimes insert one extra `0x00` before the
value's version vector.

**Message 6 body:** `bool isStructure`, `string name`, `NetVersion`, `byte
deltaType` (0 = child delta), then a *skippable* body holding `bitarray[51]`
(dirty fields) followed by each dirty field's delta, in ascending index order.

**NetVector2Dictionary layout.** Every entry - both in the full write and inside
a delta's add list - is:

```
key: Vector2 (float32 x, float32 y)   version: NetVersion   refFlag: byte   typeName: string   <value net fields>
```

The concrete type name is repeated for every entry (576 `...Tree` strings for
576 trees), and values are **not length-prefixed**. Rather than re-implement the
full `Object`/`TerrainFeature` net graph, `sdvclient/location.py` finds each
entry by its embedded type name and walks *backwards* over `refFlag` and the
(variable-length) `NetVersion` to recover the tile key. Object subtype
(Stone/Twig/Chest/...) comes from the object's `name` NetString just after the
type name; a tree's species id is the first string after `...Tree`. On the test
farm this yields exactly 576 trees, 852 grass, 343 stone and 221 twig.

**locationDelta dictionaries.** A `NetDictionary` delta is `varint changeCount`
× `(byte removal, key, NetVersion, value?)` then `varint updateCount` × `(key,
NetVersion, skippable body)`. Removals and updates are fully decoded (a removal
drops the tile; an update leaves it in place); an addition carries a value we
cannot length-measure, so decoding stops after recording its tile. Resource
clumps (field 33) and furniture (34) are not decoded yet - they follow the
`characters` collection.

### 3.7 Farmer inventory (netItems, field 39)

`Farmer.netItems` is field 39, a `NetRef<Inventory>`; `Inventory` is a
`NetList<Item>` (12 backpack slots for a starter farmhand). Its delta rides a
message-0 farmer delta and nests as::

    NetRef child: skippable {
        bitarray(1) = [True]              # Inventory field 0 (the list) dirty
        int32 count                       # element count (12)
        NetRef child: skippable {         # the backing NetArray
            bitarray(15)                  # which slots changed
            per dirty slot:
                byte refDeltaType         # 0 modify existing item, 1 set new value
                skippable { payload }
        }
    }

A **set** (type 1) payload is `NetVersion`, the concrete type name
(`StardewValley.Object`), then the item's full serialisation. A plain Object is
`Item` header — `int32 specialVariable, int32 category, NetString name, int32
parentSheetIndex, bool hasBeenInInventory, NetString itemId`, `modData` — then
the Object fields (tileLocation, owner, `type`, flags, fragility, price,
edibility, **stack (int32)**, **quality (int32)**, …). Freshly added items carry
stack 0; the game grows the stack with **modify** (type 0) deltas whose item
field-delta sets field 11. The client builds new items from this skeleton to add
pickups to its own inventory (see `sdvclient/inventory.py`); every captured
field-39 delta round-trips byte-for-byte.

## 4. What the client sends

| Action | Message |
|---|---|
| join | 2 with the farmhand blob (section 2.2) |
| chat | 10: `int64 0, int16 0, string text` |
| move | 0 with fields 1 (position, moving), 2 (facing), 3 (speed); one delta per ~50 ms while walking |
| change map | 5 `warpFarmer`; the server answers with a 3 for the new location. Also a 0 with field 7 so other clients learn the location |
| give money | 13 `teamDelta` with the `FarmerTeam.money` field dirty (a `NetIntDelta`, so the int32 is the amount to **add**). Shared-wallet only; see below |
| leave | 19, then Lidgren `Disconnect ""` |

### 4.1 teamDelta / shared-wallet money (message 13)

`FarmerTeam` syncs like any other `NetRoot`: `NetVersion` + delta-type byte +
`skippable(bitarray + changed fields)`. On a shared-wallet host
(`useSeparateWallets = false`) the communal gold is the `money` field, a
`NetIntDelta` (int32 delta). `build_team_delta()` writes just that one field;
`give_money(n)` / `--give-money N` sends it.

On 1.6.15, verified live against the test host: `FarmerTeam` has **77** net
fields (`netcode.FARMER_TEAM_FIELD_COUNT`, the bitarray length - must match the
host or the delta is rejected, like the farmer delta) and `money` is field
**index 0** (`netcode.F_TEAM_MONEY`). The pin: a `teamDelta` captured while
buying grass starter (100g) at Pierre read `field_count=77 dirty=[0]
tail=9cffffff` - `0x9cffffff` = int32 `-100`, matching the 100g spend exactly.
The client also relearns the field count from any incoming `teamDelta`.

To re-pin on another game version, run `client.py --trace` and change money
at a **shop** (an immediate change, not the shipping bin, which only settles
overnight): `money` is the dirty index whose `tail` is exactly 4 bytes and
decodes to the gold delta. Some other team fields also change on join/shipping -
e.g. index 41 carries a player-keyed collection (its delta ends in an int64
farmer id), not money - so match on the 4-byte int32 payload, not just any
dirty bit.

Positions are pixels; a tile is 64 px. A farmer standing on tile `(tx, ty)` has
`Position = (tx * 64, ty * 64 + 16)` (this is what `GameServer.warpFarmer`
sets) and the tile under a farmer is `((x + 32) / 64, (y + 16) / 64)`.

## 5. Known gaps

* Location state (message 3/6) is decoded only for the object (16) and terrain
  (19) layers - the things scattered around the map - via `sdvclient/location.py`
  (see section 3.6). Resource clumps, furniture, buildings, the character
  collection and the binary part of farmer state are still not decoded; the
  client also keeps positions/names/locations of other farmers and the world
  clock. Team state (13) is decoded only far enough to add shared-wallet money
  (section 4.1); the rest of the `FarmerTeam` schema is undecoded.
* The new-day / ready-check handshake (14, 30, 31) is not answered, so a bot
  that is still connected when the host goes to bed will hold up the night
  until it is kicked or disconnects.
* Movement is not collision checked and no animations/tools are used.
* Farmhand list splitting relies on locating `<Farmer>` documents; with several
  farmhands whose reassigned version vectors differ in size the boundary can be
  ambiguous, which the client reports instead of guessing.
