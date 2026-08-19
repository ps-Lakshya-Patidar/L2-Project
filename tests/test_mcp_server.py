"""Tests for PlanPilot MCP Server tool registration and execution."""

import pytest
from planpilot.mcp_server.server import (
    discover_events,
    famous_restaurants,
    find_budget_hotels,
    get_weather,
    mcp_server,
    search_books,
    travel_route,
)


@pytest.mark.asyncio
async def test_mcp_server_initialization():
    assert mcp_server.name == "planpilot"
    tools = await mcp_server.list_tools()
    assert len(tools) == 6
    names = [t.name for t in tools]
    assert "get_weather" in names
    assert "search_books" in names
    assert "discover_events" in names
    assert "find_budget_hotels" in names
    assert "travel_route" in names
    assert "famous_restaurants" in names


@pytest.mark.asyncio
async def test_mcp_get_weather_tool():
    res = await get_weather(city="Indore")
    assert isinstance(res, dict)
    assert "city" in res or "error" in res


@pytest.mark.asyncio
async def test_mcp_search_books_tool():
    res = await search_books(query="Sci-fi books")
    assert isinstance(res, list)
    assert len(res) > 0


@pytest.mark.asyncio
async def test_mcp_discover_events_tool():
    res = await discover_events(city="Mumbai")
    assert isinstance(res, list)
    assert len(res) > 0


@pytest.mark.asyncio
async def test_mcp_find_budget_hotels_tool():
    res = await find_budget_hotels(city="Jaipur", budget="low")
    assert isinstance(res, list)
    assert len(res) > 0


@pytest.mark.asyncio
async def test_mcp_travel_route_tool():
    res = await travel_route(source="Delhi", destination="Agra")
    assert isinstance(res, dict)
    assert "source" in res or "error" in res


@pytest.mark.asyncio
async def test_mcp_famous_restaurants_tool():
    res = await famous_restaurants(city="Delhi", query="Indian")
    assert isinstance(res, list)
    assert len(res) > 0
