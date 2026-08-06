"""The five operations this connector performs, one module each.

Each action knows one endpoint and nothing else: no HTTP, no retries, no
authentication. Those belong to the client below it, and the envelope above it
is identical whichever action ran.
"""
