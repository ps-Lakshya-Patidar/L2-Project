# 🧭 PlanPilot: Complete Project Presentation & Explanation Guide

This guide is designed to walk you through explaining the entire project to a reviewer from start to finish. It covers the **Problem**, the **Solution**, the **Architecture**, and key **Concept Explanations** (MCP, Ollama, OpenStreetMap Overpass, Pydantic, Evaluation Telemetry, etc.).

---

## 📢 Section 1: The Presentation Pitch (Start Here)

### 1. The Problem Statement
*   **Context**: LLMs (Large Language Models) are powerful, but suffer from three key limitations:
    1.  **Knowledge Cutoff**: They lack real-time data (e.g., current weather, live events, or spatial hotel/restaurant availability).
    2.  **No Local Preference State**: They don't remember user profile preferences (interests, dislikes, home city, budget) across different sessions.
    3.  **Hallucinations**: When asked for routes or hotels, LLMs tend to invent fake travel durations, non-existent cities, or fictitious places.
*   **The Goal**: Build a fully local, privacy-respecting AI travel concierge (**PlanPilot**) that connects directly to real-world tools, validates cities, remembers user preferences, and generates verified itineraries.

### 2. The Solution (What We Built)
We built **PlanPilot**, an AI Travel Planner & Concierge consisting of:
*   **An Agent Loop** with a self-reflection pass that acts as a quality gate to verify recommendations against raw API payloads.
*   **An MCP Tool Server** with 6 registered active tools:
    - `find_budget_hotels` (OpenStreetMap Overpass API)
    - `travel_route` (Open-Meteo Geocoding & Haversine Distance Engine)
    - `famous_restaurants` (OpenStreetMap Overpass API)
    - `get_weather` (Open-Meteo Forecasts)
    - `search_books` (Open Library API)
    - `discover_events` (SerpAPI / DuckDuckGo)
*   **A User Preference Engine** that stores profile memory in `PlanPilot/data/user_preferences.json` and automatically supplies `home_city` when a travel query omits the departure location.
*   **A Project Logger** writing rotating execution traces to `PlanPilot/logs/planpilot.log`.
*   **An Evaluation & Telemetry Framework**: Uses **`tiktoken`** and LLM response metadata for token tracking, **`time.monotonic()`** for step latency, and **`pytest`** for automated unit test validation.
*   **An Interactive Streamlit Dashboard UI** complete with Groq model dropdown selectors, token telemetry, step counts, and live tool traces.

---

## 🏗️ Section 2: How Things Work (Architecture & Data Flow)

Explain this sequence diagram to the reviewer:

```
[User Interface]           [Agent Loop]            [MCP Server]               [APIs / Services]
      |                         |                       |                            |
      |--- 1. User Prompt ----->|                       |                            |
      | ("Trip to Jaipur")      |--- 2. Load Prefs ---->| data/user_preferences.json |
      |                         | (Fills home_city=Indore)                           |
      |                         |--- 3. Tool Calls ---->|                            |
      |                         | (travel_route, hotels)|--- 4. Query Spatial ------>| (OSM Overpass API)
      |                         |                       |<-- 5. Return Stays --------| (Open-Meteo)
      |                         |<-- 6. Raw Data -------|                            |
      |                         |                       |                            |
      |                         |=== 7. Reflection QA ==|                            |
      |<-- 8. Final Itinerary --|                       |                            |
```

### Codebase Execution Flow:
1.  **Handshake**: Client starts the MCP server (`server.py`) as a subprocess using **stdio** transport protocol.
2.  **Tool Enrollment**: Server registers all 6 tools with schemas and parameter definitions.
3.  **Departure City Auto-Fallback**: If prompt says `"Plan a trip to Jaipur"`, the agent reads `home_city` from `data/user_preferences.json` and automatically sets `source="Indore"`.
4.  **Spatial & Distance Execution**:
    - `travel_route` geocodes both cities via Open-Meteo. Rejects fake cities (`asdfgh`, `qwerty`) with explicit errors and computes Haversine distance in km for valid cities.
    - `find_budget_hotels` & `famous_restaurants` query OpenStreetMap Overpass API within spatial radiuses.
5.  **Reflection QA Pass**: Reflection reviewer formats single-domain queries directly without filler headers, or compiles full multi-day travel plans.

---

## 📊 Section 3: Evaluation Metrics & Telemetry Framework

When presenting to a technical reviewer, explain how performance and cost are evaluated:

1. **Token Tracking**: Uses **`tiktoken`** and LLM provider metadata (`prompt_tokens`, `completion_tokens`, `total_tokens`) returned in completion payloads.
2. **Latency & Step Counts**: Measured per reasoning step and tool invocation using Python's native **`time.monotonic()`** module.
3. **Cost Telemetry**: Calculated dynamically via model rate cards defined in `agent.py` multiplying tokens by rate limits.
4. **Automated Unit Testing**: Built using **`pytest`** (`tests/test_preferences.py`).

---

## 💎 Section 4: Engineering Highlights & Edge-Case Fixes

*   **City Geocoding Verification**: Prevents hallucinated travel routes for fake/gibberish city names like `asdfgh` / `qwerty` by returning clean error notifications.
*   **Groq TPM Rate Limit Management**: Context string truncation (`[:1500]`) on raw tool outputs keeps prompt turns under 1,200 tokens, staying well below Groq's 6,000 TPM limit.
*   **Project Root Self-Containment**: Storing `user_preferences.json` in `PlanPilot/data/` and logs in `PlanPilot/logs/` ensures the project is 100% self-contained for code reviews.
