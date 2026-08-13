# 🧭 PlanPilot: Complete Project Presentation & Explanation Guide

This guide is designed to walk you through explaining the entire project to a reviewer from start to finish. It covers the **Problem**, the **Solution**, the **Architecture**, and key **Concept Explanations** (MCP, Ollama, Pydantic, etc.).

---

## 📢 Section 1: The Presentation Pitch (Start Here)

### 1. The Problem Statement
*   **Context**: LLMs (Large Language Models) are powerful, but they suffer from three key limitations:
    1.  **Knowledge Cutoff**: They don't know real-time information (e.g., today's weather or events happening tonight).
    2.  **No Local State**: They don't remember you, your interests, or your dislikes across different sessions.
    3.  **Hallucinations**: If they don't know the answer, they are prone to inventing realistic-looking but fake information (like recommending a non-existent concert).
*   **The Goal**: Build a fully local, privacy-respecting AI agent companion (**PlanPilot**) that connects directly to real-world local tools, remembers user profile preferences, runs on local hardware, and guarantees hallucination-free scheduling.

### 2. The Solution (What we built)
We built **PlanPilot**, a Personal AI Weekend Concierge consisting of:
*   **An Agent Loop** with a self-reflection pass that acts as a quality gate to verify recommendations against raw API payloads.
*   **An MCP Tool Server** acting as an isolated environment that fetches live weather (Open-Meteo), books (Open Library), and events (SerpAPI/DuckDuckGo).
*   **A User Preference Engine** that stores home city, interests, dislikes, and vibes, automatically ranking suggestions.
*   **A Dark-themed Dashboard UI** built in Streamlit, complete with real-time logging, live model config toggles, and token/cost evaluation metrics.

---

## 🏗️ Section 2: How Things Work (Architecture & Data Flow)

Explain this sequence diagram to the reviewer to show how a single prompt flows:

```
[User Interface]           [Agent Loop]            [MCP Server]          [APIs]
      |                         |                       |                  |
      |--- 1. User Prompt ----->|                       |                  |
      |    ("Any rain today?")  |                       |                  |
      |                         |--- 2. Tool Query ---->|                  |
      |                         |    (get_weather)      |                  |
      |                         |                       |--- 3. Fetch ---->| (Open-Meteo)
      |                         |                       |<-- 4. JSON ------|
      |                         |<-- 5. Raw Result -----|                  |
      |                         |                       |                  |
      |                         |=== 6. Draft Answer ===|                  |
      |                         |=== 7. Reflection =====|                  |
      |                         |    (QA Verification)  |                  |
      |<-- 8. Refined Answer ---|                       |                  |
```

### The Codebase Execution Flow:
1.  **Handshake**: When the CLI or UI starts, `PlanPilotAgent` starts the MCP server (`server.py`) as a subprocess using **stdio** (standard input/output streams) transport.
2.  **Tool Enrollment**: The server registers four tools: `get_weather`, `search_books`, `discover_events`, and `get_weekend_score`.
3.  **Intent Classification**: The agent parses the user query and filters tool schemas to prevent the LLM from making unnecessary calls (e.g. searching books when the user only asked about rain).
4.  **Tool Execution**: The LLM outputs a tool call structured as JSON. The agent catches it, runs the async API call in `services.py`, and feeds the data back to the LLM.
5.  **Quality Reflection**: The draft response is evaluated by a secondary reflection system message to ensure:
    - No hallucinated data is presented.
    - Weather units and book URLs are formatted as clean markdown links.
6.  **Telemetry Render**: Latency, input/output tokens, execution steps, and live cost calculation metrics are sent to the Streamlit UI.

---

## 📚 Section 3: Explanation of Key Tech Stack Concepts

Be prepared to explain these core technologies to your reviewer:

### 1. Model Context Protocol (MCP)
*   **What it is**: An open standard protocol designed by Anthropic that allows clients (like our Agent loop) to securely interact with tool servers.
*   **Why use it**: Instead of hardcoding API request logic directly in the LLM loop (which makes code messy and poses security risks if the LLM tries to run arbitrary code), MCP separates the data-fetching layer into an isolated server. They communicate safely over stdin/stdout standard streams using JSON-RPC.

### 2. Ollama vs. Groq Cloud
*   **Ollama**: A tool for running Large Language Models (like Llama 3.2 3B) **locally** on your CPU/GPU. It keeps data completely private and offline.
*   **Groq Cloud**: A cloud-based LLM hosting provider powered by custom LPUs (Language Processing Units). It is incredibly fast (hundreds of tokens per second). We support both dynamically via settings.

### 3. Pydantic & Pydantic Settings
*   **What it is**: Python's most popular data validation library.
*   **Usage**: `config.py` uses `Pydantic Settings` to read `.env` configuration files and system variables. It validates types at startup (e.g. checking that the port is a number between 1 and 65535, or that the LLM provider is either "ollama" or "groq"). If configuration is wrong, it fails fast on startup.

### 4. Asyncio Event Loop & Thread Pools
*   **Concept**: Since fetching weather, events, and books involves waiting on network responses, using standard synchronous code would freeze the application. We use `asyncio` to fetch data concurrently.
*   **Thread Execution**: Ollama calls can block execution. To prevent blocking the main asyncio event loop (which manages the MCP subprocess), we use `loop.run_in_executor` to run LLM operations safely in background threads.

### 5. Tenacity & Retry Logic
*   **Concept**: Cloud API endpoints (like Groq) occasionally fail due to network drops or rate limit exceptions (HTTP 429).
*   **Usage**: We decorated the LLM calling functions with `@retry` from the `tenacity` library, employing exponential backoff (e.g., waiting 2s, 4s, 8s...) to automatically self-heal and resolve transient network errors without crashing the session.

---

## 💎 Section 4: Engineering Highlights & Edge-Case Fixes

Highlight these technical achievements to prove production-grade development:

*   **Groq Null Message Repair**: We identified that Groq's validation schema rejects assistant messages containing empty `tool_calls` structures. We implemented sanitizers that recursively inspect the message dictionary and remove `tool_calls` keys entirely if they are empty.
*   **BaseExceptionGroup TaskGroup Shield**: Since anyio subprocesses run in a `TaskGroup`, any network timeout results in an `ExceptionGroup` crash. We implemented a custom handler to catch standard and grouped exceptions, displaying a clear, styled user-facing error message instead of dumping a stack trace.
*   **Reliable API Book Search**: We replaced fragile web scraping falling back on DuckDuckGo for books with a direct, robust Open Library API integration featuring timeout retry thresholds.
*   **Dynamic Path Resolution**: Rather than using brittle hardcoded directories to locate configuration files, we created an upward parent folder traverser that searches dynamically for the project root `.env` file up to 6 levels high.
*   **Real-time Cost & Token Telemetry**: Built a telemetry decoder displaying prompt inputs, completion outputs, total token metrics, steps, and real-time cost estimations based on active model rate cards.
