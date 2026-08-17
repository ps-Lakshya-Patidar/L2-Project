# 🧭 PlanPilot: Personal AI Travel & Concierge Agent

PlanPilot is a stateful AI travel planning agent powered by **Google Gemini** (default), **Groq Cloud**, and **Ollama**, the **Model Context Protocol (MCP)**, OpenStreetMap Overpass API, and free public services. It acts as your personal concierge to compile personalized travel itineraries, fetch real-time weather, search spatial hotels & restaurants, compute real-world transport routes, recommend books, and discover live local events.

---

## ✨ Key Features & Capability Matrix

- **🤖 Multi-LLM Provider Support (Google Gemini Default)**: Powered by `gemini-3.6-flash` / `gemini-3.7-flash` with zero rate limit bottlenecks and massive throughput. Also supports Groq (`openai/gpt-oss-20b`, `qwen/qwen3.6-27b`) and local Ollama (`llama3.2:3b`).
- **🏨 Spatial Hotel Discovery (`find_budget_hotels`)**: Queries OpenStreetMap (OSM) Overpass API (`node["tourism"~"hotel|hostel|guest_house"]`) for live stays. Supports dynamic budget tiers (`low`, `mid-range`, `premium`, `luxury`).
- **🛣️ Real-World Route & Geocoding (`travel_route`)**: Validates real-world cities on Earth via Open-Meteo geocoding. Rejects fake/gibberish cities (`asdfgh`, `qwerty`). Computes Haversine Great Circle distances, travel times, transport modes (Train, Bus, Flight, Drive), intercontinental trans-oceanic flight routing, and route summaries.
- **🍽️ Spatial Restaurant Discovery (`famous_restaurants`)**: Uses OpenStreetMap Overpass API (`node["amenity"="restaurant"]["name"]`) and curated heritage dining spots to return authentic local restaurants, cuisines, dietary filters (`vegetarian`, `vegan`, `Italian`), and street addresses.
- **🌤️ Smart Weather Forecasts (`get_weather`)**: Connects to the Open-Meteo API to retrieve current conditions and 12-hour precipitation forecasts.
- **📚 Reliable Book Recommendations (`search_books`)**: Direct query to the Open Library API to find books by topic, title, or author with clickable links.
- **🎟️ Live Event Discovery (`discover_events`)**: Locates concerts, exhibitions, or cultural activities for any city via SerpAPI and DuckDuckGo.
- **🧠 JSON Profile Memory & Departure City Fallback**: Stores user preferences in `PlanPilot/data/user_preferences.json`. When a prompt omits the departure city (e.g., `"Plan a 3-day trip to Jaipur"`), it automatically retrieves `home_city` from JSON memory.
- **📊 Evaluation Metrics & Telemetry Engine**: Tracks token usage (`tiktoken` / API metadata), millisecond latency (`time.monotonic()`), step counts, and real-time cost estimations based on model pricing grids in the Streamlit UI. Automated suite testing via **`pytest`**.
- **🌐 Interactive Streamlit Portal**: Features dynamic provider & model dropdown selectors (Google Gemini, Groq, Ollama), travel vibe goals, profile editing, and live trace logs.

---

## 📐 Evaluation Metrics & Telemetry Tools

PlanPilot monitors and evaluates performance using the following tools and libraries:

1. **Token Usage Metrics**: Extracted from LLM provider metadata (`prompt_tokens`, `completion_tokens`, `total_tokens`) or computed via **`tiktoken`**.
2. **Step Count & Latency Telemetry**: Measured per tool call and per reasoning step using Python's native **`time.monotonic()`** module inside async status callbacks.
3. **Real-time Cost Estimation Engine**: Calculated dynamically using model rate cards (e.g. Google Gemini Free Tier / Groq rate cards) configured in `streamlit_app.py`.
4. **Unit Testing & Code Quality Suite**: Automated unit tests built with **`pytest`** (`tests/test_preferences.py`).

---

## 🏗️ Architecture

PlanPilot uses a client-server architecture based on the Model Context Protocol (MCP) over `stdio` transport.

```
User ──► CLI / Streamlit UI
              │
              ▼
    Stateful Agent Loop (planpilot.agent) ◄──► data/user_preferences.json
              │
       ┌───────┴───────┐
       ▼               ▼
 Google Gemini /      MCP Client Session
 Groq / Ollama        │ (stdio transport protocol)
                       ▼
                MCP Subprocess (planpilot.mcp_server)
                       │
                       ▼
              Registered MCP Tools (6 Total):
              - get_weather         - find_budget_hotels
              - search_books        - travel_route
              - discover_events     - famous_restaurants
                       │
                       ▼
              External APIs / Services:
              (Open-Meteo, OpenStreetMap Overpass, Open Library, SerpAPI, DuckDuckGo)
```

---

## 🔌 MCP Tool API Reference (6 Active Tools)

PlanPilot exposes 6 active tool interfaces on the MCP Server:

### 1. `find_budget_hotels`
Search for budget, mid-range, or luxury hotels and accommodations.
```json
{
  "city": "Jaipur",
  "budget": "low | mid-range | premium | luxury"
}
```

### 2. `travel_route`
Calculate real-world distance (Haversine), travel durations, and transport options between two cities. Rejects fake/gibberish city names.
```json
{
  "source": "Ahmedabad",
  "destination": "Jaipur"
}
```

### 3. `famous_restaurants`
Discover famous local dining spots, bistros, and regional specialities using OpenStreetMap Overpass API.
```json
{
  "city": "Indore"
}
```

### 4. `get_weather`
Fetch current weather and 12-hour precipitation forecast for a city.
```json
{
  "city": "Paris"
}
```

### 5. `search_books`
Search for book recommendations and metadata using the Open Library API.
```json
{
  "query": "science fiction"
}
```

### 6. `discover_events`
Discover live events, exhibitions, concerts, or activities happening in a city.
```json
{
  "city": "Mumbai"
}
```

---

## ⚙️ How the Process Works (Under the Hood)

1. **Handshake**: The agent client spawns the MCP server subprocess using stdio transport.
2. **Preference & Departure City Auto-Resolution**: Reads `PlanPilot/data/user_preferences.json`. If a travel query specifies a destination but omits the source city, `home_city` is automatically passed as the departure location.
3. **Reasoning Loop**: The LLM determines necessary tool calls, executes them via MCP client session, and truncates raw context (`[:1500]`) to protect against Groq 6,000 TPM rate limits.
4. **Self-Reflection (QA) Pass**: Sends draft outputs to a reflection reviewer. Single-topic queries receive clean, direct answers; full itineraries are structured with complete markdown sections.

---

## 🚀 How to Run the Project

### 1. Installation
```bash
# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1   # On Windows

# Install dependencies and editable package
pip install -r requirements.txt
pip install -e .
```

### 2. Configuration
Create a `.env` file:
```env
LLM_PROVIDER=groq
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
```

### 3. Execution Commands

#### **Streamlit Web Portal**
```bash
planpilot ui
# Or: python -m streamlit run src/planpilot/ui/streamlit_app.py
```

#### **Stateful Interactive CLI REPL**
```bash
planpilot query
```

#### **Single Query Command**
```bash
planpilot query "Plan a 3-day trip to Jaipur"
```

#### **Unit Tests**
```bash
python -m pytest tests/test_preferences.py
```

---

## 📁 File Structure Overview

```
PlanPilot/
├── data/
│   └── user_preferences.json    # Persistent user JSON profile
├── docs/
│   ├── API_DOCUMENTATION.md      # Full API reference guide
│   ├── PROJECT_PRESENTATION_GUIDE.md
│   └── REVIEW_PREPARATION.md
├── logs/
│   └── planpilot.log             # Application execution logs
├── src/
│   └── planpilot/
│       ├── agent/                # Agent loop & reflection QA pass
│       ├── mcp_server/           # Stdio MCP Server tool registry
│       ├── tools/                # Service implementations & APIs
│       ├── ui/                   # Streamlit web portal
│       └── utils/                # Config, Logger, Preferences
├── tests/                        # Pytest suite
├── README.md
└── pyproject.toml
```
