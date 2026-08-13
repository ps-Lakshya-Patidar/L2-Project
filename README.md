# 🧭 PlanPilot

PlanPilot is a stateful, fully local/cloud AI agent concierge powered by **Ollama** or **Groq Cloud**, the **Model Context Protocol (MCP)**, and free public APIs. It acts as your personal navigator to compile personalized weekend schedules, fetch real-time weather, recommend books, and discover live local events.

---

## ✨ Features

- **🌤️ Smart Weather Forecasts**: Connects to the Open-Meteo API to retrieve current conditions and hourly precipitation probabilities (rain check) for the next 12 hours.
- **📚 Reliable Book Recommendations**: Queries the Open Library API directly to find books by topic, title, or author. Includes direct links and has no scraping fallback to ensure data accuracy.
- **🎟️ Live Event Discovery**: Uses SerpAPI (with DuckDuckGo search fallback) to locate live events, concerts, or exhibitions for any city.
- **🧠 User Preference Engine**: Integrates a JSON profile memory (interests, dislikes, home city, budget) to personalize and rank all recommendations.
- **📊 Evaluation & Cost Telemetry**: Displays token usage (input/output/total), step execution counts, latency, and real-time cost estimations based on model pricing grids in the Streamlit UI.
- **🌐 Interactive Streamlit Portal**: A beautiful, dark-themed dashboard featuring system vital checks, model switching, profile editing, and live callback metrics.
- **💻 Stateful CLI REPL**: An interactive CLI prompt that remembers previous turns for multi-turn planning.

---

## 🏗️ Architecture

PlanPilot uses a client-server architecture based on the Model Context Protocol (MCP) using the `stdio` transport.

```
User ──► CLI / Streamlit UI
              │
              ▼
    Stateful Agent Loop (planpilot.agent)
              │
      ┌───────┴───────┐
      ▼               ▼
   Ollama /        MCP Client Session
   Groq API           │ (stdio transport protocol)
                       ▼
                MCP Subprocess (planpilot.mcp_server)
                       │
                       ▼
             Registered Tools (get_weather, search_books, discover_events, get_weekend_score)
                       │
                       ▼
             External APIs (Open-Meteo, Open Library, SerpAPI/DuckDuckGo)
```

---

## 🔌 API & Tool Schemas

PlanPilot exposes the following tool interfaces on the MCP Server:

### 1. `get_weather`
Fetch current weather and 12-hour precipitation forecast for a specified city.
*   **Input Schema**:
    ```json
    {
      "city": "string (required, 2-100 characters)"
    }
    ```
*   **Output Example**:
    ```json
    {
      "city": "Indore",
      "country": "India",
      "temperature_c": 28.5,
      "windspeed_kmh": 14.2,
      "weather_code": 1,
      "forecast_next_12h": {
        "any_rain_expected": false,
        "max_rain_probability_percent": 10,
        "total_expected_rain_mm": 0.0
      }
    }
    ```

### 2. `search_books`
Search for book recommendations and metadata using the Open Library API.
*   **Input Schema**:
    ```json
    {
      "query": "string (required)"
    }
    ```
*   **Output Example**:
    ```json
    [
      {
        "title": "Dune",
        "author": "Frank Herbert",
        "first_publish_year": 1965,
        "number_of_pages_median": 412,
        "info_url": "https://openlibrary.org/works/OL89341W"
      }
    ]
    ```

### 3. `discover_events`
Discover live events, exhibitions, concerts, or activities happening in a city.
*   **Input Schema**:
    ```json
    {
      "city": "string (required)",
      "query": "string (optional, category filter)"
    }
    ```
*   **Output Example**:
    ```json
    [
      {
        "source": "Music Fest 2026",
        "summary": "Live Open Air Venue | Saturday 7 PM | Info/Tickets: https://..."
      }
    ]
    ```

### 4. `get_weekend_score`
Compute an algorithmic quality score (0-100) based on weather, event counts, and preference matches.
*   **Input Schema**:
    ```json
    {
      "city": "string (required)"
    }
    ```

---

## ⚙️ How the Process Works (Under the Hood)

```
[User Prompt] ──► [HANDSHAKE] ──► [LLM Tool Analysis]
                                        │
             ┌──────────────────────────┴──────────────────────────┐
             ▼ (Needs Data)                                        ▼ (No tools needed / done)
      [Execute MCP Tool]                                    [Self-Reflection QA]
             │                                                     │
             ▼                                                     ▼
    [API Return & Loop] ───────────────────────────────────► [Refined Response]
```

1.  **Handshake**: The client agent spawns the MCP server subprocess using stdio.
2.  **Tool Scheme Retrieval**: The agent retrieves the tool definitions and parameters.
3.  **Reasoning Loop**: The LLM determines if a tool call is needed. If yes, it outputs a tool call which is intercepted and executed by the client.
4.  **Self-Reflection (QA) Pass**:
    - To prevent hallucinations, the draft response and current turn's tool outputs are sent to a secondary LLM reviewer.
    - The QA pass validates that the draft matches the tool data, formats book URLs as clickable markdown links, and outputs a clean, friendly response.
5.  **Metrics Calculation**: Prompt inputs, completion tokens, latency, steps, and real-time cost estimations based on rate cards are compiled and rendered.

---

## 🚀 How to Run the Project

### 1. Installation
Clone the repository, configure a virtual environment, and install:
```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows:
.venv\Scripts\Activate.ps1
# Mac/Linux:
source .venv/bin/activate

# Install requirements and package in editable mode
pip install -r requirements.txt
pip install -e .
```

### 2. Configuration
Copy the environment template and configure your provider:
```bash
cp .env.example .env
```
Ensure `.env` contains:
```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b

# Or if using Groq Cloud:
# LLM_PROVIDER=groq
# GROQ_API_KEY=your_key_here
# GROQ_MODEL=llama-3.3-70b-versatile
```

### 3. Execution Commands

#### **A. Streamlit Web Portal (With Metrics & UI)**
```bash
planpilot ui
```

#### **B. Stateful Interactive Mode (CLI REPL)**
```bash
planpilot query
```

#### **C. Single-Query Command**
```bash
planpilot query "Is there any rain expected in Indore in the next few hours?"
```

---

## 📝 Example Transcript

**User prompt**: `Recommend some mystery books.`

```
Connecting to tool server...
Initializing protocol handshake...
Retrieving registered tools...
Reasoning (Step 1)...
✦ Calling MCP Tool: search_books with args {'query': 'mystery'}...
Received output from 'search_books'
Reasoning (Step 2)...
Performing self-reflection review...
```

**PlanPilot Response**:

> ### 📚 Mystery Book Recommendations
>
> 1. [The Mysterious Affair at Styles](https://openlibrary.org/works/OL471268W) by Agatha Christie (1920, 296 pages)
> 2. [Still Life](https://openlibrary.org/works/OL17081952W) by Louise Penny (2005, 312 pages)
> 3. [In the Woods](https://openlibrary.org/works/OL5735363W) by Tana French (2007, 429 pages)

---

*Built with ❤️ as a learning project in AI agent engineering.*
