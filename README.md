# 🧙 Weekend Wizard

> A fully local AI agent powered by **Ollama** (Mistral 7B), **MCP** (Model Context Protocol), and free public APIs — designed to make your weekends more fun.

---

## ✨ Features

| Tool | API | Description |
|------|-----|-------------|
| 🌤️ Weather | Open-Meteo | Get current weather for any city |
| 📚 Books | Open Library | Search and recommend books |
| 😂 Jokes | JokeAPI | Fetch random jokes by category |
| 🐕 Dog Images | Dog CEO | Random dog pictures by breed |
| 🧠 Trivia | Open Trivia DB | Quiz questions on any topic |

## 🏗️ Architecture

```
User ──► CLI ──► Agent Loop ──► MCP Client ──► MCP Server ──► Tools ──► APIs
                    │                                            │
                    └──── Ollama (mistral:7b) ◄── Reflection ◄──┘
```

**Key design principles:**
- Clean Architecture with clear dependency boundaries
- SOLID principles throughout
- Fully async I/O for tool calls
- Single reflection pass before final response
- 100% local — no cloud AI services

## 🚀 Quick Start

```bash
# Prerequisites
# 1. Python 3.11+
# 2. Ollama installed and running (https://ollama.ai)
# 3. Pull the model: ollama pull mistral:7b

# Clone & install
git clone <repo-url> && cd weekend-wizard
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e ".[dev]"

# Configure
copy .env.example .env

# Run
weekend-wizard
```

## 🧪 Testing

```bash
pytest                          # All tests
pytest -m unit                  # Unit tests only
pytest -m integration           # Integration tests
pytest -m e2e                   # End-to-end tests
pytest --cov=weekend_wizard     # With coverage
```

## 📁 Project Structure

```
weekend-wizard/
├── src/weekend_wizard/
│   ├── agent/          # Agent loop, reflection, orchestration
│   ├── mcp_server/     # MCP server implementation
│   ├── tools/          # Tool implementations (weather, books, etc.)
│   ├── prompts/        # System & tool prompts
│   ├── models/         # Data models (Pydantic)
│   └── utils/          # Config, logging, helpers
├── tests/
│   ├── unit/           # Fast, isolated tests
│   ├── integration/    # Tests with external deps
│   └── e2e/            # Full pipeline tests
├── docs/               # Documentation
├── scripts/            # Utility scripts
├── pyproject.toml      # Project metadata & tool config
└── requirements.txt    # Pinned runtime dependencies
```

## 📝 License

MIT

---

*Built with ❤️ as a learning project in AI agent engineering.*
