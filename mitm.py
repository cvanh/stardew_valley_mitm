from mitmproxy import udp
import struct
import codecs

class UdpDump:
    def udp_start(self, flow: udp.UDPFlow):
        print(f"UDP connection started: {flow.client_conn.address}")

    def udp_end(self, flow: udp.UDPFlow):
        print(f"UDP connection ended: {flow.client_conn.address}")

    def udp_message(self, flow: udp.UDPFlow):
        client_address = flow.client_conn.address
        server_address = flow.server_conn.address
        data = flow.messages[-1].content

        # print(f"UDP message from {client_address} to {server_address}")
        # print(data[:1])
    
        # messagetype = bin((int.from_bytes(data[:1], byteorder='big')))[2:]
        # print(data)


        ptr = 0
        while (len(data) - ptr) >= 5:
            messagetype = data[ptr] 
            ptr += 1

            low = data[ptr]
            high = data[ptr]
            isFragmented = ((low & 1) == 1)
            				# ushort sequenceNumber = (ushort)((low >> 1) | (((int)high) << 7));

            # isFragmented = bin((int.from_bytes(data[:1], byteorder='big')))[2:][-1]
            sequenceNumber = data[2:4]
            payloadLen = data[4:6]

            if isFragmented == "1":
               fragmentGroupId = data[6:8]
               fragmentTotalCount = data[8:10] 
               fragmentNumber = data[12:14]

               print("fragmentgroupid", fragmentGroupId)  
               print("fragmenttotalcount", fragmentTotalCount)
               print("fragmentnumber", fragmentNumber)

            print("messagetype", messagetype)
            print("seq",sequenceNumber)
            print("payload len", payloadLen)
            print("msgtype",messagetype, data[:1])
            print("fragment", isFragmented)
            print("===================")

            # check if we got a handler for the lidgren packet type
            if messagetype in handlers:
                handlers.get(messagetype)(data)

def bytesToBinary(bytes):
    return int(bin((int.from_bytes(bytes, byteorder='big')))[2:])
    

def fragmentedData(data):
    print(str(data))
    
def handleDiscovery(data):
   print("discovery made")
#    print("handlediscovery",data) 
    
        
handlers = {
    # 0x86
    "01000011": fragmentedData,

    #0x88
    "10001001": handleDiscovery 
}


















addons = [
    UdpDump()
]

if __name__ == "__main__":
    import sys
    from mitmproxy.tools.main import mitmdump

    sys.argv = ["mitmdump", "-s", __file__]
    mitmdump()
