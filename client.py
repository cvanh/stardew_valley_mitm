import socket
import codecs

UDP_IP_ADDRESS = "127.0.0.1"
UDP_PORT_NO = 24642 

# class LidgrenPacket:
#     def __init__(self) -> None:
#         pass

class StarDewClient:
    def __init__(self) -> None:
        self.clientSock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.receive_message_listner()

        # discovery message
        self.send_message(b"\x88\x00\x00\x00\x00")


    def send_message(self,message):
        """
        sends message to server
        """
        self.clientSock.sendto(message, (UDP_IP_ADDRESS, UDP_PORT_NO))
    
    def receive_message_listner(self):
        try:
            while True:
                 data, addr = self.clientSock.recvfrom(1408) # 1408 is a lidgren packet
                 print("received message: %s" % data)       
        except socket.timeout:
            print("ERROR: acknowledgement was not received")
        except Exception as ex:
            print("ERROR:", ex)
        finally:
            self.clientSock.close()

StarDewClient()


