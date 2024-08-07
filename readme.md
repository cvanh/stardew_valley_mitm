# poc mitm for stardew valley and lidgren
this repo contains a middleware for [mitmproxy.org](https://mitmproxy.org/) in mitm.py and docs about the lidgren and stardew valley packets in [notes.md](./notes.md)

you can run a proxy on port 8080 for stardew valley with this command:
`./mitmweb --mode reverse:udp://127.0.0.1:24642 -s ./mitm.py`
please keep in mind do not only use this proxy but also wireshark since that is much better

please note this is not finished yet