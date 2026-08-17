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
    find_budget_hotels_data,
    travel_route_data,
    famous_restaurants_data,
)

mcp_server = MCPServer(
    name="planpilot",
    version="0.1.0",
    description="PlanPilot AI Travel Planner Tool Server",
    instructions="A tool server providing weather, books, event discovery, budget hotels, travel routes, and famous restaurants.",
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
) -> list[dict[str, Any]]:
    """Search books."""
    try:
        res = await search_books_data(query)
        return res
    except Exception as e:
        return [{"error": str(e)}]


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
) -> list[dict[str, Any]]:
    """Fetch live events for a city."""
    try:
        res = await discover_events_data(city, query)
        return res
    except Exception as e:
        return [{"error": str(e)}]


@mcp_server.tool(
    name="find_budget_hotels",
    description="Suggest affordable budget hotels and accommodations in a city matching price constraints. "
    "Returns hotel name, price range per night, rating, location, and budget tier.",
)
async def find_budget_hotels(
    city: Annotated[
        str,
        Field(description="The target city name, e.g. 'Jaipur', 'Udaipur', 'Goa'"),
    ],
    budget: Annotated[
        str,
        Field(description="Budget tier: 'low' (<₹1500/night), 'mid-range' (₹1500-₹4000/night), 'premium' (>₹4000/night). Defaults to 'low'."),
    ] = "low",
) -> list[dict[str, Any]]:
    """Suggest budget hotels for a city."""
    try:
        res = await find_budget_hotels_data(city, budget)
        return res
    except Exception as e:
        return [{"error": str(e)}]


@mcp_server.tool(
    name="travel_route",
    description="Calculate distance, travel time, recommended modes of transport (train, bus, flight, drive), and route summary between a source and destination city.",
)
async def travel_route(
    source: Annotated[
        str,
        Field(description="Starting source city, e.g. 'Ahmedabad', 'Mumbai', 'Delhi'"),
    ],
    destination: Annotated[
        str,
        Field(description="Destination city, e.g. 'Jaipur', 'Udaipur', 'Goa'"),
    ],
) -> dict[str, Any]:
    """Suggest optimal travel route between source and destination cities."""
    try:
        res = await travel_route_data(source, destination)
        return res
    except Exception as e:
        return {"error": str(e)}


@mcp_server.tool(
    name="famous_restaurants",
    description="Suggest famous local restaurants, iconic food spots, specialities, ratings, and locations in a city. "
    "Use the optional 'query' parameter for specific cuisine preferences (e.g. 'Indian food', 'Italian bistros', 'vegan cafes', 'seafood').",
)
async def famous_restaurants(
    city: Annotated[
        str,
        Field(description="Target city name, e.g. 'New York', 'Jaipur', 'Paris', 'London'"),
    ],
    query: Annotated[
        str | None,
        Field(description="Optional cuisine or food preference filter, e.g. 'Indian food', 'Italian', 'vegan'"),
    ] = None,
) -> list[dict[str, Any]]:
    """Suggest famous restaurants for a city with optional cuisine query."""
    try:
        res = await famous_restaurants_data(city, query)
        return res
    except Exception as e:
        return [{"error": str(e)}]



