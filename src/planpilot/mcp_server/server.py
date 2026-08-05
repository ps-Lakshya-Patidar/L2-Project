"""PlanPilot MCP Server.

Creates and configures the MCPServer instance with all registered tools.
Tools are registered via the @mcp_server.tool() decorator.
"""

from __future__ import annotations
from typing import Annotated, Any
from pydantic import Field
from mcp.server import MCPServer
from planpilot.tools.services import (
    get_weather_data,
    search_books_data,
    discover_events_data,
    compute_weekend_score,
)
from planpilot.utils.config import get_settings

_settings = get_settings()

mcp_server = MCPServer(
    name="planpilot",
    version="0.1.0",
    description="PlanPilot Local Tool Server",
    instructions="A tool server providing weather, books, event discovery, and weekend scoring.",
)


@mcp_server.tool(
    name="get_weather",
    description="Get the current weather forecast for a specified city (e.g. 'New York', 'Paris', 'Tokyo').",
)
async def get_weather(
    city: Annotated[
        str,
        Field(
            description="The name of the city to get weather for, e.g. 'Indore', 'Mumbai', 'New York'"
        ),
    ]
) -> dict[str, Any]:
    """Fetch current weather for a city. Returns temperature in Celsius, windspeed in km/h, and a 12-hour precipitation forecast."""
    try:
        res = await get_weather_data(city)
        return res
    except Exception as e:
        return {"error": str(e)}


@mcp_server.tool(
    name="search_books",
    description="Search for book recommendations and information using a search query (e.g., topic, title, author).",
)
async def search_books(
    query: Annotated[
        str,
        Field(
            description="The search query for books, e.g. 'science fiction', 'Lord of the Rings', 'Tolkien'"
        ),
    ]
) -> list[dict[str, Any]] | dict[str, Any]:
    """Search books."""
    try:
        res = await search_books_data(query)
        return res
    except Exception as e:
        return {"error": str(e)}


@mcp_server.tool(
    name="discover_events",
    description="Discover live events, exhibitions, concerts, or activities happening in a specific city. "
    "The optional 'query' parameter filters the type of events (e.g. 'comedy shows', 'music concerts', 'art exhibitions').",
)
async def discover_events(
    city: Annotated[
        str,
        Field(
            description="The city where events are happening, e.g. 'Ahmedabad', 'Indore', 'London'"
        ),
    ],
    query: Annotated[
        str | None,
        Field(
            description="Optional query to filter type of events, e.g. 'comedy shows', 'music concerts'"
        ),
    ] = None,
) -> list[dict[str, str]] | dict[str, Any]:
    """Fetch live events for a city."""
    try:
        res = await discover_events_data(city, query)
        return res
    except Exception as e:
        return {"error": str(e)}


@mcp_server.tool(
    name="get_weekend_score",
    description="Compute a Weekend Quality Score (0-100) for a city by combining weather forecast and local event availability. "
    "Returns a score, label (e.g. 'Excellent Weekend!'), weather summary, tips, and preference match bonus.",
)
async def get_weekend_score(
    city: Annotated[
        str,
        Field(description="The city to score the weekend for, e.g. 'Indore', 'Mumbai', 'New York'"),
    ],
) -> dict[str, Any]:
    """Compute weekend score by fetching weather + events for the city."""
    try:
        from planpilot.utils.preferences import load_preferences
        prefs = load_preferences()

        # Fetch weather and events concurrently
        import asyncio
        weather, events = await asyncio.gather(
            get_weather_data(city),
            discover_events_data(city),
        )

        if "error" in weather:
            return {"error": f"Could not fetch weather: {weather['error']}"}

        result = compute_weekend_score(weather, events, prefs)
        result["city"] = city
        result["weather"] = weather
        result["top_events"] = events[:3] if events else []
        return result
    except Exception as e:
        return {"error": str(e)}
