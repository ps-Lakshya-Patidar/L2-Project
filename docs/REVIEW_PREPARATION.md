# 🧭 PlanPilot: Review Preparation Guide

This guide is compiled to help you prepare for a project review, detailing the architecture, the recent engineering upgrades, robustness modifications, and key technical talking points for **PlanPilot**.

---

## 🛠️ Table of Contents
1. [Core Features & Pitch](#-core-features--pitch)
2. [Architecture & Protocol Flow](#-architecture--protocol-flow)
3. [Key Upgrades (Implemented Phases)](#-key-upgrades-implemented-phases)
4. [Robustness & Edge-Case Engineering](#-robustness--edge-case-engineering)
5. [Codebase Map (Critical Files)](#-codebase-map-critical-files)
6. [Demo Reference Guide](#-demo-reference-guide)
7. [Potential Review Questions & Answers](#-potential-review-questions--answers)

---

## ⚡ Core Features & Pitch

**PlanPilot** is a stateful, fully local AI agent concierge that translates natural language prompts into personalized weekend schedules. It does this by combining:
*   **LLM Reasoning**: Ollama (local) or Groq Cloud (remote).
*   **Model Context Protocol (MCP)**: A standard protocol to securely hook LLMs up to real-world data tools.
*   **Persistent Preference Memory**: Custom JSON profile store that ranks, filters, and formats suggestions according to user interests and dislikes.
*   **Real-time External API Integrations**: Open-Meteo (Weather), Open Library (Books), and SerpAPI/DuckDuckGo (Local Events).

---

## 🏗️ Architecture & Protocol Flow

PlanPilot follows a clean client-server architecture separating LLM orchestration from tool execution:

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
            +-----------------------+-----------------------+
            |                       |                       |
            v                       v                       v
      [ get_weather ]        [ search_books ]       [ discover_events ]
     (Open-Meteo API)      (Open Library API)      (SerpAPI / DDG search)
```

### The Tool-Call Handshake & Loop:
1.  **Handshake**: The client agent spawns the MCP server as a python subprocess using `stdio` (standard input/output streams) as the transport channel.
2.  **Tool Listing**: The client retrieves the tool definitions (`get_weather`, `search_books`, `discover_events`, `get_weekend_score`) along with their JSON-Schema parameters.
3.  **LLM Execution Loop**:
    - The user prompt is injected with the User Profile context.
    - The LLM receives the schema descriptions. If it needs data, it outputs a tool call (e.g. `get_weather(city="Mumbai")`).
    - The agent catches this tool call, halts LLM generation, runs the Python function asynchronously, and feeds the JSON result back into the LLM conversation window.
4.  **Self-Reflection (QA) Pass**: Once a draft response is ready, a secondary, self-contained system call is executed. This quality assurance pass validates that the draft aligns with the tool's raw data, strips out any history leakage, and formats book URLs and weather units precisely before final output.

---

## 🚀 Key Upgrades (Implemented Phases)

### Phase 1: User Preference Engine (`preferences.py`)
*   **Storage**: Profile data saved as a lightweight JSON document at `~/.planpilot/user_preferences.json`.
*   **Profile Context Injection**: Dynamically loads interests, dislikes, home city, budget preference, and custom notes, compiling them into a natural-language prompt prefix used in every agent turn.
*   **Personalization Rules**: The Agent ranks book and event matches using a custom percentage matching rule (e.g., *Match explanation: 95% match - aligns with your interest in hiking*).

### Phase 2: Weather-Aware Planning & Weekend Scoring (`services.py`)
*   **`compute_weekend_score`**: An algorithmic evaluator that parses weather forecasts and event density, calculating a **0-100 Weekend Quality Score**:
    - *Weather (max 50 pts)*: Perfect weather gets 50 pts. Rainy/Overcast results in progressive penalties based on probability.
    - *Events (max 30 pts)*: Scale of 0 pts (no events) to 30 pts (5+ events found).
    - *Preference Match (max 20 pts)*: 4 pts bonus per event matching user interest keywords.
*   **`get_weekend_score` MCP Tool**: Concurrently pulls weather and events data using `asyncio.gather` and compiles the score.

### Phase 3: Premium Streamlit Portal (`streamlit_app.py`)
*   **Theme**: Styled with custom CSS imports, featuring dark backdrop gradients, custom fonts, fluid layouts, and hovering cards.
*   **Control Panel**: Real-time LLM provider switching (local Ollama vs Groq Cloud), editable user profile section with auto-save, and diagnostic tool trace views.

---

## 🛡️ Robustness & Edge-Case Engineering

During development, several critical failures were identified and systematically resolved:

1.  **Groq API Null Validation Fix**: 
    - *Problem*: The Groq API rejected messages if the assistant's previous message contained `tool_calls: null` or an empty object.
    - *Fix*: Refactored `_prepare_groq_messages` to entirely omit the `tool_calls` key from assistant payloads if no actual tool execution took place.
2.  **MCP Subprocess TaskGroup Crash Safety**:
    - *Problem*: If an HTTP request timed out inside `stdio_client`, `anyio` threw a `BaseExceptionGroup`, causing a hard crash of the main application.
    - *Fix*: Wrapped the MCP runner inside a `try/except BaseException` interceptor block in `agent.py`, converting system-level TaskGroup crashes into clear, graceful user-facing error messages.
3.  **Non-Earth Query Safeguard**:
    - *Problem*: Asking about fictional or planetary locations (e.g., "What is the weather on Mars?") caused the LLM to call `get_weather`, causing geocoding failures.
    - *Fix*: Implemented a keyword filter list (`_non_earth`) and system rules that prevent calls to Earth-based geocoding tools for non-terrestrial locations.
4.  **Dynamic Project Root Discovery**:
    - *Problem*: `_PROJECT_ROOT` was configured using a hardcoded 4-level parent directory chain (`Path(__file__).parent.parent.parent.parent`), which broke when running the code from different directories or environments.
    - *Fix*: Implemented a dynamic upward parent traverser that checks for the presence of a `.env` file up to 6 levels high, falling back to `Path.cwd()` if not found.
5.  **Book Search Reliability**:
    - *Problem*: The DuckDuckGo HTML scraping fallback for book requests was slow and timed out frequently.
    - *Fix*: Removed the DuckDuckGo fallback from book search entirely, raising the primary Open Library API client timeout to `8.0s` with explicit warning logs.
6.  **Structured Log Exporter**:
    - *Problem*: Development runs were difficult to debug due to silent backend API failures.
    - *Fix*: Configured structured file logging to `~/.planpilot/planpilot.log` with `INFO` and `DEBUG` tags tracking lat/lon geocoding lookup, status codes, and HTTP timeouts.

---

## 📂 Codebase Map (Critical Files)

*   [`src/planpilot/agent/agent.py`](file:///C:/Users/LakshyaPatidar/GitHub/L2%20Project/PlanPilot/src/planpilot/agent/agent.py): The main agent loop, LLM call wrappers, tool intercept logic, and QA reflection pass.
*   [`src/planpilot/mcp_server/server.py`](file:///C:/Users/LakshyaPatidar/GitHub/L2%20Project/PlanPilot/src/planpilot/mcp_server/server.py): Defines MCP tool registration schema handlers (`get_weather`, `search_books`, `discover_events`, `get_weekend_score`).
*   [`src/planpilot/tools/services.py`](file:///C:/Users/LakshyaPatidar/GitHub/L2%20Project/PlanPilot/src/planpilot/tools/services.py): Core integrations containing geocoding resolvers, Open-Meteo, Open Library parsing, and SerpAPI/DDG scraping.
*   [`src/planpilot/ui/streamlit_app.py`](file:///C:/Users/LakshyaPatidar/GitHub/L2%20Project/PlanPilot/src/planpilot/ui/streamlit_app.py): The interactive Streamlit web dashboard.
*   [`src/planpilot/utils/config.py`](file:///C:/Users/LakshyaPatidar/GitHub/L2%20Project/PlanPilot/src/planpilot/utils/config.py): Pydantic settings config incorporating dynamic path resolution.
*   [`src/planpilot/utils/preferences.py`](file:///C:/Users/LakshyaPatidar/GitHub/L2%20Project/PlanPilot/src/planpilot/utils/preferences.py): JSON profile CRUD actions and prompts compilation.

---

## 💻 Demo Reference Guide

Ensure your virtual environment is active:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.venv\Scripts\Activate.ps1
```

### 1. Show the Interactive CLI Portal
```bash
planpilot query
```
*   **What to demo**: Ask `"What's the weather in Indore?"`. Point out the stdout logs showing the MCP handshake, the tool execution, and the final response featuring explicit units (`°C`, `km/h`).

### 2. Show Web Dashboard
```bash
planpilot ui
```
*   **What to demo**: 
    1. Go to the **My Profile** tab, add a couple of interests (e.g., "mystery novels", "jazz concerts") and hit save.
    2. Ask: `"Recommend some books for me."`
    3. Notice how it ranks recommendations by matching your interests, and formats them with clickable Open Library hyperlinks.
    4. Switch the model configuration live in the sidebar from Ollama to Groq.

### 3. Check Live Logs
Open another terminal pane and tail the logs during a request:
```powershell
Get-Content C:\Users\LakshyaPatidar\.planpilot\planpilot.log -Wait -Tail 20
```

---

## ❓ Potential Review Questions & Answers

#### **Q: What is the Model Context Protocol (MCP) and why is it useful here?**
*   **Answer**: MCP is an open standard transport protocol designed by Anthropic to securely connect LLMs to data sources and tools. Instead of hardcoding API integrations inside the agent's core code, MCP isolates the tools inside a separate server. The client agent discovers tools dynamically via a handshake. This makes adding new tools highly plug-and-play and protects the LLM from insecure code execution.

#### **Q: How does the agent prevent hallucinations when recommending events and books?**
*   **Answer**: First, through strict system constraints that explicitly forbid inventing events/books. Second, via the **Self-Reflection (QA) Pass**. Before returning the response, the agent takes the raw JSON tool outputs and the draft response, passing them to a QA LLM instance. The QA instance acts as a checker to ensure that every book or event mentioned matches the real API outputs, stripping out any hallucinated suggestions.

#### **Q: Why was the DuckDuckGo fallback removed from the book search API?**
*   **Answer**: The DuckDuckGo search relied on HTML parsing, which is brittle and highly prone to breaking when search engine structures change. It was also causing frequent HTTP timeouts (up to 8s) in environments with high latency. By removing it and optimizing the Open Library API call with a larger timeout, we dramatically increased request reliability and response quality.

#### **Q: How did you fix the Groq API invalid request crashes?**
*   **Answer**: The Groq validation schema strictly rejects any `role: assistant` messages that contain a `tool_calls: null` or empty object payload. When a tool wasn't invoked, Pydantic's serialization would sometimes retain an empty `tool_calls` field. We fixed this by rewriting `_prepare_groq_messages` in `agent.py` to recursively strip out any `tool_calls` keys entirely if they do not contain valid, populated tool commands.
