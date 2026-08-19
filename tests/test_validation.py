"""Tests for validation logic (requirements extraction, transportation rules, and section enforcement)."""

import pytest
from planpilot.utils.validation import (
    extract_requirements,
    validate_and_enforce_sections,
    validate_hotel_entry,
    validate_restaurant_match,
    validate_transportation,
)


def test_extract_requirements_weather_only():
    reqs = extract_requirements("current weather in Hyderabad")
    assert reqs.destination == "Hyderabad"
    assert reqs.weather is True
    assert reqs.budget_hotels is False
    assert reqs.restaurants is False
    assert reqs.books is False


def test_extract_requirements_hotels_only():
    reqs = extract_requirements("budget hotels in Goa")
    assert reqs.destination == "Goa"
    assert reqs.budget_hotels is True
    assert reqs.weather is False
    assert reqs.restaurants is False


def test_extract_requirements_full():
    reqs = extract_requirements("Plan a 3-day trip from Ahmedabad to Paris in July with Italian food")
    assert reqs.origin == "Ahmedabad"
    assert reqs.destination == "Paris"
    assert reqs.cuisine == "Italian"
    assert reqs.itinerary_duration == "3-day"


def test_validate_transportation_international():
    res = validate_transportation(
        origin="Ahmedabad",
        destination="Paris",
        distance_km=6800,
        is_different_country=True,
        transport_options=[
            {"mode": "Drive", "duration": "100 hrs"},
            {"mode": "Flight", "duration": "9.5 hrs"},
        ],
    )
    assert res["recommended_mode"] == "Commercial Airline Flight"
    # Ensure driving was removed for intercontinental flight
    modes = [opt["mode"] for opt in res["transport_options"]]
    assert "Drive" not in modes
    assert "Flight" in modes


def test_validate_hotel_entry():
    entry = {
        "hotel_name": "Grand Palace",
        "price_range": "₹4,000/night",
        "rating": "4.5 ⭐",
        "location": "Downtown",
        "budget_tier": "mid-range",
    }
    validated = validate_hotel_entry(entry)
    assert validated["hotel_name"] == "Grand Palace"
    assert "hotel_class" in validated


def test_validate_restaurant_match():
    rest = {
        "restaurant_name": "Trattoria Bella",
        "speciality": "Italian Pasta",
        "rating": "4.6 ⭐",
        "location": "Central",
    }
    match = validate_restaurant_match(rest, requested_cuisine="Italian")
    assert match is True
