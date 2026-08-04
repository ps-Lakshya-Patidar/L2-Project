# 🧭 PlanPilot

> A fully local, stateful AI agent powered by **Ollama** (`llama3.2:3b`) / **Groq Cloud**, **MCP** (Model Context Protocol), and free public APIs — designed to help you with weather forecasts, book searches, and event discovery.

---

## ✨ Features

| Tool | API | Description |
|------|-----|-------------|
| 🌤️ Weather | Open-Meteo | Get current weather and 12h precipitation forecasts for any city |
| 📚 Books | Open Library | Search and recommend books by topic, author, or title |
| 🎟️ Events | DuckDuckGo | Discover live events, concerts, or exhibitions happening in a specific location |

## 🏗️ Architecture

```
User ──► CLI ──► Stateful Agent Loop ──► MCP Client ──► MCP Subprocess ──► Tools ──► APIs
                    │                                                        │
                    └──── Ollama / Groq API ◄── QA Reflection Pass ◄─────────┘
```

**Key design principles:**
- **Model Context Protocol (MCP)**: Implements standard MCP stdio client-server protocol.
- **Stateful Conversation**: Preserves chat history across turns, enabling multi-turn conversations and follow-ups.
- **Unified LLM Abstraction**: Supports local Ollama or high-speed Groq Cloud API.
- **Self-Reflection (QA) Pass**: Performs a final verification pass using conversation context and tool outputs before printing answers.
- **Interactive Portal**: Exposes a gorgeous Streamlit dashboard for vital checks, model switching, and real-time execution logs.

## 🚀 Quick Start

### 1. Prerequisites
- **Python**: version 3.11+
- **Ollama** (optional): installed and running locally with the model pulled:
  ```bash
  ollama pull llama3.2:3b
  ```

### 2. Installation
Clone the repository and install the production requirements:
```bash
git clone https://github.com/ps-Lakshya-Patidar/L2-Project.git
cd L2-Project/weekend-wizard
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
pip install -e .
```

### 3. Configuration
Copy the environment template to activate local settings (pre-configured to default to `llama3.2:3b`):
```bash
copy .env.example .env
```

### 4. Running the Agent

#### A. Interactive Mode (Multi-turn REPL)
Launch PlanPilot directly to enter stateful interactive mode:
```bash
planpilot query
```

#### B. Single-Query Mode
Submit a natural language prompt directly as an argument:
```bash
planpilot query "What is the weather in Indore?"
```

#### C. Streamlit Web Portal
Ignite the engine and launch the local web UI:
```bash
planpilot ui
```

## 📁 Project Structure

```
planpilot/
├── src/planpilot/
│   ├── agent/          # Stateful agent loop, reflection orchestration
│   ├── mcp_server/     # MCP server implementation
│   ├── tools/          # Tool integrations (weather, books, events)
│   ├── ui/             # Streamlit Web UI portal
│   └── utils/          # Config validation and setup
├── pyproject.toml      # Packaging & CLI entry points metadata
└── requirements.txt    # Pinned production runtime dependencies
```

## 📝 License

MIT

---

*Built with ❤️ as a learning project in AI agent engineering.*
