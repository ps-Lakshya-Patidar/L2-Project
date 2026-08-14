"""Unit tests for PlanPilot AI Travel Planner MCP Tools."""
import pytest
from planpilot.tools.services import (
    find_budget_hotels_data,
)


@pytest.mark.asyncio
async def test_find_budget_hotels_curated():
    """Test hotel lookup for a curated city like Jaipur."""
    results = await find_budget_hotels_data("Jaipur", "low")
    assert isinstance(results, list)
    assert len(results) >= 1
    assert "hotel_name" in results[0]
    assert "price_range" in results[0]
    assert "rating" in results[0]
    assert "location" in results[0]


@pytest.mark.asyncio
async def test_find_budget_hotels_validation_error():
    """Test input validation for invalid city name."""
    results = await find_budget_hotels_data("x", "low")
    assert isinstance(results, list)
    assert "error" in results[0]
    assert "at least 2 characters" in results[0]["error"]


@pytest.mark.asyncio
async def test_travel_route_success():
    """Test travel route calculation between two cities."""
    from planpilot.tools.services import travel_route_data
    res = await travel_route_data("Ahmedabad", "Jaipur")
    assert isinstance(res, dict)
    assert res["source"] == "Ahmedabad"
    assert res["destination"] == "Jaipur"
    assert "distance_km" in res
    assert "transport_options" in res
    assert len(res["transport_options"]) >= 1


@pytest.mark.asyncio
async def test_travel_route_same_city():
    """Test error when source and destination are the same."""
    from planpilot.tools.services import travel_route_data
    res = await travel_route_data("Jaipur", "Jaipur")
    assert isinstance(res, dict)
    assert "error" in res
    assert "must be different" in res["error"]


@pytest.mark.asyncio
async def test_famous_restaurants_success():
    """Test restaurant lookup for a city."""
    from planpilot.tools.services import famous_restaurants_data
    res = await famous_restaurants_data("Jaipur")
    assert isinstance(res, list)
    assert len(res) >= 1
    assert "restaurant_name" in res[0]
    assert "speciality" in res[0]
    assert "rating" in res[0]
    assert "location" in res[0]


