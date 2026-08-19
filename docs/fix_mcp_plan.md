# Fix MCP Server and Agent Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve MCP subprocess launch failures, multi-tool iteration cutoffs in the agent loop, and OpenRouter API key error handling to ensure reliable agent and MCP execution.

**Architecture:** Update `PlanPilotAgent` initialization to pass `PYTHONPATH` in `StdioServerParameters.env`, refine tool loop termination logic using `requested_tools` set tracking, sanitize optional tool parameters, and enforce strict error handling for LLM providers.

**Tech Stack:** Python 3.11+, MCP SDK, httpx, asyncio, pytest

## Global Constraints

- Preserve clean output messages when MCP tools fail to find data.
- Never hardcode static dummy fallback datasets.
- Ensure all unit tests pass with pytest.

---

### Task 1: Fix MCP Subprocess Environment in Agent Initialization

**Files:**
- Modify: `src/planpilot/agent/agent.py:130-140`
- Test: `tests/test_mcp_env.py`

**Interfaces:**
- Consumes: `sys.executable`, `os.environ`, `mcp.StdioServerParameters`
- Produces: `PlanPilotAgent.server_params` with explicit `PYTHONPATH` pointing to `src`

- [ ] **Step 1: Write test for MCP subprocess server_params environment**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Update `PlanPilotAgent.__init__` to pass `env` with `PYTHONPATH`**
- [ ] **Step 4: Run test to verify it passes**

---

### Task 2: Fix Multi-Tool Agent Loop Termination & Argument Sanitization

**Files:**
- Modify: `src/planpilot/agent/agent.py:700-820`
- Test: `tests/test_multi_tool_loop.py`

**Interfaces:**
- Consumes: `has_weather`, `has_events`, `has_books`, `has_hotels`, `has_route`, `has_restaurants`
- Produces: `requested_tools` set tracking to allow calling multiple tools when requested in a query

- [ ] **Step 1: Write test for multi-tool query execution**
- [ ] **Step 2: Update `agent.py` to check `requested_tools.issubset(called_tools)`**
- [ ] **Step 3: Run pytest to verify all test suites pass**

---

### Task 3: Improve OpenRouter Error Handling & Verify Project End-to-End

**Files:**
- Modify: `src/planpilot/agent/agent.py:310-420`
- Modify: `.env`

- [ ] **Step 1: Fix `OPENROUTER_API_KEY` verification and error handling in `agent.py`**
- [ ] **Step 2: Clean `.env` file formatting**
- [ ] **Step 3: Run full pytest suite**
- [ ] **Step 4: Run end-to-end agent CLI test**
