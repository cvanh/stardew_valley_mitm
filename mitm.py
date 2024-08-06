from mitmproxy import udp
import struct
import codecs
import os
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
        while (len(data) - ptr) >= 5:
            messagetype = data[ptr] 
            ptr += 1

            low = data[ptr]
            high = data[ptr]
            isFragmented = ((low & 1) == 1)

            # TODO is this right?
            sequenceNumber = (low >> 1) | (high << 7)
            payloadLen = int.from_bytes(data[ptr:ptr+2], byteorder='little')

            ptr += 1

            if isFragmented == True:
               fragmentGroupId = data[ptr]
               ptr += 1
               fragmentTotalCount = data[ptr]
               ptr += 1
               fragmentNumber = data[ptr]

            #    print("fragmentgroupid", fragmentGroupId)
            #    print("fragmenttotalcount", fragmentTotalCount)
            #    print("fragmentnumber", fragmentNumber)

            # print("messagetype", messagetype)
            # print("seq", sequenceNumber)
            # print("payloadlen", payloadLen)
            # print("fragment", isFragmented)
            # print("===================")

            if messagetype == 0 and isFragmented == False and b"kaas" in data:
                ptr += 1

                # stardew message type?
                # print("type", data[ptr])
                # print(">", IncommingMessageParse(data[ptr]))
                print(">", data[ptr:])

                ptr += 1
                # stardew farmer id? seems more like seq
                # print("farmer", data[ptr])
            # os.system("clear")

            # check if we got a handler for the lidgren packet type
            if messagetype in handlers:
                handlers.get(messagetype)(data)


def parseBytes(data, ptr):
    parsed = ""
    readptr = ptr >> 3
    startReadIndex = ptr - (readptr * 8)

    if startReadIndex == 0:
        print("asd")
        return

    secondpartlen = 8 - startReadIndex
    secondMask = 255 >> secondpartlen

    for i in range(7):
        b = data[readptr] >> startReadIndex

        readptr += 1

        second = data[ptr] & secondMask
	# destination[destinationByteOffset++] = (byte)(b | (second << secondPartLen));
        readptr += 1
        parsed += str(b | (second << secondpartlen))
    return parsed


def fragmentedData(data):
    # print(data)
    pass
    
def handleDiscovery(data):
   print("discovery made")
#    print("handlediscovery",data) 


def handlePong(data):
    print("pongg")
    # pass


def handlePing(data):
    print("ping")
    # pass


def handleACK(data):
    print("ACK")


handlers = {
    0: fragmentedData,

    # 129: handlePing,

    # 130: handlePong,

    # 134: handleACK
}

# parses message type acording to https://github.com/WeDias/StardewValley/blob/b237fdf9d8b67b079454bb727626fefccc73e15d/Network/Client.cs#L89


def IncommingMessageParse(message_type):
    if message_type <= 9:
        if message_type == 1:
            return "receive server intro"
        elif message_type == 2:
            # return "process incomming message1"
            return parsemsg(message_type)
        elif message_type == 3:
            # return "process incomming message 2"
            return parsemsg(message_type)
        elif message_type == 9:
            return "get farm hands"
        else:
            # return "process incomming message 3"
            return parsemsg(message_type)

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
