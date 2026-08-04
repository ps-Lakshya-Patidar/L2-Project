"""Entry point for running the MCP server as a module.

Usage:
    python -m planpilot.mcp_server           # stdio transport (default)
    python -m planpilot.mcp_server --stdio    # explicit stdio
    python -m planpilot.mcp_server --sse      # SSE transport

The stdio transport is the standard for local agent ↔ server communication.
The agent spawns this process and communicates over stdin/stdout.
"""

from __future__ import annotations

import sys
from typing import Literal

from planpilot.mcp_server.server import mcp_server


def main() -> None:
    """Run the MCP server with the specified transport."""
    # Default to stdio; check for --sse flag
    transport: Literal["stdio", "sse", "streamable-http"] = "stdio"

    if "--sse" in sys.argv:
        transport = "sse"
    elif "--streamable-http" in sys.argv:
        transport = "streamable-http"

    mcp_server.run(transport=transport)


if __name__ == "__main__":
    main()
