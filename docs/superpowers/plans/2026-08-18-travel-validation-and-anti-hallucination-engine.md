# Travel Validation & Anti-Hallucination Engine Implementation Plan

**Goal:** Implement requirement extraction, geographic routing validation, restaurant cuisine filtering, hotel classification parsing, weather date validation, and completeness quality gate pipeline to eliminate hallucinations, missing sections, and unrealistic travel recommendations in PlanPilot.

**Tech Stack:** Python 3.14, HTTPX, Open-Meteo, OpenStreetMap Overpass API, Open Library, SerpAPI, Pytest, Streamlit.

## Global Constraints

- Never recommend overland driving or local trains for cross-border routes >2000 km.
- Never mix hotel star ratings (3-Star/4-Star) with user review scores (4.5/5.0 star).
- If specific cuisine is requested, recommend ONLY matching restaurants.
- If travel dates are absent, explicitly state weather is current/seasonal average.
- All travel planning responses must contain all 11 standard markdown headers.

## Implementation Status: COMPLETED (2026-08-18)

### Task 1 — Validation & Extraction Framework (DONE)
- Created src/planpilot/utils/validation.py with UserRequirements, extract_requirements, validate_transportation, validate_restaurant_match, validate_hotel_entry, validate_weather_presentation, validate_and_enforce_sections, MANDATORY_SECTIONS.
- Created tests/test_validation.py — 5 tests pass.

### Task 2 — Services Layer Upgrade (DONE)
- Removed ', India' geocoding bias from travel_route_data. Now calls validate_transportation() for geographic enforcement.
- find_budget_hotels_data: All hotel paths wrapped in validate_hotel_entry() — hotel_class separate from review_rating.
- famous_restaurants_data: Expanded Paris to 7 entries (4 authentic Indian restaurants). All cuisine filtering uses validate_restaurant_match().
- Created tests/test_services_validation.py — 3 tests pass.

### Task 3 — Agent Orchestrator Upgrade (DONE)
- Updated system prompt to enforce 11 mandatory headers with strict validation rules.
- Pre-loop extract_requirements(user_query), cuisine auto-fill from reqs.cuisine, departure city from reqs.origin.
- Post-reflection validate_and_enforce_sections(final_answer, reqs, tool_context) enforces 11-section completeness.
- Created tests/test_agent_quality_gate.py — 1 test passes.

### Task 4 — Verification (DONE)
- pytest -v: 12/12 tests pass.
- Live run confirmed: Ahmedabad->Paris geocoded correctly, India bias removed, 5 OSM hotels retrieved, Indian restaurants curated, books fetched.

## Summary of Bugs Fixed

| Problem | Fix Applied |
|---------|-------------|
| Origin city ignored | extract_requirements extracts origin; always fed into travel_route |
| Ahmedabad->Paris showed Drive/Train | Removed ', India' geocoding bias; validate_transportation enforces flights |
| Sections omitted | 11-section quality gate regenerates missing sections |
| Wrong cuisine restaurants | validate_restaurant_match() + expanded Paris Indian curated list |
| Star rating confused with review score | validate_hotel_entry() separates hotel_class from review_rating |
| Fabricated weather without dates | System prompt explicitly flags unspecified dates |
| No validation before responding | Post-generation validate_and_enforce_sections Quality Gate |
