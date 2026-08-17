"""User preference memory for PlanPilot.

Stores and retrieves user preferences (interests, dislikes, home city, goal vibe)
as a lightweight JSON file so the agent remembers you across sessions.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from planpilot.utils.config import _PROJECT_ROOT

# Stored in data/user_preferences.json inside the project root directory
_PREF_FILE = _PROJECT_ROOT / "data" / "user_preferences.json"

_DEFAULTS: dict[str, Any] = {
    "home_city": "",
    "interests": [],          # e.g. ["rock concerts", "sci-fi books", "hiking"]
    "dislikes": [],           # e.g. ["horror", "crowded places"]
    "preferred_budget": "any",  # "budget", "mid-range", "premium", "any"
    "weekend_goal": "Explore",  # "Relax", "Learn", "Explore", "Socialize"
    "indoor_preference": False,  # True = prefer indoor activities
    "custom_notes": "",       # Free-text notes the agent may learn dynamically
}


def _ensure_dir() -> None:
    _PREF_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_preferences() -> dict[str, Any]:
    """Load user preferences from disk. Returns defaults if file doesn't exist."""
    _ensure_dir()
    if not _PREF_FILE.exists():
        return dict(_DEFAULTS)
    try:
        data = json.loads(_PREF_FILE.read_text(encoding="utf-8"))
        # Merge with defaults so new keys are always present
        merged = dict(_DEFAULTS)
        merged.update(data)
        return merged
    except Exception:
        return dict(_DEFAULTS)


def save_preferences(prefs: dict[str, Any]) -> None:
    """Persist preferences to disk."""
    _ensure_dir()
    _PREF_FILE.write_text(json.dumps(prefs, indent=2, ensure_ascii=False), encoding="utf-8")


def get_preference(key: str, default: Any = None) -> Any:
    """Retrieve a single preference value by key."""
    return load_preferences().get(key, default)


def set_preference(key: str, value: Any) -> None:
    """Update a single preference value and persist."""
    prefs = load_preferences()
    prefs[key] = value
    save_preferences(prefs)


def add_interest(interest: str) -> None:
    """Add an interest to the user's interests list (deduplicating)."""
    prefs = load_preferences()
    interests: list[str] = prefs.get("interests", [])
    if interest.lower() not in [i.lower() for i in interests]:
        interests.append(interest)
        prefs["interests"] = interests
        save_preferences(prefs)


def add_dislike(dislike: str) -> None:
    """Add a dislike to the user's dislikes list (deduplicating)."""
    prefs = load_preferences()
    dislikes: list[str] = prefs.get("dislikes", [])
    if dislike.lower() not in [d.lower() for d in dislikes]:
        dislikes.append(dislike)
        prefs["dislikes"] = dislikes
        save_preferences(prefs)


def auto_update_preferences_from_text(text: str) -> dict[str, Any]:
    """Parse user text for preference declarations (e.g. 'I live in Indore', 'My home city is Ahmedabad')
    and auto-save them to user_preferences.json.
    """
    import re
    prefs = load_preferences()
    updated = False

    city_match = re.search(
        r"\b(?:i live in|i live at|i am from|i'm from|my home city is|my base city is|i am based in|i'm based in|starting from|start from)\s+([a-zA-Z]{2,20}(?:\s+[a-zA-Z]{2,20})?)",
        text,
        re.IGNORECASE,
    )
    if city_match:
        extracted = city_match.group(1).strip()
        for sw in [" and", " with", " for", " but", " so", " to", " in", " on", ",", "."]:
            if sw in extracted.lower():
                extracted = extracted[:extracted.lower().find(sw)]
        extracted_city = extracted.strip().title()
        if extracted_city and extracted_city.lower() not in ("a", "the", "my", "this", "there", "here"):
            prefs["home_city"] = extracted_city
            updated = True

    # Extract Dietary / Notes
    if "vegetarian" in text.lower() and "vegetarian" not in prefs.get("custom_notes", "").lower():
        notes = prefs.get("custom_notes", "")
        prefs["custom_notes"] = (notes + " Vegetarian.").strip()
        updated = True

    if updated:
        save_preferences(prefs)

    return prefs


def build_preference_context(prefs: dict[str, Any] | None = None) -> str:
    """Build a concise natural-language string that can be injected into any LLM prompt.
    
    Example output:
      User Profile: Home city: Indore. Departure City Fallback: Indore. Weekend goal: Explore.
      Interests: rock concerts, hiking. Dislikes: horror movies.
      Budget preference: mid-range. Prefers indoor activities: No.
      Notes: Vegetarian.
    """
    if prefs is None:
        prefs = load_preferences()

    parts: list[str] = []
    home_city = prefs.get("home_city")
    if home_city:
        parts.append(f"Home/Departure city: {home_city}.")
        parts.append(f"DEPARTURE CITY FALLBACK: If the user query specifies a destination (e.g. 'Plan a trip to Jaipur') but omits the starting/source city, automatically use '{home_city}' as the departure city for travel_route and itinerary planning.")

    if prefs.get("weekend_goal"):
        parts.append(f"Weekend goal/Vibe: {prefs['weekend_goal']}.")
    if prefs.get("interests"):
        parts.append(f"Interests: {', '.join(prefs['interests'])}.")
    if prefs.get("dislikes"):
        parts.append(f"Dislikes: {', '.join(prefs['dislikes'])}.")
    if prefs.get("preferred_budget") and prefs["preferred_budget"] != "any":
        parts.append(f"Budget preference: {prefs['preferred_budget']}.")
    if prefs.get("indoor_preference"):
        parts.append("Prefers indoor activities: Yes.")
    if prefs.get("custom_notes"):
        parts.append(f"Notes: {prefs['custom_notes']}.")

    if not parts:
        return ""
    return "Stored User Preferences JSON Profile:\n" + "\n".join(parts)

