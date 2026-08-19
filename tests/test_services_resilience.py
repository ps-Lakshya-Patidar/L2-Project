"""Tests for service implementations focusing on resilience, fallbacks, and anti-fabrication rules."""

import pytest
from planpilot.tools.services import (
    clear_services_cache,
    discover_events_data,
    famous_restaurants_data,
    find_budget_hotels_data,
    get_weather_data,
    search_books_data,
    travel_route_data,
    validate_city_name,
)


@pytest.fixture(autouse=True)
def auto_clear_cache():
    clear_services_cache()
    yield
    clear_services_cache()


def test_validate_city_name_unicode():
    assert validate_city_name("São Paulo") == "São Paulo"
    assert validate_city_name("München") == "München"
    assert validate_city_name("New York") == "New York"
    with pytest.raises(ValueError):
        validate_city_name("a")


@pytest.mark.asyncio
async def test_get_weather_data_success():
    res = await get_weather_data("Hyderabad")
    assert "error" not in res
    assert res["city"] == "Hyderabad"
    assert "temperature_c" in res
    assert "forecast_next_12h" in res


@pytest.mark.asyncio
async def test_get_weather_data_invalid_city():
    res = await get_weather_data("NonExistentCityXYZ123")
    assert "error" in res


@pytest.mark.asyncio
async def test_search_books_data_success():
    res = await search_books_data("Python programming")
    assert isinstance(res, list)
    assert len(res) > 0
    first = res[0]
    assert "title" in first or "source" in first


@pytest.mark.asyncio
async def test_no_fabricated_hotels():
    """Verify that fake hotels like 'Budget Stay Central' or fake ratings are NEVER returned when OSM/DDG fail or return data."""
    res = await find_budget_hotels_data("Hyderabad", budget="low")
    assert isinstance(res, list)
    for hotel in res:
        # Check notice or hotel fields
        if "hotel_name" in hotel:
            assert "Budget Stay Central" not in hotel["hotel_name"]
            assert "Backpackers Haven" not in hotel["hotel_name"]
            # Check rating is not hardcoded fake star if unrated
            assert hotel.get("rating") != "4.3 ⭐" or "OpenStreetMap" in hotel.get("source", "")


@pytest.mark.asyncio
async def test_no_fabricated_restaurants():
    """Verify that hardcoded Jaipur restaurants (LMB, Rawat) are NEVER returned for other cities."""
    res = await famous_restaurants_data("Paris", query="French")
    assert isinstance(res, list)
    for rest in res:
        if "restaurant_name" in rest:
            assert "Laxmi Misthan Bhandar" not in rest["restaurant_name"]
            assert "Rawat Misthan Bhandar" not in rest["restaurant_name"]


@pytest.mark.asyncio
async def test_no_fabricated_travel_route():
    """Verify that fake distance 'Approx 350 - 500 km' is NEVER returned when geocoding fails."""
    res = await travel_route_data("InvalidCity111", "InvalidCity222")
    assert "error" in res
    assert "distance_km" not in res  # No fake route dictionary!


@pytest.mark.asyncio
async def test_travel_route_data_success():
    res = await travel_route_data("Ahmedabad", "Mumbai")
    assert "error" not in res
    assert res["source"] == "Ahmedabad"
    assert res["destination"] == "Mumbai"
    assert "estimated" in res["distance_km"].lower() or "km" in res["distance_km"]
    assert "transport_options" in res
