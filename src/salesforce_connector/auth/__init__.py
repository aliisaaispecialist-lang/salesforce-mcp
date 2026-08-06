"""Obtaining an access token, without performing any I/O.

Each strategy builds a token request and parses the reply. The client sends it.
Keeping the network in one module means the whole handshake, including the
signing, is tested without a socket.
"""
