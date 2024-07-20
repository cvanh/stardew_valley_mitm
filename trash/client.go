package main

import (
	"fmt"
	"net"
	"os"
	"time"
)

// messagetypes from lidgren lib
const (
	NetError                    = 0
	NetStatusChanged            = 1 << 0  // Data (string)
	NetUnconnectedData          = 1 << 1  // Data					Based on data received
	NetConnectionApproval       = 1 << 2  // Data
	NetData                     = 1 << 3  // Data					Based on data received

	NetReceipt                  = 1 << 4  // Data

	// 88
	NetDiscoveryRequest         = 1 << 5  // (no data)

	// 89
	NetDiscoveryResponse        = 1 << 6  // Data

	NetVerboseDebugMessage      = 1 << 7  // Data (string)
	NetDebugMessage             = 1 << 8  // Data (string)
	NetWarningMessage           = 1 << 9  // Data (string)
	NetErrorMessage             = 1 << 10 // Data (string)
	NetNatIntroductionSuccess   = 1 << 11 // Data (as passed to master server)
	NetConnectionLatencyUpdated = 1 << 12 // Seconds as a Single
)

type LidgrenPackage struct {
	NetMessageType [7]byte
	IsFragment [1]byte
	NetMessageLibraryType any
	SequenceNumber any
	PayloadLen any
	FragmentGroupId any
	FragmentTotalCount any
	FragmentNumber any
	Payload any
}

var conn *net.UDPConn

func main() {

	if len(os.Args) == 1 {
		fmt.Println("Please provide host:port to connect to")
		os.Exit(1)
	}

	// Resolve the string address to a UDP address
	udpAddr, err := net.ResolveUDPAddr("udp", os.Args[1])

	if err != nil {
		fmt.Println(err)
		os.Exit(1)
	}

	// Dial to the address with UDP
	conn, err = net.DialUDP("udp", nil, udpAddr)

	send("\x88\x00\x00\x00\x00")

	for {
		conn.SetReadDeadline(time.Now().Add(15 * time.Second))

		// 1408 bytes in packet https://github.com/lidgren/lidgren-network-gen3/blob/master/Lidgren.Network/NetPeerConfiguration.cs#L36C12-L36C16
		buf := make([]byte, 1408)
		amountByte, remAddr, _ := conn.ReadFrom(buf)

		fmt.Println(amountByte, "bytes received from", remAddr)
		fmt.Println(string(buf))

		send("StardewValley")
		// send(LidgrenPackage{
		// 	NetMessageType: NetData,
		// 	IsFragment: 1,
		// 	Payload: "StardewValley",
		// })

	}
	// Read from the connection untill a new line is send
	// data, err := bufio.NewReader(conn).ReadString('\n')

	// Print the data read from the connection to the terminal
	// fmt.Print("> ", string(data))

}

func send(body string) {
	// send magic knock. server returns version then
	bodyBytes := []byte(body)
	_, err := conn.Write(bodyBytes)

	if err != nil {
		fmt.Println(err)
		os.Exit(1)
	}
}
