import pytest
from planpilot.utils.validation import (
    UserRequirements,
    extract_requirements,
    validate_transportation,
    validate_restaurant_match,
    validate_hotel_entry,
    validate_and_enforce_sections,
    MANDATORY_SECTIONS,
)

def test_extract_requirements_full():
    query = 'Plan a trip to Paris from Ahmedabad including weather, budget hotels, Indian food, history and books.'
    reqs = extract_requirements(query)
    assert reqs.origin.lower() == 'ahmedabad'
    assert reqs.destination.lower() == 'paris'
    assert reqs.weather is True
    assert reqs.budget_hotels is True
    assert reqs.cuisine == 'Indian'
    assert reqs.history is True
    assert reqs.books is True

def test_extract_requirements_fallback_origin():
    query = 'Plan a 3-day trip to Jaipur with vegetarian food'
    prefs = {'home_city': 'Indore'}
    reqs = extract_requirements(query, user_prefs=prefs)
    assert reqs.origin.lower() == 'indore'
    assert reqs.destination.lower() == 'jaipur'
    assert reqs.cuisine == 'Vegetarian'

def test_geographic_validation_international():
    options = [
        {'mode': 'Flight', 'option': 'International Flight', 'duration': '10 hrs', 'approx_cost': '₹50,000'},
        {'mode': 'Drive', 'option': 'Drive via NH', 'duration': '120 hrs', 'approx_cost': '₹80,000'},
        {'mode': 'Train', 'option': 'Local Train', 'duration': '100 hrs', 'approx_cost': '₹10,000'},
    ]
    res = validate_transportation(
        origin='Ahmedabad, India',
        destination='Paris, France',
        distance_km=6800,
        is_different_country=True,
        transport_options=options
    )
    modes = [o['mode'] for o in res['transport_options']]
    assert 'Flight' in modes
    assert 'Drive' not in modes
    assert 'Train' not in modes

def test_validate_restaurant_match():
    r1 = {'restaurant_name': 'Saravanaa Bhavan Paris', 'speciality': 'South Indian Vegetarian', 'why_popular': 'Indian thali'}
    r2 = {'restaurant_name': 'Bistrot Paul Bert', 'speciality': 'French Steak Frites', 'why_popular': 'Classic bistro'}
    assert validate_restaurant_match(r1, 'Indian') is True
    assert validate_restaurant_match(r2, 'Indian') is False

def test_validate_hotel_entry():
    raw_hotel = {
        'hotel_name': 'Zostel Jaipur',
        'location': 'MI Road, Jaipur (Hostel)',
        'price_range': '₹800 - ₹1,500/night',
        'rating': '4.6 ⭐'
    }
    validated = validate_hotel_entry(raw_hotel)
    assert 'hotel_class' in validated
    assert 'review_rating' in validated
    assert validated['hotel_class'] != validated['review_rating']
