"""Entry point, kept where the programme's repository layout expects it.

The implementation lives in the package as `salesforce_connector.mcp_server`
rather than here, for one concrete reason: this directory is named `mcp`, and
the MCP SDK's own package is also named `mcp`. A module inside this directory
that imports the SDK is asking Python to choose between them, and which one it
picks depends on how the process happened to be started. Moving the code one
level up removes the ambiguity entirely, while leaving the file the layout
calls for exactly where it is expected.
"""

from salesforce_connector.mcp_server import main

if __name__ == "__main__":
    main()
