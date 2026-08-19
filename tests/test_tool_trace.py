"""Tests for the TOOL_TRACE structured callback protocol.

Covers:
- tool start event recorded
- tool output event recorded
- cache-hit path appears in trace
- trace list is not empty when a tool is actually used
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any


# ---------------------------------------------------------------------------
# Helper: mirrors the ui_callback logic in streamlit_app.py (no Streamlit dep)
# ---------------------------------------------------------------------------

def make_ui_callback(trace_items: list[dict]) -> Any:
    async def ui_callback(msg: str) -> None:
        if msg.startswith("TOOL_TRACE:start:"):
            parts = msg.split(":", 3)
            tool_name = parts[2] if len(parts) > 2 else "tool"
            args_part = parts[3] if len(parts) > 3 else "{}"
            trace_items.append({"tool": tool_name, "args": args_part, "started": time.monotonic()})
        elif msg.startswith("TOOL_TRACE:end:"):
            parts = msg.split(":", 3)
            tool_name = parts[2] if len(parts) > 2 else "tool"
            source = parts[3] if len(parts) > 3 else "live"
            for item in reversed(trace_items):
                if item["tool"] == tool_name and "duration_ms" not in item:
                    item["duration_ms"] = int((time.monotonic() - item["started"]) * 1000)
                    item["source"] = source
                    break

    return ui_callback


def run(coro: Any) -> None:
    asyncio.run(coro)


# ---------------------------------------------------------------------------
# Tests: TOOL_TRACE message format
# ---------------------------------------------------------------------------

def test_tool_trace_start_message_is_parseable():
    msg = f"TOOL_TRACE:start:get_weather:{json.dumps({'city': 'Hyderabad'}, separators=(',', ':'))}"
    parts = msg.split(":", 3)
    assert parts[2] == "get_weather"
    assert json.loads(parts[3]) == {"city": "Hyderabad"}


def test_tool_trace_end_live_is_parseable():
    parts = "TOOL_TRACE:end:get_weather:live".split(":", 3)
    assert parts[2] == "get_weather"
    assert parts[3] == "live"


def test_tool_trace_end_cache_is_parseable():
    parts = "TOOL_TRACE:end:famous_restaurants:cache".split(":", 3)
    assert parts[2] == "famous_restaurants"
    assert parts[3] == "cache"


# ---------------------------------------------------------------------------
# Tests: callback -> trace_items
# ---------------------------------------------------------------------------

def test_tool_start_event_recorded():
    trace: list[dict] = []
    cb = make_ui_callback(trace)
    run(cb('TOOL_TRACE:start:get_weather:{"city":"Delhi"}'))

    assert len(trace) == 1
    assert trace[0]["tool"] == "get_weather"
    assert trace[0]["args"] == '{"city":"Delhi"}'
    assert "started" in trace[0]
    assert "duration_ms" not in trace[0]


def test_tool_output_event_recorded_live():
    trace: list[dict] = []
    cb = make_ui_callback(trace)
    run(cb('TOOL_TRACE:start:get_weather:{"city":"Delhi"}'))
    run(cb("TOOL_TRACE:end:get_weather:live"))

    assert len(trace) == 1
    assert "duration_ms" in trace[0]
    assert trace[0]["source"] == "live"


def test_cache_hit_path_appears_in_trace():
    trace: list[dict] = []
    cb = make_ui_callback(trace)
    run(cb('TOOL_TRACE:start:famous_restaurants:{"city":"Mumbai"}'))
    run(cb("TOOL_TRACE:end:famous_restaurants:cache"))

    assert len(trace) == 1
    assert trace[0]["tool"] == "famous_restaurants"
    assert trace[0]["source"] == "cache"
    assert "duration_ms" in trace[0]


def test_trace_list_not_empty_when_tool_used():
    trace: list[dict] = []
    cb = make_ui_callback(trace)
    run(cb('TOOL_TRACE:start:get_weather:{"city":"Paris"}'))
    run(cb("TOOL_TRACE:end:get_weather:live"))
    run(cb('TOOL_TRACE:start:find_budget_hotels:{"city":"Paris","budget":"low"}'))
    run(cb("TOOL_TRACE:end:find_budget_hotels:cache"))

    assert len(trace) == 2
    assert all("duration_ms" in item for item in trace)
    assert {item["source"] for item in trace} == {"live", "cache"}


def test_non_trace_messages_do_not_pollute_trace():
    trace: list[dict] = []
    cb = make_ui_callback(trace)
    run(cb("Connecting to tool server..."))
    run(cb("Reasoning (Step 1)..."))
    run(cb("\u26a1 [Cache Hit] Fetching stored output for 'get_weather'..."))
    run(cb("\u2705 Received live output from 'get_weather'"))

    assert trace == []


def test_multiple_tools_all_recorded():
    trace: list[dict] = []
    cb = make_ui_callback(trace)
    for t in ["get_weather", "famous_restaurants", "find_budget_hotels"]:
        run(cb(f"TOOL_TRACE:start:{t}:{{}}"))
        run(cb(f"TOOL_TRACE:end:{t}:live"))

    assert len(trace) == 3
    assert [item["tool"] for item in trace] == ["get_weather", "famous_restaurants", "find_budget_hotels"]
