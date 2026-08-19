"""Tests for agent quality gate section enforcement."""

import pytest
from planpilot.utils.validation import UserRequirements, validate_and_enforce_sections


def test_quality_gate_enforces_all_11_sections():
    draft = "# Destination Overview\nOverview text\n"
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
        "# Destination Overview",
        "# Weather",
        "# How to Reach",
        "# Estimated Budget",
        "# Accommodation Options",
        "# Restaurants",
        "# Upcoming Events",
        "# History of Destination",
        "# Recommended Books",
        "# Suggested Itinerary",
        "# Travel Tips",
    ]
    for sec in sections:
        assert sec in result
