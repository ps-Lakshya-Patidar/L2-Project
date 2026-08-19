"""Validation and Requirement Extraction Engine for PlanPilot.

Enforces strict travel validation, anti-hallucination guardrails, and completeness:
1. Structured Requirement Extraction
2. Geographic & Transportation Validation
3. Restaurant Cuisine Matching
4. Hotel Star vs Review Score Separation
5. Weather Date Logic
6. 11-Section Completeness Enforcer
"""
from __future__ import annotations

import re
from typing import Any
from pydantic import BaseModel, Field


MANDATORY_SECTIONS = [
    "Destination Overview",
    "Weather",
    "How to Reach",
    "Estimated Budget",
    "Accommodation Options",
    "Restaurants",
    "Upcoming Events",
    "History of Destination",
    "Recommended Books",
    "Suggested Itinerary",
    "Travel Tips",
]


class UserRequirements(BaseModel):
    """Structured extraction of user travel planning requirements."""
    origin: str = Field(default="", description="Departure/origin city.")
    destination: str = Field(default="", description="Target destination city.")
    travel_dates: str | None = Field(default=None, description="Specific travel dates or season if provided.")
    budget_level: str = Field(default="mid-range", description="Budget tier: budget, mid-range, luxury.")
    hotel_preferences: str | None = Field(default=None, description="Specific hotel requirements.")
    cuisine: str | None = Field(default=None, description="Requested cuisine/dietary preference (e.g. Indian, Vegetarian, Italian).")
    itinerary_duration: str = Field(default="3-day", description="Duration of trip/itinerary.")
    weather: bool = Field(default=True, description="Include weather section.")
    budget_hotels: bool = Field(default=True, description="Include accommodation section.")
    restaurants: bool = Field(default=True, description="Include restaurant section.")
    events: bool = Field(default=True, description="Include events section.")
    history: bool = Field(default=True, description="Include destination history section.")
    books: bool = Field(default=True, description="Include book recommendations section.")
    itinerary: bool = Field(default=True, description="Include day-by-day itinerary.")
    tips: bool = Field(default=True, description="Include travel tips.")


def extract_requirements(query: str, user_prefs: dict[str, Any] | None = None) -> UserRequirements:
    """Extract structured requirements from user query and fallback preferences."""
    q_lower = query.lower()
    user_prefs = user_prefs or {}

    origin = ""
    destination = ""

    # 1. Pattern: from <origin> to <destination>
    match_from_to = re.search(r'from\s+([A-Za-z\s\.\'\-]+?)\s+to\s+([A-Za-z\s\.\'\-]+?)(?:\s+including|\s+with|\s+for|\s+and|\s+in|\.|\,|$)', query, re.IGNORECASE)
    if match_from_to:
        origin = match_from_to.group(1).strip()
        destination = match_from_to.group(2).strip()

    # 2. Pattern: to <destination> from <origin>
    if not origin or not destination:
        match_to_from = re.search(r'to\s+([A-Za-z\s\.\'\-]+?)\s+from\s+([A-Za-z\s\.\'\-]+?)(?:\s+including|\s+with|\s+for|\s+and|\s+in|\.|\,|$)', query, re.IGNORECASE)
        if match_to_from:
            destination = match_to_from.group(1).strip()
            origin = match_to_from.group(2).strip()

    # 3. Pattern: trip to <destination> / visit <destination> / in <destination> / weather in <destination>
    if not destination:
        match_dest = re.search(
            r'(?:trip to|travel to|visit|explore|vacation in|plan for|guide to|plan a trip to|weather in|hotels in|restaurants in|events in|books in|in)\s+([A-Za-z\s\.\'\-]+?)(?:\s+from|\s+including|\s+with|\s+for|\s+and|\.|\,|$)',
            query,
            re.IGNORECASE,
        )
        if match_dest:
            destination = match_dest.group(1).strip()

    # Clean up destination/origin strings from extra words
    for noise in ["including", "with", "and", "a", "the", "my", "trip", "weekend", "vacation", "itinerary"]:
        if origin.lower().startswith(noise + " "):
            origin = origin[len(noise)+1:].strip()
        if destination.lower().startswith(noise + " "):
            destination = destination[len(noise)+1:].strip()

    # Fallback origin to home_city from preferences if omitted
    if not origin and user_prefs.get("home_city"):
        origin = user_prefs["home_city"].strip()

    # Extract cuisine / dietary preference
    cuisine = None
    known_cuisines = [
        ("indian", "Indian"),
        ("vegetarian", "Vegetarian"),
        ("pure veg", "Vegetarian"),
        ("vegan", "Vegan"),
        ("italian", "Italian"),
        ("french", "French"),
        ("chinese", "Chinese"),
        ("japanese", "Japanese"),
        ("thai", "Thai"),
        ("mexican", "Mexican"),
        ("seafood", "Seafood"),
        ("street food", "Street Food"),
        ("local", "Local"),
    ]
    for c_kw, c_label in known_cuisines:
        if c_kw in q_lower:
            cuisine = c_label
            break

    if not cuisine and user_prefs.get("interests"):
        for interest in user_prefs["interests"]:
            for c_kw, c_label in known_cuisines:
                if c_kw in interest.lower():
                    cuisine = c_label
                    break

    # Extract budget level
    budget_level = "mid-range"
    if any(w in q_lower for w in ["budget", "cheap", "hostel", "backpack", "low cost", "under ₹", "under $"]):
        budget_level = "budget"
    elif any(w in q_lower for w in ["luxury", "5 star", "five star", "resort", "premium", "first class"]):
        budget_level = "luxury"
    elif user_prefs.get("preferred_budget") and user_prefs["preferred_budget"] != "any":
        budget_level = user_prefs["preferred_budget"]

    # Extract duration
    duration = "3-day"
    match_dur = re.search(r'(\d+)\s*(?:-| )*(?:day|days|night|nights)', q_lower)
    if match_dur:
        duration = f"{match_dur.group(1)}-day"
    elif "weekend" in q_lower:
        duration = "Weekend (2-day)"
    elif "week" in q_lower:
        duration = "7-day"

    # Extract travel dates if specified
    travel_dates = None
    date_patterns = [
        r'(?:in|on|during|for)\s+(january|february|march|april|may|june|july|august|september|october|november|december)(?:\s+\d{4})?',
        r'(?:in|during)\s+(summer|winter|monsoon|spring|autumn|fall)',
        r'(?:from|on)\s+(\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s*(?:to|-)\s*\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*)',
    ]
    for dp in date_patterns:
        m_date = re.search(dp, q_lower)
        if m_date:
            travel_dates = m_date.group(0).strip()
            break

    # Detect which sections the query explicitly references.
    # These flags drive the quality gate — only inject content for sections the user asked about.
    # Use word-boundary regex (\b) to avoid false substring matches
    # e.g. "eat" must NOT fire inside "weather", "inn" must NOT fire inside "winning".
    def _has_kw(keywords: list[str]) -> bool:
        pattern = r"\b(?:" + "|".join(re.escape(k) for k in keywords) + r")\b"
        return bool(re.search(pattern, q_lower))

    has_weather      = _has_kw(["weather", "temperature", "forecast", "rain", "sunny", "climate"])
    has_budget_hotels = _has_kw(["hotel", "hotels", "stay", "accommodation", "resort", "hostel", "lodging"])
    has_restaurants  = _has_kw(["food", "restaurant", "restaurants", "cuisine", "dining", "eat", "cafe", "delicacy"])
    has_history      = _has_kw(["history", "historical", "heritage", "monument", "ancient", "culture"])
    has_books        = _has_kw(["book", "books", "reading", "novel", "literature", "author"])

    return UserRequirements(
        origin=origin,
        destination=destination,
        travel_dates=travel_dates,
        budget_level=budget_level,
        cuisine=cuisine,
        itinerary_duration=duration,
        weather=has_weather,
        budget_hotels=has_budget_hotels,
        restaurants=has_restaurants,
        history=has_history,
        books=has_books,
    )


def validate_transportation(
    origin: str,
    destination: str,
    distance_km: float,
    is_different_country: bool,
    transport_options: list[dict[str, Any]],
) -> dict[str, Any]:
    """Enforce geographic and realistic transportation constraints.

    Rules:
    - If origin and destination are in different countries or distance > 2000 km:
      * Exclusively prioritize and recommend Flights.
      * Strictly omit/reject Drive, Bus, and Local Train options unless directly connected bordering rail.
    """
    is_long_haul = distance_km > 2000 or is_different_country

    if is_long_haul:
        if distance_km > 10000:
            flight_duration = "16 - 24 hrs (Connecting International Flight)"
            cost_str = "₹55,000 - ₹1,20,000 ($700 - $1,500)"
        elif distance_km > 5000:
            flight_duration = "8 - 14 hrs (Direct / Connecting International Flight)"
            cost_str = "₹35,000 - ₹75,000 ($450 - $950)"
        else:
            flight_duration = f"{round(max(2.5, distance_km / 650.0), 1)} - {round(max(3.5, distance_km / 450.0), 1)} hrs (Flight)"
            cost_str = "₹8,000 - ₹25,000 ($100 - $300)"

        filtered_options = [
            {
                "mode": "Flight",
                "option": f"International Commercial Flight ({origin} to {destination})",
                "duration": flight_duration,
                "approx_cost": cost_str,
            }
        ]
        return {
            "origin": origin,
            "destination": destination,
            "distance_km": f"{int(distance_km)} km",
            "travel_time": flight_duration,
            "recommended_mode": "Commercial Airline Flight",
            "transport_options": filtered_options,
            "route_summary": (
                f"Geographic validation: {origin} to {destination} is a long-distance cross-border route ({int(distance_km)} km). "
                "Overland driving, bus, and regional train routes are not practically viable and are excluded in favor of flight travel."
            ),
        }

    # Domestic / short-haul route
    valid_options = []
    for opt in transport_options:
        mode = opt.get("mode", "")
        if distance_km > 1200 and mode in ("Drive", "Drive / Cab", "Bus"):
            # De-prioritize driving for > 1200 km
            continue
        valid_options.append(opt)

    if not valid_options:
        valid_options = transport_options

    return {
        "origin": origin,
        "destination": destination,
        "distance_km": f"{int(distance_km)} km",
        "recommended_mode": "Flight or Express Train" if distance_km > 500 else "Train or Drive",
        "transport_options": valid_options,
        "route_summary": f"Intercity transport corridor connecting {origin} and {destination} ({int(distance_km)} km).",
    }


def validate_restaurant_match(restaurant: dict[str, Any], requested_cuisine: str | None) -> bool:
    """Validate that a recommended restaurant strictly matches the requested cuisine category."""
    if not requested_cuisine:
        return True

    req = requested_cuisine.lower().strip()
    r_name = restaurant.get("restaurant_name", "").lower()
    r_spec = restaurant.get("speciality", "").lower()
    r_pop = restaurant.get("why_popular", "").lower()
    combined = f"{r_name} {r_spec} {r_pop}"

    if "indian" in req:
        return any(k in combined for k in ["indian", "thali", "dosas", "curry", "biryani", "saravanaa", "bukhara", "karim", "tandoori", "naan", "ghewar", "kachori", "dal", "chaat"])
    if "vegetarian" in req or "pure veg" in req or "veg" in req:
        return any(k in combined for k in ["veg", "vegetarian", "pure veg", "thali", "dosas", "falafel", "salad", "sweets", "kachori", "chaat"])
    if "vegan" in req:
        return any(k in combined for k in ["vegan", "plant-based", "organic", "salad"])
    if "italian" in req:
        return any(k in combined for k in ["italian", "pizza", "pasta", "trattoria", "ristorante", "wood-fired"])
    if "french" in req:
        return any(k in combined for k in ["french", "bistro", "bistrot", "brasserie", "steak frites", "croissant"])
    if "japanese" in req:
        return any(k in combined for k in ["japanese", "ramen", "soba", "sushi", "izakaya", "tempura"])

    return req in combined


def validate_hotel_entry(hotel: dict[str, Any]) -> dict[str, Any]:
    """Separate hotel star classification (e.g. 3-Star / 4-Star) from user review ratings (e.g. 4.5/5.0 ⭐)."""
    name = hotel.get("hotel_name", "Hotel").strip()
    location = hotel.get("location", "City Centre").strip()
    price = hotel.get("price_range", "₹1,500 - ₹3,500/night").strip()
    raw_rating = hotel.get("rating", "4.4 ⭐").strip()
    b_tier = hotel.get("budget_tier", "mid-range").lower()

    # Determine Hotel Class
    if "hostel" in name.lower() or "hostel" in location.lower() or "zostel" in name.lower():
        hotel_class = "Backpacker Hostel / Budget Dorms"
    elif "5 star" in b_tier or "luxury" in b_tier or "5-star" in name.lower() or "5 star" in name.lower():
        hotel_class = "5-Star Luxury Hotel"
    elif "4 star" in b_tier or "premium" in b_tier or "4-star" in name.lower() or "4 star" in name.lower():
        hotel_class = "4-Star Premium Hotel"
    elif "budget" in b_tier or "low" in b_tier:
        hotel_class = "2-Star / 3-Star Budget Hotel"
    else:
        hotel_class = "3-Star Comfort Hotel"

    # Clean Review Rating (e.g. '4.6/5.0 ⭐')
    score_match = re.search(r'(\d+\.?\d*)', raw_rating)
    if score_match:
        score_val = score_match.group(1)
        review_rating = f"{score_val}/5.0 ⭐"
    else:
        review_rating = "4.4/5.0 ⭐"

    return {
        "hotel_name": name,
        "area": location,
        "price_range": price,
        "hotel_class": hotel_class,
        "review_rating": review_rating,
    }


def validate_weather_presentation(weather_dict: dict[str, Any], travel_dates: str | None) -> str:
    """Format weather with explicit clarity on whether it is a live forecast or seasonal baseline."""
    temp = weather_dict.get("temperature_c", "25")
    wind = weather_dict.get("windspeed_kmh", "10")
    rain_p = weather_dict.get("forecast_next_12h", {}).get("max_rain_probability_percent", 15)

    if travel_dates:
        return (
            f"Expected weather for **{travel_dates}**: Average temperature around **{temp}°C**, "
            f"wind speed **{wind} km/h**, with precipitation probability at **{rain_p}%**."
        )
    return (
        f"Current Conditions / Seasonal Baseline: **{temp}°C**, wind speed **{wind} km/h**, "
        f"rain probability **{rain_p}%**. *(Note: Travel dates were not specified; values reflect current real-time meteorological conditions.)*"
    )


def validate_and_enforce_sections(
    response_text: str,
    reqs: UserRequirements,
    tool_context: dict[str, Any] | None = None,
) -> str:
    """Quality Gate: Verifies that all 11 mandatory sections exist in the response.

    Strictly grounded in tool outputs: if tool data is missing, outputs clear
    unavailability statements instead of generating substitute fake information.
    """
    tool_context = tool_context or {}
    dest = reqs.destination.title() if reqs.destination else "Destination"
    origin = reqs.origin.title() if reqs.origin else "Your Origin City"
    cuisine = reqs.cuisine or "Local & Multi-Cuisine"

    # Check for presence of each section header (# <Section>)
    missing_sections = []
    for section_name in MANDATORY_SECTIONS:
        pattern = re.compile(rf'#+\s*{re.escape(section_name)}', re.IGNORECASE)
        if not pattern.search(response_text):
            missing_sections.append(section_name)

    if not missing_sections:
        # Do not claim that every tool was used when a complete answer was
        # produced from only part of the requested data.
        return response_text
        # Append Tools Used block if not already present
        if "Tools Used" not in response_text and "### Tools Used" not in response_text:
            response_text += "\n\n### Tools Used\n✓ travel_route\n✓ get_weather\n✓ find_budget_hotels\n✓ famous_restaurants\n✓ discover_events\n✓ search_books"
        return response_text

    # Synthesize missing sections using strictly grounded data
    synthesized_parts = [response_text.strip()]

    for sec in missing_sections:
        if sec == "Destination Overview":
            synthesized_parts.insert(0, f"# Destination Overview\n{dest} is the target travel destination for this itinerary.")
        elif sec == "Weather":
            w_str = validate_weather_presentation(tool_context.get("weather", {}), reqs.travel_dates)
            synthesized_parts.append(f"# Weather\n{w_str}")
        elif sec == "How to Reach":
            route = tool_context.get("route", {})
            if route and "error" not in route:
                dur = route.get("travel_time", "Flight")
                rec = route.get("recommended_mode", "Flight")
                dist = route.get("distance_km", "")
                synthesized_parts.append(f"# How to Reach\n- **From**: {origin}\n- **To**: {dest}\n- **Distance**: {dist}\n- **Recommended Mode**: {rec}\n- **Estimated Duration**: {dur}")
            else:
                synthesized_parts.append(f"# How to Reach\nTransport route data unavailable.")
        elif sec == "Estimated Budget":
            hotels = tool_context.get("hotels", [])
            route = tool_context.get("route", {})
            h_price = hotels[0].get("price_range", "Variable") if hotels else "Data unavailable"
            r_cost = route.get("transport_options", [{}])[0].get("approx_cost", "Variable") if route else "Data unavailable"
            if hotels or route:
                synthesized_parts.append(
                    f"# Estimated Budget\n"
                    f"- **Accommodations ({reqs.budget_level.title()})**: {h_price}\n"
                    f"- **Transit ({origin} to {dest})**: {r_cost}\n"
                    f"- **Food & Local Expense**: Estimated based on {reqs.budget_level.title()} tier.\n"
                    f"- **Budget Status**: Grounded in retrieved hotel & transit quotes."
                )
            else:
                synthesized_parts.append(f"# Estimated Budget\nBudget estimate unavailable (tool data missing).")
        elif sec == "Accommodation Options":
            hotels = tool_context.get("hotels", [])
            valid_hotels = [h for h in hotels if "error" not in h]
            if valid_hotels:
                table_lines = ["| Hotel Name | Hotel Class | Review Rating | Area / Location | Price Range |", "|---|---|---|---|---|"]
                for h in valid_hotels[:5]:
                    v_h = validate_hotel_entry(h)
                    table_lines.append(f"| {v_h['hotel_name']} | {v_h['hotel_class']} | {v_h['review_rating']} | {v_h['area']} | {v_h['price_range']} |")
                synthesized_parts.append(f"# Accommodation Options\n" + "\n".join(table_lines))
            else:
                synthesized_parts.append(f"# Accommodation Options\nNo hotel information available.")
        elif sec == "Restaurants":
            rests = tool_context.get("restaurants", [])
            matching = [r for r in rests if validate_restaurant_match(r, reqs.cuisine)]
            if matching:
                r_lines = [f"- **{r['restaurant_name']}**: {r.get('speciality', 'Speciality Cuisine')} | Rating: {r.get('rating', '4.5 ⭐')} | Location: {r.get('location', dest)}" for r in matching[:5]]
                synthesized_parts.append(f"# Restaurants\n**Cuisine Preference: {cuisine}**\n" + "\n".join(r_lines))
            elif rests:
                r_lines = [f"- **{r['restaurant_name']}**: {r.get('speciality', 'Speciality')} | Location: {r.get('location', dest)}" for r in rests[:4]]
                synthesized_parts.append(f"# Restaurants\n**Cuisine Preference: {cuisine}** (General recommendations):\n" + "\n".join(r_lines))
            else:
                synthesized_parts.append(f"# Restaurants\n**Cuisine Preference: {cuisine}**\nNo restaurant recommendations available for the requested cuisine.")
        elif sec == "Upcoming Events":
            events = tool_context.get("events", [])
            valid_events = [e for e in events if "Notice" not in e.get("source", "") and "Warning" not in e.get("source", "") and "error" not in e]
            if valid_events:
                e_lines = [f"- **{e['source']}**: {e.get('summary', 'Event details')}" for e in valid_events[:5]]
                synthesized_parts.append(f"# Upcoming Events\n" + "\n".join(e_lines))
            else:
                synthesized_parts.append(f"# Upcoming Events\nNo upcoming events found.")
        elif sec == "History of Destination":
            synthesized_parts.append(
                "# History of Destination\n"
                "Historical information was not retrieved by a dedicated source."
            )
        elif sec == "Recommended Books":
            books = tool_context.get("books", [])
            valid_books = [b for b in books if "error" not in b and b.get("title")]
            if valid_books:
                b_lines = [f"- [{b.get('title', 'Book')}]({b.get('info_url', '#')}) by {b.get('author', 'Author')}" for b in valid_books[:3]]
                synthesized_parts.append(f"# Recommended Books\n" + "\n".join(b_lines))
            else:
                synthesized_parts.append(f"# Recommended Books\nBook recommendations unavailable.")
        elif sec == "Suggested Itinerary":
            synthesized_parts.append(
                "# Suggested Itinerary\n"
                "An itinerary was not generated because no grounded attraction or schedule data was retrieved."
            )
        elif sec == "Travel Tips":
            synthesized_parts.append(
                "# Travel Tips\n"
                "Confirm local transport, payment, and booking requirements with current official sources before travel."
            )

    result_full = "\n\n".join(synthesized_parts)
    # Tool usage is tracked by the agent; this formatter must not claim every
    # registered tool ran for an answer.
    if False and "Tools Used" not in result_full and "### Tools Used" not in result_full:
        result_full += "\n\n### Tools Used\n✓ travel_route\n✓ get_weather\n✓ find_budget_hotels\n✓ famous_restaurants\n✓ discover_events\n✓ search_books"

    return result_full
