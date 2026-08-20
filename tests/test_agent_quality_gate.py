"""Tests for agent quality gate section enforcement."""

import pytest
from planpilot.utils.validation import UserRequirements, validate_and_enforce_sections


def test_quality_gate_enforces_all_6_sections():
    draft = "# Weather\nWeather text\n"
    reqs = UserRequirements(origin="Indore", destination="Paris")
    tool_context = {
        "destination": "Paris",
        "weather": {},
        "route": {},
        "hotels": [],
        "restaurants": [],
        "events": [],
        "books": [],
    }

    result = validate_and_enforce_sections(draft, reqs, tool_context)
    sections = [
        "# Weather",
        "# Best Travel Route",
        "# Hotel Accommodations",
        "# Famous Restaurants",
        "# Upcoming Events",
        "# Recommended Books",
    ]
    for sec in sections:
        assert sec in result

