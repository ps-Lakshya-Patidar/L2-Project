import pytest
from planpilot.utils.validation import (
    MANDATORY_SECTIONS,
    validate_and_enforce_sections,
    extract_requirements,
)

def test_quality_gate_enforces_all_11_sections():
    query = "Plan a trip to Paris from Ahmedabad including weather, budget hotels, Indian food, history and books."
    reqs = extract_requirements(query)
    incomplete_draft = """
# Destination Overview
Paris is the capital of France.

# Weather
Current weather is 18°C.
"""
    tool_context = {
        "destination": "Paris",
        "origin": "Ahmedabad",
        "route": {"travel_time": "10-12 hrs (Flight)", "recommended_mode": "Commercial Airline Flight"},
        "hotels": [{"hotel_name": "Hotel Paris", "hotel_class": "3-Star Hotel", "review_rating": "4.5/5.0 ⭐", "area": "10th Arr.", "price_range": "€70 - €120"}],
        "restaurants": [{"restaurant_name": "Saravanaa Bhavan Paris", "speciality": "South Indian Vegetarian", "rating": "4.5 ⭐", "location": "Gare du Nord"}],
        "books": [{"title": "A Moveable Feast", "author": "Ernest Hemingway", "info_url": "https://openlibrary.org/works/OL123W"}],
    }
    completed = validate_and_enforce_sections(incomplete_draft, reqs, tool_context)
    for section in MANDATORY_SECTIONS:
        assert f"# {section}" in completed or f"#{section}" in completed or f"## {section}" in completed
