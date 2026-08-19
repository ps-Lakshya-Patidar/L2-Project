import pytest
from planpilot.agent.agent import PlanPilotAgent

def test_requested_tools_set_calculation():
    q = "What is the weather and famous restaurants in Paris?"
    q_lower = q.lower()
    has_weather = any(kw in q_lower for kw in ["weather", "temperature", "forecast", "rain", "sunny", "climate"])
    has_events = any(kw in q_lower for kw in ["event", "concert", "exhibition", "festival", "show", "activities", "music", "comedy", "standup", "stand-up", "gig", "play", "theatre", "theater"])
    has_books = any(kw in q_lower for kw in ["book", "novel", "author", "reading", "read"])
    has_hotels = any(kw in q_lower for kw in ["hotel", "stay", "resort", "hostel", "accommodation", "lodging"])
    has_route = any(kw in q_lower for kw in ["route", "travel from", "how to reach", "transport", "distance", "how to travel"])
    has_restaurants = any(kw in q_lower for kw in ["restaurant", "eat", "food", "dining", "dish", "delicacy", "cafe", "place to eat"])

    requested_tools = {
        t_name for t_name, req in [
            ("get_weather", has_weather),
            ("discover_events", has_events),
            ("search_books", has_books),
            ("find_budget_hotels", has_hotels),
            ("travel_route", has_route),
            ("famous_restaurants", has_restaurants),
        ] if req
    }

    assert requested_tools == {"get_weather", "famous_restaurants"}

    # Simulate seen_tool_calls after calling get_weather only
    seen_tool_calls = {("get_weather", '{"city": "Paris"}')}
    called_tools = {k[0] for k in seen_tool_calls}

    # Verify that requested_tools is NOT a subset of called_tools yet
    assert not requested_tools.issubset(called_tools)

    # Simulate seen_tool_calls after calling famous_restaurants as well
    seen_tool_calls.add(("famous_restaurants", '{"city": "Paris"}'))
    called_tools = {k[0] for k in seen_tool_calls}

    # Now all requested tools have been called!
    assert requested_tools.issubset(called_tools)
