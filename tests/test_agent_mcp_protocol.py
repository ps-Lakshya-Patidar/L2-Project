"""Offline regression tests for MCP result and provider protocol handling."""

from __future__ import annotations

import json
from types import SimpleNamespace

from planpilot.agent.agent import PlanPilotAgent, ToolCall, ToolFunction


def test_decode_mcp_multi_block_result_rebuilds_a_list() -> None:
    result = SimpleNamespace(
        content=[
            SimpleNamespace(text='{"title": "One"}'),
            SimpleNamespace(text='{"title": "Two"}'),
        ]
    )

    data, text = PlanPilotAgent._decode_mcp_result(result)

    assert data == [{"title": "One"}, {"title": "Two"}]
    assert json.loads(text) == data


def test_openai_tool_responses_keep_individual_call_ids() -> None:
    agent = PlanPilotAgent()
    first = ToolCall(ToolFunction("get_weather", {"city": "Delhi"}), id="weather-delhi")
    second = ToolCall(ToolFunction("get_weather", {"city": "Mumbai"}), id="weather-mumbai")

    prepared = agent._prepare_groq_messages(
        [
            {"role": "assistant", "content": "", "tool_calls": [first, second]},
            {
                "role": "tool",
                "name": "get_weather",
                "tool_call_id": "weather-delhi",
                "content": '{"city": "Delhi"}',
            },
            {
                "role": "tool",
                "name": "get_weather",
                "tool_call_id": "weather-mumbai",
                "content": '{"city": "Mumbai"}',
            },
        ]
    )

    assert prepared[1]["tool_call_id"] == "weather-delhi"
    assert prepared[2]["tool_call_id"] == "weather-mumbai"


def test_compact_tool_output_remains_valid_json() -> None:
    data = [{"title": "A" * 100}, {"title": "B" * 100}]
    compact = PlanPilotAgent._compact_tool_output(data, json.dumps(data), char_limit=80)

    assert json.loads(compact)
