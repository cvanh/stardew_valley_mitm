# notes



## udp packet
each packet is goes to port `24642` whith udp and tcp?

a packet is [1408 bytes](https://github.com/lidgren/lidgren-network-gen3/blob/master/Lidgren.Network/NetPeerConfiguration.cs#L36C12-L36C16)

PER MESSAGE:
```
7 bits - NetMessageType note: the code specifies 8 bits
1 bit - Is a message fragment?

[8 bits NetMessageLibraryType, if NetMessageType == Library]

[16 bits sequence number, if NetMessageType >= UserSequenced] note: it seems in the code that this could be 15 bits

8/16 bits - Payload length in bits (variable size ushort) note: the codes specifies 16 bits

[16 bits fragments group id, if fragmented]
[16 bits fragments total count, if fragmented]
[16 bits fragment number, if fragmented]

[x - Payload] if length > 0
```

### NetIncomingMessagetype

```
Error = 0,
StatusChanged = 1 << 0,			// Data (string), 1
UnconnectedData = 1 << 1,		// Data	Based on data received, 2
ConnectionApproval = 1 << 2,	// Data, 4
Data = 1 << 3,                  // Data	Based on data received, 0x83, 10000011 when fragmented
Receipt = 1 << 4,               // Data, 0x86, 10000110 when not fragmented
DiscoveryRequest = 1 << 5,      // (no data), 0x88, 100100 when not fragement
DiscoveryResponse = 1 << 6,		// Data
VerboseDebugMessage = 1 << 7,	// Data (string)
DebugMessage = 1 << 8,			// Data (string)
WarningMessage = 1 << 9,		// Data (string)
ErrorMessage = 1 << 10,			// Data (string)
NatIntroductionSuccess = 1 << 11, // Data (as passed to master server)
ConnectionLatencyUpdated = 1 << 12, // Seconds as a Single
```

## NetMessageType
you can calulate the value of netincomming type of you know the type and if it is a fragmented message.
7 bits incommingmessagetype + 1 bit isfragmented
```
Unconnected = 0,
UserUnreliable = 1,
UserSequenced1 = 2,
UserSequenced2 = 3,
UserSequenced3 = 4,
UserSequenced4 = 5,
UserSequenced5 = 6,
UserSequenced6 = 7,
UserSequenced7 = 8,
UserSequenced8 = 9,
UserSequenced9 = 10,
UserSequenced10 = 11,
UserSequenced11 = 12,
UserSequenced12 = 13,
UserSequenced13 = 14,
UserSequenced14 = 15,
UserSequenced15 = 16,
UserSequenced16 = 17,
UserSequenced17 = 18,
UserSequenced18 = 19,
UserSequenced19 = 20,
UserSequenced20 = 21,
UserSequenced21 = 22,
UserSequenced22 = 23,
UserSequenced23 = 24,
UserSequenced24 = 25,
UserSequenced25 = 26,
UserSequenced26 = 27,
UserSequenced27 = 28,
UserSequenced28 = 29,
UserSequenced29 = 30,
UserSequenced30 = 31,
UserSequenced31 = 32,
UserSequenced32 = 33,
UserReliableUnordered = 34,
UserReliableSequenced1 = 35,
UserReliableSequenced2 = 36,
UserReliableSequenced3 = 37,
UserReliableSequenced4 = 38,
UserReliableSequenced5 = 39,
UserReliableSequenced6 = 40,
UserReliableSequenced7 = 41,
UserReliableSequenced8 = 42,
UserReliableSequenced9 = 43,
UserReliableSequenced10 = 44,
UserReliableSequenced11 = 45,
UserReliableSequenced12 = 46,
UserReliableSequenced13 = 47,
UserReliableSequenced14 = 48,
UserReliableSequenced15 = 49,
UserReliableSequenced16 = 50,
UserReliableSequenced17 = 51,
UserReliableSequenced18 = 52,
UserReliableSequenced19 = 53,
UserReliableSequenced20 = 54,
UserReliableSequenced21 = 55,
UserReliableSequenced22 = 56,
UserReliableSequenced23 = 57,
UserReliableSequenced24 = 58,
UserReliableSequenced25 = 59,
UserReliableSequenced26 = 60,
UserReliableSequenced27 = 61,
UserReliableSequenced28 = 62,
UserReliableSequenced29 = 63,
UserReliableSequenced30 = 64,
UserReliableSequenced31 = 65,
UserReliableSequenced32 = 66,
UserReliableOrdered1 = 67,
UserReliableOrdered2 = 68,
UserReliableOrdered3 = 69,
UserReliableOrdered4 = 70,
UserReliableOrdered5 = 71,
UserReliableOrdered6 = 72,
UserReliableOrdered7 = 73,
UserReliableOrdered8 = 74,
UserReliableOrdered9 = 75,
UserReliableOrdered10 = 76,
UserReliableOrdered11 = 77,
UserReliableOrdered12 = 78,
UserReliableOrdered13 = 79,
UserReliableOrdered14 = 80,
UserReliableOrdered15 = 81,
UserReliableOrdered16 = 82,
UserReliableOrdered17 = 83,
UserReliableOrdered18 = 84,
UserReliableOrdered19 = 85,
UserReliableOrdered20 = 86,
UserReliableOrdered21 = 87,
UserReliableOrdered22 = 88,
UserReliableOrdered23 = 89,
UserReliableOrdered24 = 90,
UserReliableOrdered25 = 91,
UserReliableOrdered26 = 92,
UserReliableOrdered27 = 93,
UserReliableOrdered28 = 94,
UserReliableOrdered29 = 95,
UserReliableOrdered30 = 96,
UserReliableOrdered31 = 97,
UserReliableOrdered32 = 98,
Unused1 = 99,
Unused2 = 100,
Unused3 = 101,
Unused4 = 102,
Unused5 = 103,
Unused6 = 104,
Unused7 = 105,
Unused8 = 106,
Unused9 = 107,
Unused10 = 108,
Unused11 = 109,
Unused12 = 110,
Unused13 = 111,
Unused14 = 112,
Unused15 = 113,
Unused16 = 114,
Unused17 = 115,
Unused18 = 116,
Unused19 = 117,
Unused20 = 118,
Unused21 = 119,
Unused22 = 120,
Unused23 = 121,
Unused24 = 122,
Unused25 = 123,
Unused26 = 124,
Unused27 = 125,
Unused28 = 126,
Unused29 = 127,
LibraryError = 128,
Ping = 129, // used for RTT calculation
Pong = 130, // used for RTT calculation
Connect = 131,
ConnectResponse = 132, // used for asking handshakes?
ConnectionEstablished = 133,
Acknowledge = 134,
Disconnect = 135,
Discovery = 136,
DiscoveryResponse = 137,
NatPunchMessage = 138, // send between peers
NatIntroduction = 139, // send to master server
NatIntroductionConfirmRequest = 142,
NatIntroductionConfirmed = 143,
ExpandMTURequest = 140,
ExpandMTUSuccess = 141,
```

## example packet
unfragmented packet used to communicate which game lidgren is running for. The len is 0x000d which is 13 chars
```
       1  2  3  3  4  4  begin packet
0000   84 00 00 d0 00 0d 53 74 61 72 64 65 77 56 61 6c   ......StardewVal
             end                           5? 6? 6? 
0010   6c 65 79 34 c4 c5 e0 92 79 a9 fe 98 fe 80 44      ley4....y.....D
```


first (fragmented?) message from stardew valley??? maybe receiveServerIntroduction(). the len is 0x4825 which is 7237 chars 
```
       1  2  3  3  4  4    
0000   43 01 00 48 25 06 f8 ab 04 a2 09 00 7f b6 22 00   C..H%.........".

             9  9  8  8  7  7
0010   00 a8 72 00 00 f2 00 09 ef 54 e8 a0 f1 fb 93 db   ..r......T......
0020   9b 72 00 00 01 00 04 00 10 02 08 00 42 02 c1 e5   .r..........B...

                               bgn data
0030   00 01 00 f5 58 55 00 00 3c 3f 78 6d 6c 20 76 65   ....XU..<?xml ve
0040   72 73 69 6f 6e 3d 22 31 2e 30 22 20 65 6e 63 6f   rsion="1.0" enco
0050   64 69 6e 67 3d 22 75 74 66 2d 38 22 3f 3e 0a 3c   ding="utf-8"?>.<
0060   46 61 72 6d 65 72 20 78 6d 6c 6e 73 3a 78 73 69   Farmer xmlns:xsi
0070   3d 22 68 74 74 70 3a 2f 2f 77 77 77 2e 77 33 2e   ="http://www.w3.
0080   6f 72 67 2f 32 30 30 31 2f 58 4d 4c 53 63 68 65   org/2001/XMLSche
0090   6d 61 2d 69 6e 73 74 61 6e 63 65 22 36 00 1f 64   ma-instance"6..d
00a0   36 00 0f f1 02 22 3e 0a 20 20 3c 6e 61 6d 65 3e   6....">.  <name>
00b0   64 73 66 60 3c 2f 0b 00 00 14 00 fd 09 66 6f 72   dsf`</.......for
00c0   63 65 4f 6e 65 54 69 6c 65 57 69 64 65 3e 66 61   ceOneTileWide>fa
00d0   6c 73 65 3c 2f 18 00 00 2d 00 94 69 73 45 6d 6f   lse</...-..isEmo
00e0   74 69 6e 67 26 00 06 11 00 02 1f 00 59 43 68 61   ting&.......YCha
00f0   72 67 20 00 05 12 00 02 21 00 49 47 6c 6f 77 20   rg .....!.IGlow 
0100   00 04 11 00 00 1f 00 d4 63 6f 6c 6f 72 65 64 42   ........coloredB
0110   6f 72 64 65 72 63 00 0a 15 00 00 27 00 44 66 6c   orderc.....'.Dfl
0120   69 70 1e 00 01 0c 00 00 15 00 85 64 72 61 77 4f   ip.........drawO
0130   6e 54 6f 1a 00 06 11 00 00 1f 00 a2 66 61 63 65   nTo.........face
0140   54 6f 77 61 72 64 73 01 05 40 00 0c 18 00 00 2d   Towards..@.....-
0150   00 f4 08 69 67 6e 6f 72 65 4d 6f 76 65 6d 65 6e   ...ignoreMovemen
0160   74 41 6e 69 6d 61 74 69 6f 6e 34 00 0f 1f 00 05   tAnimation4.....
0170   00 3b 00 00 68 00 8e 41 77 61 79 46 72 6f 6d 6a   .;..h..AwayFromj
0180   00 0b 1a 00 00 31 00 41 73 63 61 6c 5d 01 01 d9   .....1.Ascal]...
0190   00 50 6f 61 74 3e 31 d6 00 00 09 00 00 1f 00 15   .Poat>1.........
01a0   2f 20 00 22 3c 67 3b 01 ff 01 54 72 61 6e 73 70   / ."<g;...Transp
01b0   61 72 65 6e 63 79 3e 30 3c 2f 17 00 01 00 3a 00   arency>0</....:.
01c0   00 18 00 44 52 61 74 65 24 00 01 0c 00 00 19 00   ...DRate$.......
01d0   30 47 65 6e 5f 01 63 4d 61 6c 65 3c 2f 0d 00 00   0Gen_.cMale</...
01e0   18 00 f0 04 77 69 6c 6c 44 65 73 74 72 6f 79 4f   ....willDestroyO
01f0   62 6a 65 63 74 73 55 29 00 bf 66 6f 6f 74 3e 74   bjectsU)..foot>t
0200   72 75 65 3c 2f 22 00 09 00 42 00 41 50 6f 73 69   rue</"...B.APosi
0210   29 01 02 cf 00 80 58 3e 35 37 36 3c 2f 58 7c 02   ).....X>576</X|.
0220   b0 20 20 3c 59 3e 36 30 38 3c 2f 59 0f 00 28 3c   .  <Y>608</Y..(<
0230   2f 2c 00 a2 3c 53 70 65 65 64 3e 35 3c 2f 09 00   /,..<Speed>5</..
0240   00 4c 00 b1 46 61 63 69 6e 67 44 69 72 65 63 53   .L..FacingDirecS
0250   00 3c 31 3c 2f 13 00 00 27 00 1c 49 92 02 06 11   .<1</...'..I....
0260   00 00 1f 00 70 43 75 72 72 65 6e 74 b6 02 69 65   ....pCurrent..ie
0270   3e 32 34 3c 2f 11 00 00 22 00 11 53 80 01 32 31   >24</..."..S..21
0280   3c 2f 09 00 00 13 00 91 6d 6f 64 44 61 74 61 20   </......modData 
0290   2f aa 00 71 71 75 65 73 74 4c 6f 50 00 40 20 20   /..qquestLoP.@  
02a0   3c 51 0f 00 f1 05 20 78 73 69 3a 74 79 70 65 3d   <Q.... xsi:type=
02b0   22 53 6f 63 69 61 6c 69 7a 65 19 00 01 68 03 00   "Socialize...h..
02c0   02 00 32 3c 5f 63 7b 00 02 4b 01 32 69 76 65 4f   ..2<_c{..K.2iveO
02d0   00 00 02 00 21 3c 5f 54 00 70 44 65 73 63 72 69   ....!<_T.pDescri
02e0   70 de 00 0d 1c 00 48 54 69 74 6c 32 00 20 72 65   p.....HTitl2. re
02f0   bb 02 07 32 00 5e 3e 2d 31 3c 2f 16 00 01 79 01   ...2.^>-1</...y.
0300   b4 20 20 3c 61 63 63 65 70 74 65 64 b3 02 05 10   .  <accepted....
0310   00 04 21 00 67 63 6f 6d 70 6c 65 22 00 06 11 00   ..!.gcomple"....
0320   04 23 00 51 64 61 69 6c 79 d6 00 04 46 00 07 12   .#.Qdaily...F...
0330   00 04 25 00 73 73 68 6f 77 4e 65 77 21 02 04 0e   ..%.sshowNew!...
0340   00 04 1e 00 60 63 61 6e 42 65 43 ae 04 43 6c 6c   ....`canBeC..Cll
0350   65 64 25 00 0b 15 00 04 2c 00 12 64 7b 02 05 6c   ed%.....,..d{..l
0360   00 03 0f 00 04 1f 00 76 69 64 3e 39 3c 2f 69 30   .......vid>9</i0
0370   00 61 6d 6f 6e 65 79 52 18 01 00 e3 02 08 0f 00   .amoneyR........
0380   04 34 00 01 67 01 40 54 79 70 65 5b 02 06 0d 00   .4..g.@Type[....
0390   04 1f 00 80 64 61 79 73 4c 65 66 74 3f 00 05 0c   ....daysLeft?...
03a0   00 07 1d 00 01 fc 00 14 41 4a 01 00 71 01 0d 15   ........AJ..q...
03b0   00 04 2e 00 41 6e 65 78 74 2f 00 10 73 34 02 02   ....Anext/..s4..
03c0   02 00 90 3c 69 6e 74 3e 32 35 3c 2f 08 00 04 29   ...<int>25</...)
03d0   00 1e 2f 2a 00 0a 70 02 00 02 00 12 3c ac 00 00   ../*..p.....<...
03e0   04 02 81 3e 49 6e 74 72 6f 64 75 05 03 14 73 c6   ...>Introdu...s.
03f0   00 01 1a 00 04 53 00 95 77 68 6f 54 6f 47 72 65   .....S..whoToGre
0400   65 66 00 60 20 20 3c 73 74 72 67 05 93 41 62 69   ef.`  <strg..Abi
0410   67 61 69 6c 3c 2f 10 00 03 34 00 06 21 00 8f 43   gail</...4..!..C
0420   61 72 6f 6c 69 6e 65 22 00 08 4f 6c 69 6e 74 1f   aroline"..Olint.
0430   00 07 9f 44 65 6d 65 74 72 69 75 73 23 00 07 5f   ...Demetrius#.._
0440   57 69 6c 6c 79 1f 00 07 6f 45 6c 6c 69 6f 74 63   Willy...oElliotc
0450   00 08 3f 45 6d 69 40 00 0a 5f 76 65 6c 79 6e 60   ..?Emi@.._velyn`
0460   00 07 5f 47 65 6f 72 67 e1 00 08 1f 47 bc 00 09   .._Georg....G...
0470   4f 48 61 6c 65 bc 00 08 4f 48 61 72 76 20 00 09   OHale...OHarv ..
0480   2f 4a 61 18 01 08 4f 4a 6f 64 69 b7 00 07 4f 41   /Ja...OJodi...OA
0490   6c 65 78 1e 00 07 4f 4c 65 61 68 1e 00 08 2f 69   lex...OLeah.../i
04a0   6e d5 00 09 5f 4d 61 72 6e 69 12 01 08 4f         n..._Marni...O
                                              end?
```

ack pkg
```
       1  2  3  3  4  4    
0000   86 00 00 48 00 43 04 00 43 05 00 43 06 00         ...H.C..C..C..

```

1: Netmessagetype(7), isfragment
2: netmessagelibrarytype(8)
3: sequence number(16)
4: payload len as ushort(8/16)
5: remoteUniqueIdentifier(64)?????
6: InitializeRemoteTimeOffset???
7: fragmentnumber(16)
8: fragment total count(16)



## random notes
[stardew valley messages](https://github.com/WeDias/StardewValley/blob/main/Network/Multiplayer.cs#L1236)
[server loads scene](https://github.com/WeDias/StardewValley/blob/b237fdf9d8b67b079454bb727626fefccc73e15d/Network/LidgrenServer.cs#L158)
[stardewvalley packet strucutre](https://github.com/WeDias/StardewValley/blob/b237fdf9d8b67b079454bb727626fefccc73e15d/Network/OutgoingMessage.cs#L15)