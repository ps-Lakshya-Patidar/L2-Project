"""Unit tests for user preference JSON storage, departure city fallback, and profile retrieval."""

import pytest
from planpilot.utils.preferences import (
    load_preferences,
    save_preferences,
    set_preference,
    get_preference,
    auto_update_preferences_from_text,
    build_preference_context,
)


def test_preference_json_persistence():
    """Test saving and loading user preferences from JSON."""
    test_prefs = {
        "home_city": "Ahmedabad",
        "interests": ["hiking", "heritage walks"],
        "dislikes": ["crowded malls"],
        "preferred_budget": "mid-range",
        "weekend_goal": "Explore",
        "indoor_preference": False,
        "custom_notes": "Vegetarian",
    }
    save_preferences(test_prefs)

    loaded = load_preferences()
    assert loaded["home_city"] == "Ahmedabad"
    assert "hiking" in loaded["interests"]
    assert loaded["custom_notes"] == "Vegetarian"


def test_departure_city_auto_extraction():
    """Test auto-updating departure home_city from user prompt text."""
    auto_update_preferences_from_text("I live in Indore and I like rock music")
    loaded = load_preferences()
    assert loaded["home_city"] == "Indore"


def test_preference_context_builder_includes_departure_fallback():
    """Test that preference context builder includes departure city fallback instructions."""
    set_preference("home_city", "Ahmedabad")
    context_str = build_preference_context()
    assert "Home/Departure city: Ahmedabad" in context_str
    assert "DEPARTURE CITY FALLBACK" in context_str
