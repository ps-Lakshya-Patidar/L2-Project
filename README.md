# 🧭 PlanPilot: Personal AI Travel & Concierge Agent

PlanPilot is a stateful AI travel planning agent powered by **OpenRouter** (default) and **Ollama**, the **Model Context Protocol (MCP)**, OpenStreetMap Overpass API, and free public services. It acts as your personal concierge to compile personalized travel itineraries, fetch real-time weather, search spatial hotels & restaurants, compute real-world transport routes, recommend books, and discover live local events.

---

## ✨ Key Features & Capability Matrix

- **🤖 Multi-LLM Provider Support**: Powered by **OpenRouter** (free models like `meta-llama/llama-3.3-70b-instruct:free`, `deepseek/deepseek-r1:free`, `nvidia/nemotron-super-120b:free`) and local **Ollama** (`llama3.2:3b`). Automatically falls back across providers.
- **🏨 Hotel Discovery with 3-Tier Fallback (`find_budget_hotels`)**: Queries OpenStreetMap Overpass API → DuckDuckGo Search → **Curated Destination Knowledge** (7 cities, never fabricated). Supports budget tiers: `low`, `mid-range`, `premium`, `luxury`.
- **🛣️ Real-World Route & Geocoding (`travel_route`)**: Validates real-world cities via Open-Meteo geocoding. Rejects fake/gibberish city names. Computes Haversine Great Circle distances, travel times, transport modes (Train, Bus, Flight, Drive), and intercontinental routing.
- **🍽️ Restaurant Discovery with 3-Tier Fallback (`famous_restaurants`)**: OpenStreetMap → DuckDuckGo → **Curated Culinary Knowledge** (7 cities, cuisine-filtered, never fabricated). Supports dietary filters (`vegetarian`, `vegan`, `Indian`, etc.).
- **🌤️ Smart Weather Forecasts (`get_weather`)**: Connects to the Open-Meteo API to retrieve current conditions and 12-hour precipitation forecasts.
- **📚 Book Recommendations (`search_books`)**: Direct query to the Open Library API to find books by topic, title, or author with clickable links.
- **🎟️ Live Event Discovery (`discover_events`)**: Locates concerts, exhibitions, or cultural activities for any city via DuckDuckGo.
- **🧠 JSON Profile Memory & Departure City Fallback**: Stores user preferences in `data/user_preferences.json`. When a prompt omits the departure city, it automatically retrieves `home_city` from JSON memory.
- **🔀 XML Tool-Call Parser (Nemotron / Qwen compatible)**: Parses `<tool_call>`, `<function=name>`, `<parameter=key>` XML syntax emitted by some free OpenRouter models — no tool calls leak into the final answer.
- **🛡️ Hardened Response Cache**: Never caches raw tool call leaks, `"Data unavailable"`, `"No hotel information"`, or responses under 30 characters. Disk cache with strict per-destination keys prevents cross-query pollution.
- **📊 Evaluation Metrics & Telemetry**: Tracks token usage, millisecond latency, step counts, actual API cost, and **estimated production cost** (if scaled to paid models) — visible in both the CLI and Streamlit UI.
- **🌐 Interactive Streamlit Portal**: Dynamic provider & model selectors, travel vibe goals, profile editing, and live trace logs.

---

## 📐 Evaluation Metrics

| Metric | How it's measured |
|---|---|
| **Token Usage** | `prompt_tokens` / `completion_tokens` from API metadata or `tiktoken` |
| **Latency** | `time.monotonic()` per tool call and per reasoning step |
| **Actual Cost** | Live API cost from OpenRouter usage headers |
| **Est. Production Cost** | Estimated cost if run on GPT-4o / Claude 3.5 Sonnet pricing |
| **Step Count** | Number of tool calls + reflection passes per query |

---

## 🏗️ Architecture

```
User ──► CLI / Streamlit UI
              │
              ▼
    Stateful Agent Loop (planpilot.agent) ◄──► data/user_preferences.json
              │
       ┌──────┴──────────────────┐
       ▼                         ▼
 OpenRouter / Ollama        MCP Client Session
 (XML + JSON tool parsers)  (stdio transport)
                                 │
                                 ▼
                      MCP Subprocess (planpilot.mcp_server)
                                 │
                     ┌───────────┼───────────┐
                     ▼           ▼           ▼
              Overpass API   DuckDuckGo   Curated JSON
              (OSM hotels,   (search      (data/curated_hotels.json
               restaurants)   fallback)    data/curated_restaurants.json)
                     │
                     ▼
           Other Free APIs:
           Open-Meteo · Open Library · DuckDuckGo Events
```

---

## 🔌 MCP Tool Reference (6 Active Tools)

### 1. `find_budget_hotels`
```json
{ "city": "New York", "budget": "low | mid-range | premium | luxury" }
```
Fallback chain: **OpenStreetMap Overpass → DuckDuckGo → Curated Hotels JSON**

### 2. `famous_restaurants`
```json
{ "city": "Udaipur", "query": "Indian food" }
```
Fallback chain: **OpenStreetMap Overpass → DuckDuckGo → Curated Restaurants JSON**

### 3. `travel_route`
```json
{ "source": "Ahmedabad", "destination": "New York" }
```
Real geocoding validation — rejects fake cities. Haversine distance + transport modes.

### 4. `get_weather`
```json
{ "city": "Paris" }
```
Current conditions + 12-hour precipitation forecast via Open-Meteo.

### 5. `search_books`
```json
{ "query": "New York history" }
```
Open Library API — real books with author, year, and clickable links.

### 6. `discover_events`
```json
{ "city": "New York", "query": "music concerts" }
```
Live events via DuckDuckGo search — concerts, exhibitions, comedy shows, and more.

---

## ⚙️ How It Works (Under the Hood)

1. **MCP Handshake**: The agent spawns the MCP server subprocess over `stdio` transport and registers all 6 tools.
2. **Preference Auto-Resolution**: Reads `data/user_preferences.json`. If a query omits the departure city, `home_city` is automatically used.
3. **Tool Call Parsing (3 Strategies)**:
   - Strategy 1: JSON block `[{"name": ..., "arguments": {...}}]`
   - Strategy 2: Parenthesized calls `tool_name(key=value, ...)`
   - Strategy 3: XML tags `<tool_call><function=name><parameter=key>value</parameter></function></tool_call>` — for Nemotron/Qwen models
4. **3-Tier Fallback**: For hotels and restaurants — OSM Overpass → DuckDuckGo → Curated JSON (guaranteed non-empty, non-fabricated response).
5. **Response Cache Guard**: Responses are only cached if they are ≥30 characters, contain no raw tool call syntax, and are not error strings.
6. **Self-Reflection (QA) Pass**: Draft output is reviewed for completeness. Single-topic queries get clean direct answers; full itineraries get structured markdown.
7. **Quality Gate**: XML tags, tool call blocks, and junk strings are stripped before the final answer is shown.

---

## 🚀 Getting Started

### 1. Clone & Install

```bash
git clone https://github.com/ps-Lakshya-Patidar/L2-Project.git
cd L2-Project/PlanPilot

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1      # Windows
# source .venv/bin/activate     # macOS / Linux

# Install dependencies and package
pip install -r requirements.txt
pip install -e .
```

### 2. Configure Environment

Create a `.env` file in the `PlanPilot/` directory:

```env
# Required: OpenRouter (free tier available at openrouter.ai)
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=your_openrouter_api_key_here
OPENROUTER_MODEL=meta-llama/llama-3.3-70b-instruct:free

# Optional: Ollama (local, no API key needed)
# LLM_PROVIDER=ollama
# OLLAMA_MODEL=llama3.2:3b
```

> Get a free OpenRouter API key at [openrouter.ai](https://openrouter.ai) — no credit card required for free models.

### 3. Run

#### **Streamlit Web Portal** (recommended)
```bash
planpilot ui
# or: python -m streamlit run src/planpilot/ui/streamlit_app.py
```

#### **Interactive CLI REPL**
```bash
planpilot query
```

#### **Single Query**
```bash
planpilot query "Plan a trip from Ahmedabad to New York with Indian food restaurants and budget hotels"
```

---

## 📁 Project Structure

```
PlanPilot/
├── data/
│   ├── curated_hotels.json       # Verified hotels for 7 cities (no prices/ratings)
│   ├── curated_restaurants.json  # Verified restaurants for 7 cities
│   └── user_preferences.json     # Your personal profile (gitignored, local only)
├── logs/
│   └── planpilot.log             # Application logs (gitignored)
├── src/
│   └── planpilot/
│       ├── agent/                # Agent loop, tool parser, reflection QA, cache
│       ├── mcp_server/           # Stdio MCP Server + tool registry
│       ├── tools/                # Service implementations (hotels, restaurants, weather…)
│       ├── ui/                   # Streamlit web portal
│       └── utils/                # Config, Logger, Resilience cache, Validation
├── .env                          # Your API keys (gitignored)
├── .env.example                  # Template for .env
├── README.md
├── requirements.txt
└── pyproject.toml
```

> **Note:** `docs/` and `tests/` folders exist locally for development reference but are excluded from the repository — they are not needed to run the project.

---

## 🗺️ Supported Destinations (Curated Fallback)

Hotels and restaurants have verified curated data (no fabrication) for:

| Destination | Hotels | Restaurants |
|---|---|---|
| 🇮🇳 Udaipur | ✅ Luxury + Budget | ✅ Rajasthani & Mewari |
| 🇺🇸 New York | ✅ Luxury + Budget | ✅ Indian + NYC Classics |
| 🇮🇳 Jaipur | ✅ Luxury + Budget | ✅ Rajasthani Royal |
| 🇮🇳 Ahmedabad | ✅ Luxury + Budget | ✅ Gujarati Thali |
| 🇮🇳 Mumbai | ✅ Luxury + Budget | ✅ Coastal & Street Food |
| 🇮🇳 Delhi | ✅ Luxury + Budget | ✅ Mughlai & Modern Indian |
| 🇮🇳 Goa | ✅ Luxury + Budget | ✅ Goan & Portuguese Fusion |

For all other cities, live OSM and DuckDuckGo data is used.

---

## 📦 Requirements

- Python 3.11+
- An OpenRouter API key (free tier: [openrouter.ai](https://openrouter.ai)) **or** Ollama installed locally
- Internet connection (for weather, routes, events, books, and live hotel/restaurant search)

---

## 📄 License

MIT © Lakshya Patidar
