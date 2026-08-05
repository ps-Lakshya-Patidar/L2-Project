"""User preference memory for PlanPilot.

Stores and retrieves user preferences (interests, dislikes, home city, goal vibe)
as a lightweight JSON file so the agent remembers you across sessions.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Stored alongside the .env file at the project root
_PREF_FILE = Path.home() / ".planpilot" / "user_preferences.json"

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


def build_preference_context(prefs: dict[str, Any] | None = None) -> str:
    """Build a concise natural-language string that can be injected into any LLM prompt.
    
    Example output:
      User Profile: Home city: Indore. Weekend goal: Explore.
      Interests: rock concerts, hiking. Dislikes: horror movies.
      Budget preference: mid-range. Prefers indoor activities: No.
      Notes: Vegetarian.
    """
    if prefs is None:
        prefs = load_preferences()

    parts: list[str] = []
    if prefs.get("home_city"):
        parts.append(f"Home city: {prefs['home_city']}.")
    if prefs.get("weekend_goal"):
        parts.append(f"Weekend goal: {prefs['weekend_goal']}.")
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
    return "User Profile: " + " ".join(parts)
