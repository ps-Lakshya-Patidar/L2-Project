"""Weekend Wizard MCP Server.

Creates and configures the MCPServer instance with all registered tools.
Tools are registered via the @mcp_server.tool() decorator.
"""

from __future__ import annotations

import json

from mcp.server import MCPServer

from weekend_wizard.tools.services import (
    get_dog_image_data,
    get_joke_data,
    get_trivia_data,
    get_weather_data,
    search_books_data,
)
from weekend_wizard.utils.config import get_settings

_settings = get_settings()

mcp_server = MCPServer(
    name="weekend-wizard",
    version="0.1.0",
    description="Weekend Wizard Local Tool Server",
    instructions="A tool server providing weather, books, jokes, dog images, and trivia.",
)


@mcp_server.tool(
    name="echo",
    description="Echo back the provided message. Useful for testing server connectivity.",
)
def echo(message: str) -> str:
    """Echo back the message."""
    return f"[echo] {message}"


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
    name="get_joke",
    description="Get a random joke from JokeAPI. Optional category: 'Programming', 'Misc', 'Dark', 'Pun', 'Spooky', 'Christmas', or 'Any' (default).",
)
async def get_joke(category: str = "Any") -> str:
    """Fetch a joke."""
    try:
        res = await get_joke_data(category)
        return json.dumps(res, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool(
    name="get_dog_image",
    description="Get a random dog picture URL. Optional breed parameter to filter by breed (e.g. 'retriever', 'hound', 'poodle').",
)
async def get_dog_image(breed: str | None = None) -> str:
    """Fetch random dog image URL."""
    try:
        res = await get_dog_image_data(breed)
        return json.dumps(res, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool(
    name="get_trivia",
    description="Get a random trivia question. Optional difficulty parameter to filter questions ('easy', 'medium', 'hard').",
)
async def get_trivia(difficulty: str | None = None) -> str:
    """Fetch a trivia question."""
    try:
        res = await get_trivia_data(difficulty)
        return json.dumps(res, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})
