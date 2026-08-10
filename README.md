# 🧭 PlanPilot

PlanPilot is a stateful, fully local AI agent orchestrator powered by **Ollama** / **Groq Cloud**, the **Model Context Protocol (MCP)**, and free public APIs. It acts as your personal navigator to fetch real-time weather forecasts, suggest reading material, and discover live local events.

---

## ✨ Features

- **🌤️ Smart Weather Forecasts**: Connects to the Open-Meteo API to retrieve current conditions and hourly precipitation probabilities (rain check) for the next 12 hours.
- **📚 Book Recommendations**: Queries the Open Library API to find books by topic, title, or author. Includes URL-encoding and live links.
- **🎟️ Live Event Discovery**: Uses DuckDuckGo to scrape real-time events, comedy shows, concerts, or exhibitions for any city. Built-in layout parser fallback.
- **💻 Stateful Conversation REPL**: An interactive CLI prompt that remembers previous turns for multi-turn questions.
- **🌐 Interactive Streamlit Portal**: A beautiful, dark-themed dashboard featuring system vital checks, model switching, and real-time terminal stdout log mirroring.

---

## 🆕 Recent Improvements

- Preference memory with persistent JSON storage.
- UI chat input repositioned below output.
- Cleaned .gitignore and trimmed requirements.
- Added `preferences.py` utilities.


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
                 Registered Tools (get_weather, search_books, discover_events)
                      │
                      ▼
                 External APIs (Open-Meteo, Open Library, DuckDuckGo)
```

### Protocol flow:
1. The **Stateful Agent** initiates a protocol handshake with the local MCP server running as a subprocess.
2. The MCP server registers the active tools and sends their schemas back to the client.
3. The Agent loops dynamically to fetch reasoning steps, executes tools over stdout/stdin channels, feeds results back to the LLM, and conducts a **Self-Reflection (QA) Review** pass before returning the final response.

---

## ⚙️ How the Process Works (Under the Hood)

Whenever you submit a query, PlanPilot goes through the following sequence:

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

1. **Handshake**: The agent establishes communication with the MCP server subprocess.
2. **Tool Scheme Retrieval**: The agent retrieves the JSON schemas of all registered tools (`get_weather`, `search_books`, `discover_events`) and describes them to the LLM.
3. **Reasoning Loop**: 
   - The LLM parses the prompt and decides whether to output a direct reply or run a tool call.
   - For example, asking about Indore rain triggers a tool call to `get_weather` with `{"city": "Indore"}`.
4. **Tool Execution**: The agent intercepts the tool call, makes the corresponding async network request to the public API, and inserts the raw JSON output back into the conversation history.
5. **Self-Reflection (QA) Pass**:
   - To prevent hallucinations, the draft response and current turn's tool outputs are sent to a secondary LLM reviewer.
   - The QA pass verifies that the draft matches the tool data, filters out any unrelated history answers, and outputs a clean, friendly, and accurate response.
6. **Log Mirroring**: In Streamlit mode, the callback outputs print trace logs in real-time to both your web dashboard and the terminal stdout console.

---

## 🚀 How to Run the Project

### 1. Prerequisites
- **Python**: Version 3.11+
- **Ollama** (optional, for local run): Installed and running with the model pulled:
  ```bash
  ollama pull llama3.2:3b
  ```

### 2. Installation
Clone the repository, create a virtual environment, and install the package:
```powershell
# Navigate to parent folder
cd "path/to/PlanPilot"

# Create virtual environment
python -m venv .venv

# Activate virtual environment
.venv\Scripts\Activate.ps1

# Install requirements and package in editable mode
pip install -r requirements.txt
pip install -e .
```

### 3. Configuration
Copy the environment template and configure your provider (pre-configured for local Ollama, or add a Groq API key):
```powershell
copy .env.example .env
```

#### **A. Local Execution (Requires Ollama running)**
Ensure `.env` contains:
```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
```

#### **B. Cloud Execution (No local Ollama needed - Grader Settings)**
If you do not have Ollama installed or running locally, you can run entirely in the cloud using the Groq provider. Set `.env` to:
```env
LLM_PROVIDER=groq
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile

# Optional: supply a free API key from https://serpapi.com for structured Google Events searches.
SERPAPI_API_KEY=your_serpapi_api_key_here
```

### 4. Running Commands

#### **A. Streamlit Web Portal**
To start the dark-theme UI with live terminal logs:
```powershell
planpilot ui
```
*Open **[http://localhost:8501](http://localhost:8501)** in your browser.*

#### **B. Stateful Interactive Mode (CLI REPL)**
To chat directly inside your console with history memory:
```powershell
planpilot query
```
*Type `exit` or `quit` to close.*

#### **C. Single-Query Command**
Submit a quick prompt directly as a console argument:
```powershell
planpilot query "Is there any rain expected in Indore in the next few hours?"
```

---

## 📊 Sample Execution Log & Integration Test

Below is an actual CLI execution log demonstrating tool listing, execution, and the reflection pass:

```powershell
(.venv) PS path/to/PlanPilot> planpilot query "What is the weather in Delhi?"
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  🧭 PlanPilot                                                               │
│  Model: llama3.2:3b | URL: http://localhost:11434                           │
│                                                                             │
│  Ask me about weather, book recommendations, or local event discovery!      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
Connecting to tool server...
Initializing protocol handshake...
Retrieving registered tools...
Reasoning (Step 1)...
✦ Calling MCP Tool: get_weather with args {'city': 'Delhi'}...
Received output from 'get_weather'
Reasoning (Step 2)...
Performing self-reflection review...

┌─────────────────────────── 🧭 PlanPilot Response ───────────────────────────┐
│                                                                             │
│  The current weather in Delhi is 28.9 degrees Celsius with a wind speed     │
│  of 0.7 km/h (units: km/h). According to the forecast, there's a 94%        │
│  probability of rain in the next 12 hours, with approximately 2.7 mm of     │
│  rainfall expected.                                                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

*Built with ❤️ as a learning project in AI agent engineering.*
