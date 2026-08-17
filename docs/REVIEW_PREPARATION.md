# 🧭 PlanPilot: Review Preparation Guide

This guide is compiled to help you prepare for a project review, detailing the architecture, the recent engineering upgrades, robustness modifications, evaluation metrics framework, and key technical talking points for **PlanPilot**.

---

## 🛠️ Table of Contents
1. [Core Features & Pitch](#-core-features--pitch)
2. [Architecture & Protocol Flow](#-architecture--protocol-flow)
3. [6 Active MCP Tools](#-6-active-mcp-tools)
4. [Evaluation Metrics & Telemetry Framework](#-evaluation-metrics--telemetry-framework)
5. [Robustness & Edge-Case Engineering](#-robustness--edge-case-engineering)
6. [Codebase Map (Critical Files)](#-codebase-map-critical-files)
7. [Potential Review Questions & Answers](#-potential-review-questions--answers)

---

## ⚡ Core Features & Pitch

**PlanPilot** is a stateful, fully local/cloud AI travel planning agent concierge that translates natural language prompts into personalized travel itineraries. It combines:
*   **LLM Reasoning**: Ollama (local) or Groq Cloud (remote with model selector).
*   **Model Context Protocol (MCP)**: An isolated stdio subprocess protocol for running 6 active tools.
*   **Persistent Preference Memory**: Custom JSON profile store (`PlanPilot/data/user_preferences.json`) providing departure city auto-fallback, budget matching, and interest alignment.
*   **Real-world APIs & Spatial Search**: OpenStreetMap Overpass API (Hotels & Restaurants), Open-Meteo Geocoding & Weather, Open Library (Books), and SerpAPI/DuckDuckGo (Events).

---

## 🏗️ Architecture & Protocol Flow

```
                  +-----------------------------------+
                  |      CLI / Streamlit Portal       |
                  +-----------------+-----------------+
                                    |
                                    v
                  +-----------------+-----------------+
                  |   Agent Orchestrator (agent.py)   |
                  +--------+-----------------+--------+
                           |                 |
            [Ollama / Groq Cloud]            v
                           |     +-----------+-----------+
                           |     |   User Preference     |
                           |     |  Engine (preferences) |
                           |     +-----------------------+
                           v
                  +--------+-----------------+
                  |    MCP Client Session    |
                  +-----------------+--------+
                                    | (stdio transport)
                                    v
                  +-----------------+-----------------+
                  |    MCP Server Subprocess (mcp)    |
                  +-----------------+--------+--------+
                                    |
         +----------+----------+----+-----+----------+----------+
         |          |          |          |          |          |
         v          v          v          v          v          v
   [get_weather] [books]    [events]   [hotels]   [routes] [restaurants]
```

---

## 🚀 6 Active MCP Tools

1. **`find_budget_hotels(city, budget)`**: OpenStreetMap Overpass API (`node["tourism"~"hotel|hostel|guest_house"]`).
2. **`travel_route(source, destination)`**: Open-Meteo Geocoding city verification & Haversine Great Circle distance calculation.
3. **`famous_restaurants(city)`**: OpenStreetMap Overpass API (`node["amenity"="restaurant"]["name"]`).
4. **`get_weather(city)`**: Open-Meteo current weather and 12-hour precipitation forecast.
5. **`search_books(query)`**: Open Library API metadata search.
6. **`discover_events(city, query)`**: SerpAPI / DuckDuckGo live event discovery.

---

## 📊 Evaluation Metrics & Telemetry Framework

The project evaluates performance, latency, cost, and code quality using the following tools and libraries:

1. **Token Tracking**: **`tiktoken`** library and LLM provider metadata (`prompt_tokens`, `completion_tokens`, `total_tokens`).
2. **Execution Latency & Step Tracking**: Measured using Python's native **`time.monotonic()`** module inside async status callbacks.
3. **Cost Telemetry Engine**: Calculated dynamically via model rate cards defined in `agent.py` multiplying tokens by rate limits.
4. **Unit Test Suite**: **`pytest`** (`tests/test_preferences.py`).

---

## 🗺️ Codebase Map (Critical Files)

| File | Responsibilities |
| :--- | :--- |
| `src/planpilot/agent/agent.py` | Agent loop, preference injection, departure fallback, reflection QA pass |
| `src/planpilot/mcp_server/server.py` | MCP Server stdio entry point, tool registration for all 6 active tools |
| `src/planpilot/tools/services.py` | Implementation of OpenStreetMap Overpass API, Haversine distance, weather, books, events |
| `src/planpilot/utils/preferences.py` | Reads/writes `PlanPilot/data/user_preferences.json`, auto-extracts preferences |
| `src/planpilot/utils/logger.py` | Dual logging to console and `PlanPilot/logs/planpilot.log` |
| `src/planpilot/ui/streamlit_app.py` | Dark-themed Streamlit portal, model dropdown, travel goals, telemetry |

---

## ❓ Potential Review Questions & Answers

**Q: What tools or libraries are used for evaluation metrics?**
> **A:** We use **`tiktoken`** and API response metadata for token tracking, Python's **`time.monotonic()`** for millisecond step latency, custom rate cards in `agent.py` for cost estimation, and **`pytest`** for automated unit test validation.

**Q: How do you handle non-existent or fake city names in travel routes?**
> **A:** `travel_route` calls Open-Meteo geocoding for both cities. If either city returns 0 results on Earth, the tool returns an explicit error (`Source city 'asdfgh' not found on Earth. Please check city spelling.`), preventing hallucinations.
