"""Tests for user preference management."""

import pytest
from planpilot.utils.preferences import (
    auto_update_preferences_from_text,
    build_compact_preference_context,
    build_preference_context,
    load_preferences,
    save_preferences,
)


def test_preferences_save_and_load(tmp_path, monkeypatch):
    test_file = tmp_path / "user_preferences.json"
    monkeypatch.setattr("planpilot.utils.preferences._PREF_FILE", test_file)

    prefs = {
        "home_city": "Indore",
        "interests": ["rock concerts", "hiking"],
        "dislikes": ["horror"],
        "preferred_budget": "mid-range",
        "weekend_goal": "Explore",
        "indoor_preference": False,
        "custom_notes": "Vegetarian",
    }
    save_preferences(prefs)

    loaded = load_preferences()
    assert loaded["home_city"] == "Indore"
    assert "rock concerts" in loaded["interests"]
    assert loaded["custom_notes"] == "Vegetarian"


def test_auto_update_preferences_from_text(tmp_path, monkeypatch):
    test_file = tmp_path / "user_preferences.json"
    monkeypatch.setattr("planpilot.utils.preferences._PREF_FILE", test_file)

    text = "I live in Jaipur and I am Vegetarian"
    auto_update_preferences_from_text(text)

    loaded = load_preferences()
    assert loaded.get("home_city") == "Jaipur"
    assert "Vegetarian" in loaded.get("custom_notes", "")


def test_build_compact_preference_context():
    prefs = {
        "home_city": "Indore",
        "interests": ["hiking"],
        "dislikes": [],
        "preferred_budget": "mid-range",
        "weekend_goal": "Explore",
        "indoor_preference": False,
        "custom_notes": "Vegetarian",
    }
    ctx = build_compact_preference_context(prefs)
    assert "home=Indore" in ctx
    assert "budget=mid-range" in ctx
    assert "notes=Vegetarian" in ctx
