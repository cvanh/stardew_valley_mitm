from mitmproxy import udp
import struct
import codecs
import os
import sys
from enum import Enum
class UdpDump:
    def udp_start(self, flow: udp.UDPFlow):
        print(f"UDP connection started: {flow.client_conn.address}")

    def udp_end(self, flow: udp.UDPFlow):
        print(f"UDP connection ended: {flow.client_conn.address}")

    def udp_message(self, flow: udp.UDPFlow):
        data = flow.messages[-1].content

        messageCount = 0
        fragmentCount = 0
        ptr = 0

        messagetype = data[ptr]
        ptr += 1
        low = data[ptr]
        high = data[ptr]
        isFragmented = ((low & 1) == 1)
        sequenceNumber = (low >> 1) | (high << 7)
        payloadLen = int.from_bytes(data[ptr:ptr+2], byteorder='little')
        ptr += 1
        if isFragmented == True:
           fragmentGroupId = data[ptr]
           ptr += 1
           fragmentTotalCount = data[ptr]
           ptr += 1
           fragmentNumber = data[ptr]
           print("lidgren fragmentgroupid", fragmentGroupId)
           print("lidgren fragmenttotalcount", fragmentTotalCount)
           print("lidgren fragmentnumber", fragmentNumber)
        print("lidgren messagetype", messagetype,
              LidgrenNetMessageType(messagetype).name)
        print("lidgren seq", sequenceNumber)
        print("lidgren payloadlen", payloadLen)
        print("lidgren fragment", isFragmented)

        print("stardew messagetype?", data[ptr], data[ptr+3])
        print("stardew farmer id", int.from_bytes(
            data[5:13], byteorder="little"))
        print("===================")

        # check if we got a handler for the lidgren packet type
        if messagetype in handlers:
            handlers.get(messagetype)(data, ptr)


def fragmentedData(data, ptr):
    # print(data[:ptr])
    pass


def handleUnauthPacket(data, ptr):
    print("unauth packet")
    
def handleDiscovery(data):
   print("discovery made")
#    print("handlediscovery",data) 


def handlePong(data, ptr):
    print("pongg")
    # pass


def handlePing(data, ptr):
    print("ping")
    # pass


def handleACK(data, ptr):
    print("ACK")


handlers = {
    0: handleUnauthPacket,
    67: fragmentedData,

    # 129: handlePing,

    # 130: handlePong,

    # 134: handleACK
}


class LidgrenNetMessageType(Enum):
    Unconnected = 0
    UserUnreliable = 1
    UserSequenced1 = 2
    UserSequenced2 = 3
    UserSequenced3 = 4
    UserSequenced4 = 5
    UserSequenced5 = 6
    UserSequenced6 = 7
    UserSequenced7 = 8
    UserSequenced8 = 9
    UserSequenced9 = 10
    UserSequenced10 = 11
    UserSequenced11 = 12
    UserSequenced12 = 13
    UserSequenced13 = 14
    UserSequenced14 = 15
    UserSequenced15 = 16
    UserSequenced16 = 17
    UserSequenced17 = 18
    UserSequenced18 = 19
    UserSequenced19 = 20
    UserSequenced20 = 21
    UserSequenced21 = 22
    UserSequenced22 = 23
    UserSequenced23 = 24
    UserSequenced24 = 25
    UserSequenced25 = 26
    UserSequenced26 = 27
    UserSequenced27 = 28
    UserSequenced28 = 29
    UserSequenced29 = 30
    UserSequenced30 = 31
    UserSequenced31 = 32
    UserSequenced32 = 33
    UserReliableUnordered = 34
    UserReliableSequenced1 = 35
    UserReliableSequenced2 = 36
    UserReliableSequenced3 = 37
    UserReliableSequenced4 = 38
    UserReliableSequenced5 = 39
    UserReliableSequenced6 = 40
    UserReliableSequenced7 = 41
    UserReliableSequenced8 = 42
    UserReliableSequenced9 = 43
    UserReliableSequenced10 = 44
    UserReliableSequenced11 = 45
    UserReliableSequenced12 = 46
    UserReliableSequenced13 = 47
    UserReliableSequenced14 = 48
    UserReliableSequenced15 = 49
    UserReliableSequenced16 = 50
    UserReliableSequenced17 = 51
    UserReliableSequenced18 = 52
    UserReliableSequenced19 = 53
    UserReliableSequenced20 = 54
    UserReliableSequenced21 = 55
    UserReliableSequenced22 = 56
    UserReliableSequenced23 = 57
    UserReliableSequenced24 = 58
    UserReliableSequenced25 = 59
    UserReliableSequenced26 = 60
    UserReliableSequenced27 = 61
    UserReliableSequenced28 = 62
    UserReliableSequenced29 = 63
    UserReliableSequenced30 = 64
    UserReliableSequenced31 = 65
    UserReliableSequenced32 = 66
    UserReliableOrdered1 = 67
    UserReliableOrdered2 = 68
    UserReliableOrdered3 = 69
    UserReliableOrdered4 = 70
    UserReliableOrdered5 = 71
    UserReliableOrdered6 = 72
    UserReliableOrdered7 = 73
    UserReliableOrdered8 = 74
    UserReliableOrdered9 = 75
    UserReliableOrdered10 = 76
    UserReliableOrdered11 = 77
    UserReliableOrdered12 = 78
    UserReliableOrdered13 = 79
    UserReliableOrdered14 = 80
    UserReliableOrdered15 = 81
    UserReliableOrdered16 = 82
    UserReliableOrdered17 = 83
    UserReliableOrdered18 = 84
    UserReliableOrdered19 = 85
    UserReliableOrdered20 = 86
    UserReliableOrdered21 = 87
    UserReliableOrdered22 = 88
    UserReliableOrdered23 = 89
    UserReliableOrdered24 = 90
    UserReliableOrdered25 = 91
    UserReliableOrdered26 = 92
    UserReliableOrdered27 = 93
    UserReliableOrdered28 = 94
    UserReliableOrdered29 = 95
    UserReliableOrdered30 = 96
    UserReliableOrdered31 = 97
    UserReliableOrdered32 = 98
    Unused1 = 99
    Unused2 = 100
    Unused3 = 101
    Unused4 = 102
    Unused5 = 103
    Unused6 = 104
    Unused7 = 105
    Unused8 = 106
    Unused9 = 107
    Unused10 = 108
    Unused11 = 109
    Unused12 = 110
    Unused13 = 111
    Unused14 = 112
    Unused15 = 113
    Unused16 = 114
    Unused17 = 115
    Unused18 = 116
    Unused19 = 117
    Unused20 = 118
    Unused21 = 119
    Unused22 = 120
    Unused23 = 121
    Unused24 = 122
    Unused25 = 123
    Unused26 = 124
    Unused27 = 125
    Unused28 = 126
    Unused29 = 127
    LibraryError = 128
    Ping = 129  # used for RTT calculation
    Pong = 130  # used for RTT calculation
    Connect = 131
    ConnectResponse = 132
    ConnectionEstablished = 133
    Acknowledge = 134
    Disconnect = 135
    Discovery = 136
    DiscoveryResponse = 137
    NatPunchMessage = 138  # send between peers
    NatIntroduction = 139  # send to master server
    NatIntroductionConfirmRequest = 142
    NatIntroductionConfirmed = 143
    ExpandMTURequest = 140
    ExpandMTUSuccess = 141

def IncommingMessageParse(message_type):
    """
    parsed incomming stardew valley message acording to https://github.com/WeDias/StardewValley/blob/b237fdf9d8b67b079454bb727626fefccc73e15d/Network/Client.cs#L89
    """
    if message_type <= 9:
        if message_type == 0:
            return "receive server intro"
        elif message_type == 1:
            # return "process incomming message1"
            return parsegamemsg(message_type)
        elif message_type == 2:
            # return "process incomming message 2"
            return parsegamemsg(message_type)
        elif message_type == 9:
            return "get farm hands"
        else:
            # return "process incomming message 3"
            return "error parsing stardew message"

    elif message_type == 11:
        return "load string"
    elif message_type == 16:
        return "username update"
    else:
        # return "process incomming message"
        return parsegamemsg(message_type)


def parsegamemsg(messageType):
    """
        parse stardew valley message type according to: 
        https://github.com/WeDias/StardewValley/blob/b237fdf9d8b67b079454bb727626fefccc73e15d/Network/Multiplayer.cs#L1236
    """
    match messageType:
        case 0:
            return "readobject delta"
        case 2:
            return "receive player intro"
        case 3:
            return "read player active location"
        case 4:
            return "event?"
        case 6:
            return "read location"
        case 7:
            return "read sprite location"
        case 8:
            return "warp character"
        case 10:
            return "receive chat message"
        case 12:
            return "receive world state"
        case 13:
            return "receive team data"
        case 14:
            return "receive new days sync"
        case 15:
            return "receive chat info message"
        case 17:
            return "receive chat info message"
        case 18:
            return "receive parseServerToClientsMessage()"
        case 19:
            return "player disconnect"
        case 20:
            return "receive shared achievement"
        case 21:
            return "receive global message"
        case 22:
            return "receive party wide mail"
        case 23:
            return "receive force kick"
        case 24:
            return "receive remove location from lookup "
        case 25:
            return "receive farmed killed monster"
        case 26:
            return "receive request grandpa reevol"
        case 27:
            return "receive nut dig"
        case 28:
            return "receive passout request"
        case 29:
            return "receive passout"
        case _:
            print("error parsing messagetype", messageType)

# mitm scripts loading
addons = [
    UdpDump()
]

if __name__ == "__main__":
    import sys
    from mitmproxy.tools.main import mitmdump

    sys.argv = ["mitmdump", "-s", __file__]
    mitmdump()
