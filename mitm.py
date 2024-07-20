from mitmproxy import udp
import struct
import codecs

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
            print("===================")

            if messagetype == 0:
                ptr += 1
                print(data, data[:ptr])

            # check if we got a handler for the lidgren packet type
            if messagetype in handlers:
                handlers.get(messagetype)(data)


def fragmentedData(data):
    print(data)
    
def handleDiscovery(data):
   print("discovery made")
#    print("handlediscovery",data) 


def handlePong(data):
    print("pongg")


def handlePing(data):
    print("ping")


def handleACK(data):
    print("ACK")


handlers = {
    # 0: fragmentedData,

    129: handlePing,

    130: handlePong,

    134: handleACK
}


















addons = [
    UdpDump()
]

if __name__ == "__main__":
    import sys
    from mitmproxy.tools.main import mitmdump

    sys.argv = ["mitmdump", "-s", __file__]
    mitmdump()
