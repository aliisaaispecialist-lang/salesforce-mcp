"""Everything that touches the network, and the shape of what crosses it.

`client` is the only module that opens a socket. `exchange` describes a request
and its answer. `ratelimit` decides whether a call is made at all. Actions above
this line describe what they want and never learn that HTTP exists.
"""
