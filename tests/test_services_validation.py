import pytest
import asyncio
from planpilot.tools.services import (
    travel_route_data,
    famous_restaurants_data,
    find_budget_hotels_data,
    get_weather_data,
)

@pytest.mark.asyncio
async def test_travel_route_ahmedabad_to_paris():
    route = await travel_route_data("Ahmedabad", "Paris")
    assert "error" not in route
    assert "Flight" in route["recommended_mode"] or "flight" in route["recommended_mode"].lower()
    for opt in route["transport_options"]:
        assert opt["mode"] != "Drive"
        assert opt["mode"] != "Train"
        assert opt["mode"] != "Bus"

@pytest.mark.asyncio
async def test_famous_restaurants_paris_indian():
    restaurants = await famous_restaurants_data("Paris", query="Indian food")
    assert len(restaurants) > 0
    for r in restaurants:
        text = f"{r['restaurant_name']} {r['speciality']} {r['why_popular']}".lower()
        assert any(k in text for k in ["indian", "thali", "dosa", "saravanaa", "curry", "kashmir", "jawad", "gandhi"])

@pytest.mark.asyncio
async def test_find_hotels_hotel_class_separated():
    hotels = await find_budget_hotels_data("Jaipur", budget="mid-range")
    assert len(hotels) > 0
    for h in hotels:
        assert "hotel_class" in h
        assert "review_rating" in h
        assert h["hotel_class"] != h["review_rating"]
