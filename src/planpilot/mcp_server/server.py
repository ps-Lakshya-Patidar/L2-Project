"""PlanPilot MCP Server.

Creates and configures the MCPServer instance with all registered tools.
Tools are registered via the @mcp_server.tool() decorator.
"""

from __future__ import annotations
import json
from mcp.server import MCPServer
from planpilot.tools.services import (
    get_weather_data,
    search_books_data,
    discover_events_data,
)
from planpilot.utils.config import get_settings

_settings = get_settings()

mcp_server = MCPServer(
    name="planpilot",
    version="0.1.0",
    description="PlanPilot Local Tool Server",
    instructions="A tool server providing weather, books, and event discovery.",
)


@mcp_server.tool(
    name="get_weather",
    description="Get the current weather forecast for a specified city (e.g. 'New York', 'Paris', 'Tokyo').",
)
async def get_weather(city: str) -> str:
    """Fetch current weather for a city."""
    try:
        res = await get_weather_data(city)
        return json.dumps(res, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool(
    name="search_books",
    description="Search for book recommendations and information using a search query (e.g., topic, title, author).",
)
async def search_books(query: str) -> str:
    """Search books."""
    try:
        res = await search_books_data(query)
        return json.dumps(res, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool(
    name="discover_events",
    description="Discover live events, exhibitions, concerts, or activities happening in a specific city. "
    "The optional 'query' parameter filters the type of events (e.g. 'comedy shows', 'music concerts', 'art exhibitions').",
)
async def discover_events(city: str, query: str | None = None) -> str:
    """Fetch live events for a city."""
    try:
        res = await discover_events_data(city, query)
        return json.dumps(res, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})
