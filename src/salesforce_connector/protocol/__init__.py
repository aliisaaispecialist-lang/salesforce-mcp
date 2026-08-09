"""The MCP surface: what a client sees, and how it is translated.

`server` is wiring -- lifespan, tool listing, dispatch. `translate` is a pure
function of its argument in both directions, which is why the adapter can be
asserted without starting anything. Nothing here knows what Salesforce is.
"""
