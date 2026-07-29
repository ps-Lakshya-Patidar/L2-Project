# 🧙 Weekend Wizard

> A fully local, stateful AI agent powered by **Ollama** (`llama3.2:3b`), **MCP** (Model Context Protocol), and free public APIs — designed to make your weekends more fun.

---

## ✨ Features

| Tool | API | Description |
|------|-----|-------------|
| 🌤️ Weather | Open-Meteo | Get current weather for any city |
| 📚 Books | Open Library | Search and recommend books by topic, author, or title |
| 😂 Jokes | JokeAPI | Fetch random jokes by category (Programming, Misc, etc.) |
| 🐕 Dog Images | Dog CEO | Fetch random dog pictures by breed |
| 🧠 Trivia | Open Trivia DB | Serve trivia questions and evaluate your answers |

## 🏗️ Architecture

```
User ──► CLI ──► Stateful Agent Loop ──► MCP Client ──► MCP Subprocess ──► Tools ──► APIs
                    │                                                        │
                    └──── Ollama (llama3.2:3b) ◄── QA Reflection Pass ◄──────┘
```

**Key design principles:**
- **Model Context Protocol (MCP)**: Implements standard MCP stdio client-server protocol.
- **Stateful Conversation**: Preserves chat history across turns, enabling multi-turn conversations and follow-ups.
- **Native Tool Calling**: Utilizes local `llama3.2:3b` tool-calling capabilities dynamically.
- **Self-Reflection (QA) Pass**: Performs a final verification pass using conversation context and tool outputs before printing answers.
- **Zero Cloud Dependencies**: 100% local operation — no keys or cloud tokens required.

## 🚀 Quick Start

### 1. Prerequisites
- **Python**: version 3.11+
- **Ollama**: installed and running locally with the model pulled:
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

### 4. Running the Wizard

#### A. Interactive Mode (Multi-turn REPL)
Launch the wizard directly to enter stateful interactive mode:
```bash
weekend-wizard
```
*Note: Stateful memory allows you to reply with choices (e.g., `A`, `B`, `C`, `D`) for trivia questions or ask follow-up questions!*

#### B. Single-Query Mode
Submit a natural language prompt directly as an argument:
```bash
weekend-wizard "What is the weather in Ahmedabad?"
```

## 📁 Project Structure

```
weekend-wizard/
├── src/weekend_wizard/
│   ├── agent/          # Stateful agent loop, reflection orchestration
│   ├── mcp_server/     # MCP server implementation
│   ├── tools/          # Tool integrations (weather, books, jokes, dogs, trivia)
│   ├── prompts/        # System prompts and templates
│   ├── models/         # Pydantic schemas (placeholder)
│   └── utils/          # Config validation and setup
├── docs/               # Documentation
├── scripts/            # Utility scripts
├── pyproject.toml      # Packaging & CLI entry points metadata
└── requirements.txt    # Pinned production runtime dependencies
```

## 📝 License

MIT
