"""PlanPilot Agent Loop.

Orchestrates the client-side MCP session, connects to the local Ollama instance,
manages tool-calling loops, and performs a single reflection pass before returning the final response.
"""

from __future__ import annotations

import asyncio
import copy
import functools
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import ollama
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from tenacity import retry, stop_after_attempt, wait_exponential

from planpilot.utils.config import get_settings
from planpilot.utils.logger import logger
from planpilot.utils.preferences import (
    load_preferences,
    build_compact_preference_context,
    auto_update_preferences_from_text,
)
from planpilot.utils.validation import (
    extract_requirements,
    validate_and_enforce_sections,
    UserRequirements,
)
from planpilot.utils.resilience import global_cache

# ---------------------------------------------------------------------------
# Centralized prompt constants — single source of truth, no runtime duplication
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are PlanPilot, an AI Trip Planner powered by 6 MCP tools:
1. get_weather — Current weather & 3-day forecast
2. travel_route — Best travel route, distance, transport modes, duration & cost
3. find_budget_hotels — Hotel recommendations & price tiers
4. famous_restaurants — Local/requested cuisine & ratings
5. discover_events — Upcoming music concerts, festivals & live events
6. search_books — Destination history & travel books

OUTPUT RULES:
- SINGLE-TOPIC QUERIES: If the user asks about a specific topic (e.g. only weather, only restaurants, only hotels), answer ONLY that requested topic directly.
- FULL TRAVEL PLANS: Output ONLY these 6 sections with clean markdown headers:
  # Weather
  # Best Travel Route
  # Hotel Accommodations
  # Famous Restaurants
  # Upcoming Events
  # Recommended Books

TOOL CALLING STRATEGY:
- Multi-domain / Travel Plan queries: Call ALL needed tools simultaneously in your very first response in parallel. Never call tools one-by-one sequentially.
- Single-topic queries: Call only the single requested tool.

STRICT CONSTRAINTS:
- NEVER invent or hallucinate data. Ground all answers strictly in tool outputs.
- If data is unavailable from tools, state "Data unavailable".
- Include proper units: °C, km/h, km, hours, ₹/$.
- Do NOT generate extra filler sections (no Destination Overview, no Estimated Budget tables, no generic travel tips, no speculative itineraries).
"""

# Lightweight verification prompt for the reflection pass
_REFLECT_TRAVEL = """
Review the travel guide.

Check:
1. It contains only the 6 tool sections (# Weather, # Best Travel Route, # Hotel Accommodations, # Famous Restaurants, # Upcoming Events, # Recommended Books).
2. No hallucinated data or filler sections.
3. Information matches tool outputs accurately.

If everything is correct reply:

OK

Otherwise return the clean corrected version only.
"""
_REFLECT_SINGLE = """
Review the answer.

Check:
1. It answers only the requested topic directly.
2. No hallucinated facts.
3. Information matches tool output.

If correct reply:

OK

Otherwise return the corrected answer only.
"""



class ToolFunction:
    def __init__(self, name: str, arguments: dict[str, Any]):
        self.name = name
        self.arguments = arguments


class ToolCall:
    def __init__(self, function: ToolFunction, id: str = "call_dummy"):
        self.id = id
        self.function = function


class LLMMessage:
    def __init__(self, content: str | None, tool_calls: list[ToolCall] | None = None):
        self.content = content
        self.tool_calls = tool_calls or []


class LLMResponse:
    def __init__(self, message: LLMMessage):
        self.message = message


class PlanPilotAgent:
    """Agent orchestrator connecting LLM to the MCP Tool Server."""

    def __init__(self) -> None:
        self.settings = get_settings()
        src_dir = str(Path(__file__).resolve().parent.parent.parent)
        env = dict(os.environ)
        if "PYTHONPATH" in env and env["PYTHONPATH"]:
            env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{env['PYTHONPATH']}"
        else:
            env["PYTHONPATH"] = src_dir

        self.server_params = StdioServerParameters(
            command=sys.executable, args=["-m", "planpilot.mcp_server"], env=env
        )
        self.last_metrics: dict[str, Any] | None = None
        self.messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SYSTEM_PROMPT}
        ]
        self._response_cache_enabled = True

    def reset(self) -> None:
        """Reset the conversation history."""
        self.messages = [{"role": "system", "content": _SYSTEM_PROMPT}]

    def _get_response_cache_key(self, user_query: str, reqs: UserRequirements) -> str:
        """Generate a cache key for response caching based on normalized query + requirements."""
        normalized_query = user_query.lower().strip()
        req_tuple = (
            reqs.destination.lower().strip(),
            reqs.origin.lower().strip() if reqs.origin else "",
            reqs.cuisine.lower().strip() if reqs.cuisine else "",
            reqs.budget_level.lower().strip() if reqs.budget_level else "",
        )
        combined = f"{normalized_query}:{':'.join(req_tuple)}"
        return f"response:{hashlib.md5(combined.encode()).hexdigest()}"

    def _prune_message_history(self, max_exchanges: int = 3) -> None:
        """Keep system + last N tool exchanges only to reduce context size."""
        system = [m for m in self.messages if m.get("role") == "system"]
        exchanges = []
        for msg in reversed(self.messages):
            if msg.get("role") == "system":
                continue
            exchanges.append(msg)
            if len(exchanges) >= max_exchanges * 2:  # assistant + tool pairs
                break
        self.messages = system + list(reversed(exchanges))

    def _merge_system_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Combine all system messages into a single system message at the start of the list."""
        system_contents = []
        non_system_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content")
                if content:
                    system_contents.append(content)
            else:
                non_system_messages.append(msg)

        if system_contents:
            combined_system = {
                "role": "system",
                "content": "\n\n".join(system_contents),
            }
            return [combined_system] + non_system_messages
        return non_system_messages


    def _prepare_groq_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Preprocess messages into OpenAI/Groq compatible schemas (preserving tool IDs)."""
        groq_msgs = []
        # Tool response messages must be associated with the *individual* tool
        # call ID.  Mapping by tool name corrupts a response when a model calls
        # the same tool more than once in a single assistant message.
        last_tool_ids: dict[str, str] = {}

        # Merge system messages first to comply with standard chat templates
        merged_messages = self._merge_system_messages(messages)

        for msg in merged_messages:
            role = msg.get("role")
            content = msg.get("content")
            raw_tool_calls = msg.get("tool_calls")

            # --- Assistant message WITH valid tool calls ---
            if role == "assistant" and raw_tool_calls:
                formatted_calls = []
                for idx, tc in enumerate(raw_tool_calls):
                    call_id = getattr(tc, "id", f"call_gen_{idx}")
                    name = tc.function.name
                    last_tool_ids[name] = call_id
                    formatted_calls.append(
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(tc.function.arguments),
                            },
                        }
                    )
                groq_msgs.append(
                    {
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": formatted_calls,
                    }
                )

            # --- Assistant message WITHOUT tool calls (strip tool_calls key entirely) ---
            elif role == "assistant":
                groq_msgs.append({"role": "assistant", "content": content or ""})

            elif role == "tool":
                name = msg.get("name")
                call_id = msg.get("tool_call_id") or last_tool_ids.get(name, "call_gen_0")
                groq_msgs.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": name,
                        "content": content,
                    }
                )
            else:
                # System / user messages — never include tool_calls
                groq_msgs.append({"role": role or "user", "content": content or ""})

        return groq_msgs

    def _prepare_ollama_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Preprocess messages into Ollama-compatible message schemas."""
        ollama_msgs = []
        
        # Merge system messages first to comply with local model chat templates
        merged_messages = self._merge_system_messages(messages)

        for msg in merged_messages:
            role = msg.get("role")
            content = msg.get("content")

            if role == "assistant" and msg.get("tool_calls"):
                formatted_calls = []
                for tc in msg["tool_calls"]:
                    formatted_calls.append(
                        {
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            }
                        }
                    )
                ollama_msgs.append(
                    {
                        "role": "assistant",
                        "content": content or "",
                        "tool_calls": formatted_calls,
                    }
                )
            elif role == "tool":
                ollama_msgs.append(
                    {
                        "role": "user",
                        "content": f"[Tool Output from '{msg.get('name')}']:\n{content}",
                    }
                )
            else:
                ollama_msgs.append(
                    {
                        "role": role or "user",
                        "content": content or "",
                    }
                )
        return ollama_msgs

    @staticmethod
    def _decode_mcp_result(result: Any) -> tuple[Any | None, str]:
        """Return a JSON value and text representation from an MCP tool result.

        FastMCP serializes a list return value as several TextContent blocks
        (one JSON object per item).  Joining those blocks makes invalid JSON,
        which previously left ``tool_context`` empty and gave the LLM malformed
        tool output.  Decode each block independently and rebuild the original
        collection when possible.
        """
        text_blocks = [
            block.text for block in getattr(result, "content", [])
            if hasattr(block, "text") and isinstance(block.text, str)
        ]
        if not text_blocks:
            return None, ""

        decoded: list[Any] = []
        for text in text_blocks:
            try:
                decoded.append(json.loads(text))
            except json.JSONDecodeError:
                return None, "\n".join(text_blocks)

        data: Any = decoded[0] if len(decoded) == 1 else decoded
        return data, json.dumps(data, ensure_ascii=False)

    @staticmethod
    def _compact_tool_output(data: Any | None, raw_text: str, query_type: str = "general", char_limit: int | None = None) -> str:
        """Filter irrelevant fields based on query intent before truncating."""
        limit = char_limit if char_limit is not None else 500
        if data is None:
            if len(raw_text) <= limit:
                return raw_text
            return json.dumps({"_truncated": True, "preview": raw_text[:limit]})

        if isinstance(data, dict) and "temperature_c" in data:
            # Weather dict: compact current + full 3-day outlook
            daily = data.get("daily_forecast_3_days", [])
            compact_daily = [
                {
                    "date": d.get("date"),
                    "high": d.get("temp_max_c"),
                    "low": d.get("temp_min_c"),
                    "rain_chance": d.get("max_rain_probability_percent", 0),
                    "condition": d.get("condition", "Partly Cloudy")
                }
                for d in daily[:3]
            ]
            fc_12h = data.get("forecast_next_12h", {})
            return json.dumps({
                "city": data.get("city"),
                "current_temp": data.get("temperature_c"),
                "wind_kmh": data.get("windspeed_kmh"),
                "condition": data.get("weather_condition", "Clear"),
                "next_12h_rain_chance": fc_12h.get("max_rain_probability_percent", 0),
                "forecast_3_days": compact_daily
            }, ensure_ascii=False)

        if isinstance(data, dict) and "distance_km" in data:
            # Route dict: compact transit summary
            return json.dumps({
                "source": data.get("source"),
                "destination": data.get("destination"),
                "distance": data.get("distance_km"),
                "travel_time": data.get("travel_time"),
                "recommended_mode": data.get("recommended_mode"),
                "options": data.get("transport_options", [])
            }, ensure_ascii=False)

        if query_type == "weather_only" and isinstance(data, dict):
            filtered = {"city": data.get("city"), "temperature_c": data.get("temperature_c"), "forecast_next_12h": data.get("forecast_next_12h")}
            return json.dumps(filtered, ensure_ascii=False)
        elif query_type == "hotels_only" and isinstance(data, list):
            filtered = [{"hotel_name": h.get("hotel_name"), "price_range": h.get("price_range"), "rating": h.get("rating")} for h in data[:2]]
            return json.dumps(filtered, ensure_ascii=False)
        elif query_type == "restaurants_only" and isinstance(data, list):
            filtered = [{"restaurant_name": r.get("restaurant_name"), "speciality": r.get("speciality"), "rating": r.get("rating")} for r in data[:2]]
            return json.dumps(filtered, ensure_ascii=False)
        elif query_type == "events_only" and isinstance(data, list):
            filtered = [{"source": e.get("source"), "summary": e.get("summary")} for e in data[:2]]
            return json.dumps(filtered, ensure_ascii=False)
        elif query_type == "books_only" and isinstance(data, list):
            filtered = [{"title": b.get("title"), "author": b.get("author")} for b in data[:1]]
            return json.dumps(filtered, ensure_ascii=False)
        elif query_type == "travel_plan" and isinstance(data, list):
            compact_items = []
            for item in data[:3]:
                if isinstance(item, dict):
                    filtered_item = {k: v for k, v in item.items() if k in (
                        "hotel_name", "price_range", "rating", "review_rating", "location", "area", "hotel_class",
                        "restaurant_name", "speciality",
                        "source", "summary", "venue", "date",
                        "title", "author", "first_publish_year"
                    ) and v is not None}
                    compact_items.append(filtered_item or item)
                else:
                    compact_items.append(item)
            return json.dumps(compact_items, ensure_ascii=False)

        serialized = json.dumps(data, ensure_ascii=False)
        if len(serialized) <= limit:
            return serialized
        if isinstance(data, list):
            preview = []
            for item in data:
                candidate = json.dumps(preview + [item], ensure_ascii=False)
                if len(candidate) > limit and preview:
                    break
                preview.append(item)
            return json.dumps(preview, ensure_ascii=False)
        return json.dumps({"_truncated": True, "preview": serialized[:limit]})

    def _sanitize_tool_schema_for_groq(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sanitize JSON schemas to comply with Groq/OpenAI tool-calling specifications."""
        sanitized = copy.deepcopy(tools)
        for tool in sanitized:
            func = tool.get("function", {})
            params = func.get("parameters", {})
            properties = params.get("properties", {})
            for prop_name, prop_data in properties.items():
                if "type" in prop_data:
                    p_type = prop_data["type"]
                    if isinstance(p_type, list):
                        filtered = [t for t in p_type if t != "null"]
                        if len(filtered) == 1:
                            prop_data["type"] = filtered[0]
                        else:
                            prop_data["type"] = "string"
                if "anyOf" in prop_data:
                    types = []
                    for option in prop_data["anyOf"]:
                        opt_type = option.get("type")
                        if opt_type and opt_type != "null":
                            types.append(opt_type)
                    del prop_data["anyOf"]
                    if types:
                        prop_data["type"] = types[0]
                    else:
                        prop_data["type"] = "string"
        return sanitized

    def _call_openrouter(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, tool_choice: str = "auto"
    ) -> LLMResponse:
        """Helper to invoke OpenRouter API with OpenAI-compatible schemas, tool calling, and backoff retry."""

        # 1. Format messages for OpenRouter (OpenAI-compatible)
        openrouter_messages = self._prepare_groq_messages(messages)

        # 2. Invoke OpenRouter API
        api_key = (self.settings.openrouter_api_key or "").strip()
        url = f"{self.settings.openrouter_base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/PlanPilot",
            "X-Title": "PlanPilot AI",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.settings.openrouter_model,
            "messages": openrouter_messages,
            "temperature": 0.0,
        }
        if tools:
            payload["tools"] = self._sanitize_tool_schema_for_groq(tools)
            payload["tool_choice"] = tool_choice

        with httpx.Client(timeout=60.0) as client:
            max_retries = 3
            for attempt in range(max_retries):
                resp = client.post(url, json=payload, headers=headers)
                if resp.status_code == 429:
                    retry_after = 2
                    try:
                        err_meta = resp.json().get("error", {}).get("metadata", {})
                        retry_after = int(err_meta.get("retry_after_seconds", 2))
                    except Exception:
                        retry_after = int(resp.headers.get("retry-after", "2"))
                    print(f"OpenRouter Rate Limit (429). Waiting {retry_after + 1}s before retry...", flush=True)
                    time.sleep(retry_after + 1)
                    continue
                if resp.status_code >= 400:
                    print("OPENROUTER API ERROR RESPONSE BODY:", resp.text, flush=True)
                    if resp.status_code == 401:
                        raise ValueError(
                            "🔑 Invalid or Expired OpenRouter API Key! Please verify your key at https://openrouter.ai/keys."
                        )
                    # If model doesn't support required tool_choice, fallback to auto
                    if "tool_choice" in resp.text.lower() and payload.get("tool_choice") == "required":
                        payload["tool_choice"] = "auto"
                        resp = client.post(url, json=payload, headers=headers)
                    # If model doesn't support tools at all, fallback to no-tools
                    elif ("tools" in resp.text.lower() or "not supported" in resp.text.lower()) and "tools" in payload:
                        print(f"Model '{payload['model']}' tool calling issue on OpenRouter. Falling back to text tool calling...", flush=True)
                        payload.pop("tools", None)
                        payload.pop("tool_choice", None)
                        resp = client.post(url, json=payload, headers=headers)
                if resp.status_code < 400:
                    break

            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices", [])
        if not choices:
            return LLMResponse(message=LLMMessage(content="", tool_calls=[]))

        choice = choices[0]["message"]
        content = choice.get("content") or ""
        if content:
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

        # Parse tool calls
        raw_tool_calls = choice.get("tool_calls", [])
        tool_calls = []
        for tc in raw_tool_calls:
            func_data = tc.get("function", {})
            name = func_data.get("name")
            args_str = func_data.get("arguments", "{}")
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except Exception:
                args = {}
            tool_calls.append(
                ToolCall(
                    id=tc.get("id", f"call_{len(tool_calls)+1}"),
                    function=ToolFunction(name=name, arguments=args),
                )
            )

        if not tool_calls and content:
            tool_calls = self._parse_text_tool_calls(content)
            if tool_calls:
                content = ""

        # Track usage metrics
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        if hasattr(self, "last_metrics") and self.last_metrics is not None:
            self.last_metrics["input_tokens"] += prompt_tokens
            self.last_metrics["output_tokens"] += completion_tokens
            self.last_metrics["total_tokens"] += (prompt_tokens + completion_tokens)
            self.last_metrics["llm_calls"] += 1

        return LLMResponse(message=LLMMessage(content=content, tool_calls=tool_calls))

    @retry(
        stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=5, max=60), reraise=True
    )
    def _call_llm_with_retry(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, tool_choice: str = "auto"
    ) -> LLMResponse:
        """Helper to invoke the configured LLM provider with exponential backoff on failure."""

        provider = self.settings.llm_provider.lower().strip()

        if provider == "openrouter":
            api_key = (self.settings.openrouter_api_key or "").strip()
            if not api_key:
                raise ValueError(
                    "LLM_PROVIDER is set to 'openrouter', but OPENROUTER_API_KEY is not configured. "
                    "Please add a valid API key to your .env file or set environment variable OPENROUTER_API_KEY."
                )
            return self._call_openrouter(messages, tools, tool_choice=tool_choice)
        else:
            # Default to Ollama
            ollama_messages = self._prepare_ollama_messages(messages)
            kwargs: dict[str, Any] = {
                "model": self.settings.ollama_model,
                "messages": ollama_messages,
                "options": {
                    "temperature": 0.0,
                    "num_ctx": 8192,
                }
            }
            if tools:
                kwargs["tools"] = tools

            resp = ollama.chat(**kwargs)
            content = resp.message.content or ""
            if content:
                content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

            tool_calls = []
            if resp.message.tool_calls:
                for tc in resp.message.tool_calls:
                    args = tc.function.arguments
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    tool_calls.append(
                        ToolCall(function=ToolFunction(name=tc.function.name, arguments=args))
                    )

            if not tool_calls and content:
                tool_calls = self._parse_text_tool_calls(content)
                if tool_calls:
                    content = ""

            # Track metrics if enabled
            if isinstance(resp, dict):
                prompt_tokens = resp.get("prompt_eval_count", 0) or 0
                completion_tokens = resp.get("eval_count", 0) or 0
            else:
                prompt_tokens = getattr(resp, "prompt_eval_count", 0) or 0
                completion_tokens = getattr(resp, "eval_count", 0) or 0

            if hasattr(self, "last_metrics") and self.last_metrics is not None:
                self.last_metrics["input_tokens"] += prompt_tokens
                self.last_metrics["output_tokens"] += completion_tokens
                self.last_metrics["total_tokens"] += (prompt_tokens + completion_tokens)
                self.last_metrics["llm_calls"] += 1

            return LLMResponse(message=LLMMessage(content=content, tool_calls=tool_calls))

    def _parse_text_tool_calls(self, content: str) -> list[ToolCall]:
        """Extract tool calls written as text from LLM responses — fallback for models that don't support native tool calling.

        Parsing strategy (tried in order):
        1. JSON array/object blocks: [{\"name\": \"get_weather\", \"arguments\": {...}}]
           - Handles single-quote variants via quote-swap fallback.
        2. Parenthesized call syntax: get_weather(city="Hyderabad")
           - Handles key=value pairs with string, int, bool, and null conversions.
        All 6 registered MCP tools are recognized.
        """
        if not content:
            return []

        _VALID_TOOLS = {
            "get_weather", "search_books", "discover_events",
            "find_budget_hotels", "travel_route", "famous_restaurants",
        }
        tool_calls: list[ToolCall] = []
        seen: set[tuple[str, str]] = set()  # deduplicate within the same text response

        def _add(name: str, args: dict[str, Any]) -> None:
            key = (name, json.dumps(args, sort_keys=True))
            if name in _VALID_TOOLS and key not in seen:
                seen.add(key)
                tool_calls.append(
                    ToolCall(
                        id=f"call_text_{len(tool_calls) + 1}",
                        function=ToolFunction(name=name, arguments=args),
                    )
                )

        def _try_parse_json(block: str) -> None:
            """Attempt to parse a JSON block and extract tool call(s) from it."""
            block = block.strip()
            candidates = [block, block.replace("'", '"')]
            
            # Clean leading/trailing mismatched brackets e.g. "[[ ... ]" -> "[ ... ]"
            temp = block
            while temp.startswith("[[") and not temp.endswith("]]"):
                temp = temp[1:]
                candidates.extend([temp, temp.replace("'", '"')])
            temp = block
            while temp.endswith("]]") and not temp.startswith("[["):
                temp = temp[:-1]
                candidates.extend([temp, temp.replace("'", '"')])

            data = None
            for raw in candidates:
                try:
                    data = json.loads(raw)
                    break
                except Exception:
                    pass

            if data is None:
                # Fallback: search for individual {"name": ...} objects directly
                for obj_match in re.finditer(r'\{[^{}]*"name"\s*:\s*"([^"]+)"[^{}]*\}', block):
                    try:
                        obj = json.loads(obj_match.group(0))
                        if isinstance(obj, dict) and "name" in obj:
                            args = obj.get("arguments") or obj.get("args") or obj.get("parameters") or {}
                            _add(obj["name"], args)
                    except Exception:
                        pass
                return

            # Flatten arbitrary nested lists (e.g. [[{...}]])
            flat_items = []
            queue = [data] if not isinstance(data, list) else list(data)
            while queue:
                curr = queue.pop(0)
                if isinstance(curr, list):
                    queue.extend(curr)
                elif isinstance(curr, dict):
                    flat_items.append(curr)

            for item in flat_items:
                if isinstance(item, dict) and "name" in item:
                    args = item.get("arguments") or item.get("args") or item.get("parameters") or {}
                    _add(item["name"], args)

        def _coerce(value: str) -> Any:
            """Convert a string value to its proper Python type."""
            if value.lstrip("-").isdigit():
                return int(value)
            if value.lower() == "true":
                return True
            if value.lower() == "false":
                return False
            if value.lower() in ("none", "null"):
                return None
            return value

        # --- Strategy 1: JSON block parsing with multi-bracket support ---
        for block_match in re.finditer(r"(\[+[\s\S]*?\]+|\{[\s\S]*?\})", content):
            _try_parse_json(block_match.group(1).strip())

        # --- Strategy 1.5: Direct tool object search if broad JSON parse missed anything ---
        if not tool_calls:
            for obj_match in re.finditer(r'\{\s*"name"\s*:\s*"(?:get_weather|search_books|discover_events|find_budget_hotels|travel_route|famous_restaurants)"[\s\S]*?\}', content):
                try:
                    obj = json.loads(obj_match.group(0))
                    args = obj.get("arguments") or obj.get("args") or obj.get("parameters") or {}
                    _add(obj["name"], args)
                except Exception:
                    pass

        # --- Strategy 2: Parenthesized call syntax ---
        # Only run if strategy 1 produced nothing (avoids double-counting)
        if not tool_calls:
            call_pattern = re.compile(
                r"\b(" + "|".join(re.escape(t) for t in _VALID_TOOLS) + r")\s*\(([^)]*)\)"
            )
            for match in call_pattern.finditer(content):
                tname = match.group(1)
                arg_part = match.group(2).strip()
                args: dict[str, Any] = {}

                # Try arg_part as a JSON object first
                if arg_part.startswith("{"):
                    for raw in (arg_part, arg_part.replace("'", '"')):
                        try:
                            args = json.loads(raw)
                            break
                        except Exception:
                            pass

                # Fall back to key=value pairs
                if not args and arg_part:
                    for m in re.finditer(r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+?)(?=[,\s)]|$))', arg_part):
                        k = m.group(1)
                        v = m.group(2) or m.group(3) or m.group(4) or ""
                        args[k] = _coerce(v)

                _add(tname, args)

        # --- Strategy 3: XML / Tagged tool call syntax (Nemotron / Qwen format) ---
        if not tool_calls:
            xml_blocks = re.finditer(
                r"(?:<tool_call>[\s\S]*?</tool_call>|<function[=\s](?:name=)?[\"']?([a-zA-Z0-9_]+)[\"']?>[\s\S]*?</function>)",
                content,
                re.IGNORECASE,
            )
            for m in xml_blocks:
                block = m.group(0)
                # Extract function name: <function=find_budget_hotels> or <function name="find_budget_hotels">
                fn_match = re.search(
                    r"<function[=\s](?:name=)?[\"']?([a-zA-Z0-9_]+)[\"']?>", block, re.IGNORECASE
                )
                if not fn_match:
                    continue
                fn_name = fn_match.group(1).strip()

                # Extract parameters: <parameter=city>Udaipur</parameter> or <parameter name="city">Udaipur</parameter>
                args: dict[str, Any] = {}
                param_matches = re.finditer(
                    r"<parameter[=\s](?:name=)?[\"']?([a-zA-Z0-9_]+)[\"']?>([\s\S]*?)</parameter>",
                    block,
                    re.IGNORECASE,
                )
                for p in param_matches:
                    p_name = p.group(1).strip()
                    p_val = p.group(2).strip()
                    args[p_name] = _coerce(p_val)

                _add(fn_name, args)

        return tool_calls

    async def _run_sync(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Run a blocking function in a thread executor, cleanly re-raising any exception.

        This prevents exceptions from the thread pool from being wrapped in
        anyio's BaseExceptionGroup (which happens when a coroutine raises
        while inside a stdio_client TaskGroup context).
        """
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                None, functools.partial(fn, *args, **kwargs)
            )
        except BaseException as e:
            # Unwrap ExceptionGroup if the executor wrapped our exception
            if hasattr(e, "exceptions") and len(e.exceptions) == 1:  # type: ignore[attr-defined]
                raise e.exceptions[0] from None  # type: ignore[attr-defined]
            raise

    async def _execute_tool_call_async(
        self,
        session: ClientSession,
        tool_call: ToolCall,
        reqs: Any,
        status_callback: Any,
        tool_context: dict[str, Any],
        is_weather_only: bool,
        is_hotels_only: bool,
        is_restaurants_only: bool,
        is_events_only: bool,
        is_books_only: bool,
        has_travel_plan: bool = False,
    ) -> tuple[str, str, Any, Any]:
        """Execute a single tool call asynchronously and return (tool_name, truncated_result, result_data, result_text)."""

        tool_name = tool_call.function.name
        tool_args = tool_call.function.arguments.copy()

        # Sanitize string args: convert "null", "none", "" to None
        for k, v in list(tool_args.items()):
            if isinstance(v, str) and v.strip().lower() in ("null", "none", ""):
                tool_args[k] = None

        # Departure City Fallback for travel_route
        if tool_name == "travel_route":
            src_arg = str(tool_args.get("source", "")).strip()
            if not src_arg or src_arg.lower() in ("none", "null", "unknown", "city", "my city", "home"):
                if reqs.origin:
                    tool_args["source"] = reqs.origin

        # Cuisine Preference Auto-filling for famous_restaurants
        if tool_name == "famous_restaurants" and not tool_args.get("query"):
            if reqs.cuisine:
                tool_args["query"] = f"{reqs.cuisine} food"

        # Determine cache key
        cache_key_check = None
        if tool_name == "get_weather":
            cache_key_check = f"weather:{tool_args.get('city', '').lower().strip()}"
        elif tool_name == "search_books":
            cache_key_check = f"books:{tool_args.get('query', '').lower().strip()}"
        elif tool_name == "famous_restaurants":
            q_tag = f":{tool_args.get('query', '').lower().strip()}" if tool_args.get("query") else ""
            cache_key_check = f"restaurants:{tool_args.get('city', '').lower().strip()}{q_tag}"
        elif tool_name == "find_budget_hotels":
            b_tier = tool_args.get("budget", "low").lower().strip()
            cache_key_check = f"hotels:{tool_args.get('city', '').lower().strip()}:{b_tier}"
        elif tool_name == "travel_route":
            cache_key_check = f"route:{tool_args.get('source', '').lower().strip()}:{tool_args.get('destination', '').lower().strip()}"

        pre_cached_data, is_stale_pre = global_cache.get(cache_key_check) if cache_key_check else (None, False)
        was_cached_before = pre_cached_data is not None and not is_stale_pre

        if status_callback:
            if was_cached_before:
                await status_callback(f"⚡ [Cache Hit] Fetching stored output for '{tool_name}'...")
            else:
                await status_callback(f"🌐 [Live Call] Executing tool '{tool_name}' with args {tool_args}...")
            await status_callback(
                f"TOOL_TRACE:start:{tool_name}:{json.dumps(tool_args, separators=(',', ':'))}"
            )

        try:
            result = await session.call_tool(tool_name, arguments=tool_args)
            result_data, result_text = self._decode_mcp_result(result)
            
            if tool_name == "get_weather" and isinstance(result_data, dict):
                tool_context["weather"] = result_data
            elif tool_name == "travel_route" and isinstance(result_data, dict):
                tool_context["route"] = result_data
            elif tool_name == "find_budget_hotels" and isinstance(result_data, list):
                tool_context["hotels"] = result_data
            elif tool_name == "famous_restaurants" and isinstance(result_data, list):
                tool_context["restaurants"] = result_data
            elif tool_name == "discover_events" and isinstance(result_data, list):
                tool_context["events"] = result_data
            elif tool_name == "search_books" and isinstance(result_data, list):
                tool_context["books"] = result_data
        except Exception as e:
            result_data = {"error": f"Tool execution failed: {str(e)}"}
            result_text = json.dumps({"error": f"Tool execution failed: {str(e)}"})

        is_cache_hit = was_cached_before or "(Cached data" in result_text
        if status_callback:
            if is_cache_hit:
                logger.info(f"⚡ [CACHE HIT] Tool '{tool_name}' response retrieved directly from local cache")
                await status_callback(f"⚡ [Cache Hit] Retrieved output directly from local cache for '{tool_name}'")
            else:
                logger.info(f"🌐 [LIVE API CALL] Tool '{tool_name}' response fetched from external API")
                await status_callback(f"✅ Received live output from '{tool_name}'")
            await status_callback(
                f"TOOL_TRACE:end:{tool_name}:{'cache' if is_cache_hit else 'live'}"
            )

        query_type = "general"
        if is_weather_only:
            query_type = "weather_only"
        elif is_hotels_only:
            query_type = "hotels_only"
        elif is_restaurants_only:
            query_type = "restaurants_only"
        elif is_events_only:
            query_type = "events_only"
        elif is_books_only:
            query_type = "books_only"
        elif has_travel_plan:
            query_type = "travel_plan"

        if result_data is not None:
            truncated_result = self._compact_tool_output(
                result_data, result_text, query_type
            )
        elif len(result_text) <= 800:
            truncated_result = result_text
        else:
            try:
                parsed = json.loads(result_text)
                if isinstance(parsed, list) and len(parsed) > 2:
                    preview = json.dumps(parsed[:2], ensure_ascii=False)
                    truncated_result = (
                        preview.rstrip("]")
                        + f", {{\"_note\": \"{len(parsed) - 2} more items available\"}}]"
                    )
                else:
                    truncated_result = result_text[:800] + f"…[truncated at 800 chars]"
            except Exception:
                truncated_result = result_text[:800] + f"…[truncated at 800 chars]"

        return tool_name, truncated_result, result_data, result_text

    async def run_query(self, user_query: str, status_callback: Any = None, goal: str | None = None) -> str:
        """Run the main agent loop: request -> tool detection -> tool execution -> reflection -> response."""
        self.last_metrics = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "latency_sec": 0.0,
            "llm_calls": 0,
            "tool_calls": 0,
            "reflection_input_tokens": 0,
            "reflection_output_tokens": 0,
            "reflection_skipped": False,
            "response_cached": False,
            "model": (
                self.settings.openrouter_model
                if self.settings.llm_provider.lower().strip() == "openrouter"
                else self.settings.ollama_model
            ),
            "provider": self.settings.llm_provider.upper().strip()
        }
        start_time = time.monotonic()
        provider = self.settings.llm_provider.lower().strip()

        # Phase 3: Check response cache before processing
        prefs = load_preferences()
        reqs = extract_requirements(user_query, user_prefs=prefs)
        cache_key = self._get_response_cache_key(user_query, reqs)
        cached_response, is_stale = global_cache.get(cache_key)
        
        if cached_response and not is_stale and self._response_cache_enabled:
            if status_callback:
                await status_callback("⚡ [Cache Hit] Retrieved cached response for this query")
            logger.info(f"[Phase 3] Response cache hit for query: {user_query[:50]}...")
            if self.last_metrics is not None:
                self.last_metrics["response_cached"] = True
                self.last_metrics["latency_sec"] = round(time.monotonic() - start_time, 2)
            return cached_response

        # Ensure system prompt is always the centralized constant (no per-turn rewrite)
        if not self.messages or self.messages[0].get("role") != "system":
            self.messages.insert(0, {"role": "system", "content": _SYSTEM_PROMPT})
        else:
            self.messages[0]["content"] = _SYSTEM_PROMPT

        if status_callback:
            await status_callback("Connecting to tool server...")

        # Append new user message to conversation history
        self.messages.append({"role": "user", "content": user_query})

        # --- History sliding window: keep system + a protocol-valid suffix ---
        system_msg = self.messages[:1]
        history = [m for m in self.messages[1:] if m.get("role") != "system"]
        if len(history) > 10:
            history = history[-10:]
            # Never send orphaned tool responses to an OpenAI-compatible API.
            while history and history[0].get("role") == "tool":
                history.pop(0)
        self.messages = system_msg + history
        
        # Prune to last 3 exchanges to reduce context size
        self._prune_message_history(max_exchanges=3)

        # Detect domain keywords in user query.  Match whole words/phrases:
        # a raw substring check turns "weather" into a restaurant request via
        # the letters "eat", causing focused queries to become full plans.
        q_lower = user_query.lower()
        def mentions(keywords: list[str]) -> bool:
            return any(
                re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", q_lower)
                for keyword in keywords
            )

        has_weather = mentions(["weather", "temperature", "forecast", "rain", "sunny", "climate"])
        has_events = mentions(["event", "events", "concert", "concerts", "exhibition", "exhibitions", "festival", "festivals", "show", "shows", "activities", "music", "comedy", "standup", "stand-up", "gig", "gigs", "play", "plays", "theatre", "theater"])
        has_books = mentions(["book", "books", "novel", "novels", "author", "authors", "reading", "read"])
        has_hotels = mentions(["hotel", "hotels", "stay", "stays", "resort", "resorts", "hostel", "hostels", "accommodation", "accommodations", "lodging"])
        has_route = mentions(["route", "routes", "travel from", "how to reach", "transport", "distance", "how to travel"])
        has_restaurants = mentions(["restaurant", "restaurants", "eat", "food", "dining", "dish", "dishes", "delicacy", "delicacies", "cafe", "cafes", "place to eat"])

        # Detect non-Earth locations — these should be answered from general knowledge, not via tools
        _non_earth = ["mars", "jupiter", "saturn", "venus", "mercury", "neptune", "uranus", "pluto",
                      "moon", "sun", "outer space", "space station", "iss", "europa", "titan",
                      "narnia", "hogwarts", "mordor", "wakanda", "gotham", "atlantis", "asgard"]
        mentions_non_earth = any(loc in q_lower for loc in _non_earth)
        if mentions_non_earth:
            has_weather = has_events = has_books = has_hotels = has_route = has_restaurants = False

        # Explicitly check if query is asking for a full travel plan/itinerary
        is_explicit_travel_plan = any(kw in q_lower for kw in ["trip", "travel plan", "full trip", "full plan", "tour", "itinerary", "vacation", "holiday", "plan a trip", "plan my trip", "day trip", "guide to"])

        # Count total domains requested
        domains_requested = sum([has_weather, has_events, has_books, has_hotels, has_route, has_restaurants])

        is_general_query = domains_requested == 0 and not is_explicit_travel_plan

        # A query is a full travel plan ONLY if explicitly asked (e.g. "plan a trip") OR if 3 or more domains are asked together without specific single intent
        has_travel_plan = is_explicit_travel_plan or (domains_requested >= 3)

        # Single-topic query flags (1 or 2 specific domains asked, e.g. "weather and famous restaurant of Hyderabad", but NOT a full travel plan)
        is_single_tool_query = not has_travel_plan and not is_general_query

        is_weather_only = has_weather and is_single_tool_query and not (has_events or has_books or has_hotels or has_route or has_restaurants)
        is_events_only = has_events and is_single_tool_query and not (has_weather or has_books or has_hotels or has_route or has_restaurants)
        is_books_only = has_books and is_single_tool_query and not (has_weather or has_events or has_hotels or has_route or has_restaurants)
        is_hotels_only = has_hotels and is_single_tool_query and not (has_weather or has_events or has_books or has_route or has_restaurants)
        is_route_only = has_route and is_single_tool_query and not (has_weather or has_events or has_books or has_hotels or has_restaurants)
        is_restaurants_only = has_restaurants and is_single_tool_query and not (has_weather or has_events or has_books or has_hotels or has_route)

        # Auto-extract preference declarations (e.g., 'I live in Indore', 'Vegetarian') from query prompt
        auto_update_preferences_from_text(user_query)

        # Compact preference context (~30 tokens vs ~180 tokens for verbose version)
        compact_prefs = build_compact_preference_context(prefs)
        goal_prefix = f"Goal:{goal}. " if goal else ""
        req_summary = (
            f"{goal_prefix}Trip: {reqs.origin}→{reqs.destination} "
            f"cuisine={reqs.cuisine or 'any'} budget={reqs.budget_level} "
            f"duration={reqs.itinerary_duration} dates={reqs.travel_dates or 'unspecified'}. "
            f"{compact_prefs}"
        )

        # Inject compact per-turn context as a single system message
        self.messages.append({"role": "system", "content": req_summary})

        tool_context: dict[str, Any] = {
            "origin": reqs.origin,
            "destination": reqs.destination,
            "weather": {},
            "route": {},
            "hotels": [],
            "restaurants": [],
            "events": [],
            "books": [],
        }

        # Sanitize stale messages: remove tool_calls key if it's None/empty (prevents Groq API errors)
        for msg in self.messages:
            if msg.get("role") == "assistant" and "tool_calls" in msg and not msg["tool_calls"]:
                del msg["tool_calls"]

        try:
          async with (
            stdio_client(self.server_params) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
          ):
            if status_callback:
                await status_callback("Connecting to tool server...")
            await session.initialize()

            # List tools from the server
            if status_callback:
                await status_callback("Retrieving registered tools...")
            tools_response = await session.list_tools()

            # Format tools for LLM, filtering by query domain intent
            if is_general_query:
                ollama_tools = None
            else:
                ollama_tools = []
                for tool in tools_response.tools:
                    # Filter out tools that were clearly NOT requested in the query
                    if not has_weather and tool.name == "get_weather" and not has_travel_plan:
                        continue
                    if not has_events and tool.name == "discover_events" and not has_travel_plan:
                        continue
                    if not has_books and tool.name == "search_books" and not has_travel_plan:
                        continue
                    if not has_hotels and tool.name == "find_budget_hotels" and not has_travel_plan:
                        continue
                    if not has_route and tool.name == "travel_route" and not has_travel_plan:
                        continue
                    if not has_restaurants and tool.name == "famous_restaurants" and not has_travel_plan:
                        continue
                    ollama_tools.append(
                        {
                            "type": "function",
                            "function": {
                                "name": tool.name,
                                "description": tool.description,
                                "parameters": tool.input_schema,
                            },
                        }
                    )

            iteration = 0

            # Tracks how many messages were added in this specific turn
            start_msg_count = len(self.messages)

            # Tracks (tool_name, args_key) pairs already called this turn to prevent duplicates
            seen_tool_calls: set[tuple[str, str]] = set()

            requested_tools = {
                t_name for t_name, req in [
                    ("get_weather", has_weather),
                    ("discover_events", has_events),
                    ("search_books", has_books),
                    ("find_budget_hotels", has_hotels),
                    ("travel_route", has_route),
                    ("famous_restaurants", has_restaurants),
                ] if req
            }

            available_tool_names = {tool.name for tool in tools_response.tools}
            # Full plans need every travel domain; focused requests need the
            # domains explicitly requested. Reserve one turn for final prose.
            required_tools = available_tool_names if has_travel_plan else requested_tools
            max_iterations = max(3, len(required_tools) + 2)

            while iteration < max_iterations:
                iteration += 1
                if status_callback:
                    await status_callback(f"Reasoning (Step {iteration})...")

                called_tools = {k[0] for k in seen_tool_calls}
                all_required_tools_called = bool(required_tools) and required_tools.issubset(called_tools)

                tools_for_step = ollama_tools
                if is_general_query or all_required_tools_called:
                    tools_for_step = None

                # On step 1 for non-general queries, force tool calling if tools are offered
                step_tool_choice = "required" if (iteration == 1 and tools_for_step is not None and not is_general_query) else "auto"

                # Invoke LLM
                response = await self._run_sync(
                    self._call_llm_with_retry, self.messages, tools=tools_for_step, tool_choice=step_tool_choice
                )
                message = response.message
                tool_calls = getattr(message, "tool_calls", None)

                # Calls are only valid while tools are offered.  Do not suppress
                # later calls merely because one requested tool already ran.
                if tools_for_step is None or is_general_query:
                    tool_calls = None

                # Allow requested tool calls through
                elif tool_calls:
                    filtered_calls = []
                    for tc in tool_calls:
                        t_name = tc.function.name
                        if t_name not in available_tool_names:
                            continue
                        if (has_weather and t_name == "get_weather") or \
                           (has_events and t_name == "discover_events") or \
                           (has_books and t_name == "search_books") or \
                           (has_hotels and t_name == "find_budget_hotels") or \
                           (has_restaurants and t_name == "famous_restaurants") or \
                           (has_route and t_name == "travel_route") or \
                           has_travel_plan:
                            filtered_calls.append(tc)
                    # filtered_calls == [] means the LLM called tools that were never requested —
                    # treat that as no valid tool calls (None) so the loop exits cleanly.
                    tool_calls = filtered_calls if filtered_calls else None

                # Add response to messages history
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": message.content or "",
                }
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                self.messages.append(assistant_msg)

                # If no tool calls, break the tool loop
                if not tool_calls:
                    break

                # Filter duplicates before parallel execution
                unique_tool_calls = []
                for tool_call in tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = tool_call.function.arguments
                    call_key = (tool_name, json.dumps(tool_args, sort_keys=True))
                    
                    if call_key in seen_tool_calls:
                        if status_callback:
                            await status_callback(f"Skipping duplicate call to '{tool_name}'...")
                        self.messages.append(
                            {
                                "role": "tool",
                                "content": json.dumps({"notice": "Duplicate request skipped; use the previous result."}),
                                "name": tool_name,
                                "tool_call_id": tool_call.id,
                            }
                        )
                    else:
                        seen_tool_calls.add(call_key)
                        unique_tool_calls.append(tool_call)

                # Execute all unique tool calls in parallel using asyncio.gather()
                if unique_tool_calls:
                    if status_callback:
                        await status_callback(f"Executing {len(unique_tool_calls)} tools in parallel...")
                    
                    tasks = [
                        self._execute_tool_call_async(
                            session,
                            tool_call,
                            reqs,
                            status_callback,
                            tool_context,
                            is_weather_only,
                            is_hotels_only,
                            is_restaurants_only,
                            is_events_only,
                            is_books_only,
                            has_travel_plan,
                        )
                        for tool_call in unique_tool_calls
                    ]
                    
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    for idx, result in enumerate(results):
                        if isinstance(result, Exception):
                            logger.error(f"Tool execution error: {result}")
                            tool_call = unique_tool_calls[idx]
                            self.messages.append(
                                {
                                    "role": "tool",
                                    "content": json.dumps({"error": str(result)}),
                                    "name": tool_call.function.name,
                                    "tool_call_id": tool_call.id,
                                }
                            )
                        else:
                            tool_name, truncated_result, result_data, result_text = result
                            tool_call = unique_tool_calls[idx]
                            
                            if hasattr(self, "last_metrics") and self.last_metrics is not None:
                                self.last_metrics["tool_calls"] += 1
                            
                            self.messages.append(
                                {
                                    "role": "tool",
                                    "content": truncated_result,
                                    "name": tool_name,
                                    "tool_call_id": tool_call.id,
                                }
                            )

            # --- REFLECTION / FINAL ANSWER SELECTION ---
            # Retrieve the latest assistant message content with actual human text (excluding tool call blocks and XML tags)
            assistant_messages = [
                m for m in self.messages
                if m.get("role") == "assistant"
                and m.get("content")
                and str(m.get("content")).strip()
                and not m.get("tool_calls")
                and not str(m.get("content")).strip().startswith(("{", "[", "```json", "`{", "[[{", "<tool_call", "<function"))
            ]
            if assistant_messages:
                last_answer = assistant_messages[-1].get("content") or ""
            else:
                # If assistant text is empty or only had tool calls, format direct response from tool_context
                if tool_context.get("weather") and is_weather_only:
                    w = tool_context["weather"]
                    city_name = w.get("city", reqs.destination)
                    temp = w.get("temperature_c")
                    wind = w.get("windspeed_kmh")
                    fc = w.get("forecast_next_12h", {})
                    rain_p = fc.get("max_rain_probability_percent", 0)
                    last_answer = (
                        f"### Current Weather in {city_name}\n"
                        f"- **Temperature:** {temp}°C\n"
                        f"- **Wind Speed:** {wind} km/h\n"
                        f"- **Rain Probability:** {rain_p}%\n\n"
                        f"*(Note: Values reflect current real-time meteorological conditions).* "
                    )
                elif tool_context.get("route") and is_route_only:
                    r = tool_context["route"]
                    src = r.get("source", reqs.origin or "Origin")
                    dest = r.get("destination", reqs.destination or "Destination")
                    dist = r.get("distance_km", "")
                    time_est = r.get("travel_time", "")
                    rec = r.get("recommended_mode", "Commercial Airline Flight")
                    opts = r.get("transport_options", [])
                    opt_lines = [f"- **{opt.get('mode', 'Transit')}:** {opt.get('option', '')} — *Duration: {opt.get('duration', time_est)}* | Cost: {opt.get('approx_cost', 'Variable')}" for opt in opts]
                    last_answer = (
                        f"### Best Travel Route: {src} to {dest}\n"
                        f"- **Distance:** {dist}\n"
                        f"- **Travel Time:** {time_est}\n"
                        f"- **Recommended Mode:** {rec}\n\n"
                        f"**Transport Options:**\n" + ("\n".join(opt_lines) if opt_lines else "- Flight travel recommended.")
                    )
                elif tool_context.get("restaurants") and is_restaurants_only:
                    r_list = tool_context["restaurants"]
                    city_name = reqs.destination
                    lines = [f"### Famous Restaurants in {city_name}\n"]
                    for r in r_list[:5]:
                        lines.append(f"- **{r.get('restaurant_name')}** ({r.get('speciality', 'Local Cuisines')}) — *Rating: {r.get('rating', '4.5 ⭐')}* | Location: {r.get('location', city_name)}")
                    last_answer = "\n".join(lines)
                elif tool_context.get("hotels") and is_hotels_only:
                    h_list = tool_context["hotels"]
                    city_name = reqs.destination
                    lines = [f"### Budget Accommodations in {city_name}\n"]
                    for h in h_list[:5]:
                        lines.append(f"- **{h.get('hotel_name')}** ({h.get('hotel_class', 'Hotel')}) — *Price: {h.get('price_range', 'Budget')}* | Rating: {h.get('review_rating', '4.3 ⭐')}")
                    last_answer = "\n".join(lines)
                elif tool_context.get("events") and is_events_only:
                    e_list = tool_context["events"]
                    city_name = reqs.destination
                    lines = [f"### Upcoming Events in {city_name}\n"]
                    for e in e_list[:5]:
                        lines.append(f"- **{e.get('source', 'Event')}:** {e.get('summary', '')}")
                    last_answer = "\n".join(lines)
                elif tool_context.get("books") and is_books_only:
                    b_list = tool_context["books"]
                    city_name = reqs.destination
                    lines = [f"### Recommended Books for {city_name}\n"]
                    for b in b_list[:5]:
                        lines.append(f"- **{b.get('title', 'Book')}** by {b.get('author', 'Unknown')} ({b.get('first_publish_year', 'N/A')})")
                    last_answer = "\n".join(lines)
                else:
                    last_answer = self.messages[-1].get("content") or ""

            # Reflection is a second full LLM request.  Keep it opt-in so a
            # normal query does not double token consumption after tool calls.
            if (
                not self.settings.agent_reflection_enabled
                or is_single_tool_query
                or is_general_query
                or has_travel_plan  # Skip reflection for full travel plans
            ):
                final_answer = last_answer
                if self.last_metrics is not None:
                    self.last_metrics["reflection_skipped"] = True
                logger.debug("Reflection skipped — single-tool or general query")
            else:
                if status_callback:
                    await status_callback("Polishing and personalising response...")

                # Lightweight reflection: send query + draft only (no repeated tool outputs)
                # Tool data is already embedded in the draft; repeating it wastes 600-1800 tokens
                ref_sys = _REFLECT_TRAVEL if has_travel_plan else _REFLECT_GENERAL
                reflection_prompt = [
                    {"role": "system", "content": ref_sys},
                    {"role": "user", "content": f"Query: {user_query}\n\nDraft:\n{last_answer}"},
                ]

                # Snapshot metrics before reflection to compute reflection-specific cost
                pre_ref_in = self.last_metrics["input_tokens"] if self.last_metrics else 0
                pre_ref_out = self.last_metrics["output_tokens"] if self.last_metrics else 0

                ref_resp = await self._run_sync(
                    self._call_llm_with_retry, reflection_prompt
                )
                ref_content = ref_resp.message.content or ""
                # Strip chain-of-thought tags before evaluating content
                ref_content = re.sub(r"<think>.*?</think>", "", ref_content, flags=re.DOTALL).strip()

                # The reflection prompt says "reply OK if correct" — honour that contract.
                # Treat any short approval token as a pass (keep the original draft unchanged).
                _APPROVAL_TOKENS = {"ok", "looks good", "lgtm", "correct", "good", "approved", "pass", "✓", "✅"}
                _is_approval = (
                    not ref_content                                  # empty response
                    or ref_content.lower().rstrip(".! ") in _APPROVAL_TOKENS  # exact approval word
                    or (len(ref_content) < 20 and ref_content.lower().replace(" ", "").startswith("ok"))
                )

                if _is_approval:
                    # Reflection confirmed draft is correct — keep it untouched
                    logger.debug("Reflection returned approval token (%r) — draft kept.", ref_content)
                    final_answer = last_answer
                else:
                    # Reflection returned actual corrections — use them
                    logger.debug("Reflection returned corrections (%d chars).", len(ref_content))
                    final_answer = ref_content

                # Record reflection-specific token cost
                if self.last_metrics is not None:
                    self.last_metrics["reflection_input_tokens"] = self.last_metrics["input_tokens"] - pre_ref_in
                    self.last_metrics["reflection_output_tokens"] = self.last_metrics["output_tokens"] - pre_ref_out

            # --- POST-GENERATION QUALITY GATE ---
            # Clean up any leftover tool JSON or XML prefixes from raw text tool-calling models
            clean_answer = final_answer.strip()
            clean_answer = re.sub(r"<tool_call>[\s\S]*?</tool_call>", "", clean_answer, flags=re.IGNORECASE).strip()
            clean_answer = re.sub(r"<function[=\s][\s\S]*?</function>", "", clean_answer, flags=re.IGNORECASE).strip()
            if clean_answer.startswith(("[[{", "[{", "```json", "`{", "{\"name\":", "[{\"name\":")):
                # Extract markdown prose following the JSON block
                lines = clean_answer.splitlines()
                prose_lines = [l for l in lines if not l.strip().startswith(("[", "{", "]", "}", "```", "`", "\"name\":", "\"parameters\":", "\"arguments\":"))]
                clean_answer = "\n".join(prose_lines).strip()
            final_answer = clean_answer

            if has_travel_plan and not is_single_tool_query:
                final_answer = validate_and_enforce_sections(final_answer, reqs, tool_context)

            # Persist the final answer into conversation history.
            # The loop may have ended on a tool message (role="tool") rather than an assistant
            # message — blindly overwriting messages[-1] would corrupt tool history.
            # Safe strategy: update in-place only if the last message is already ours (assistant);
            # otherwise append a fresh assistant message.
            if self.messages and self.messages[-1].get("role") == "assistant":
                self.messages[-1]["content"] = final_answer
            else:
                self.messages.append({"role": "assistant", "content": final_answer})

            # Remove any temporary system messages we added during this turn
            self.messages = [m for idx, m in enumerate(self.messages) if m.get("role") != "system" or idx == 0]

            # Phase 3: Cache the final response only if it is a valid, high-quality prose response
            is_valid_cacheable_response = (
                self._response_cache_enabled
                and bool(final_answer and len(final_answer.strip()) > 30)
                and not final_answer.strip().startswith(("[", "{", "`", "<", "Error", "I encountered an error", "Data unavailable"))
                and "<tool_call>" not in final_answer
                and "<function" not in final_answer
                and "Transport route data unavailable" not in final_answer
                and "No hotel information available" not in final_answer
                and "No restaurant recommendations available" not in final_answer
            )
            if is_valid_cacheable_response:
                global_cache.set(cache_key, final_answer, fresh_ttl=3600.0)
                logger.info(f"[Phase 3] Cached valid response for query: {user_query[:50]}...")

            if hasattr(self, "last_metrics") and self.last_metrics is not None:
                self.last_metrics["latency_sec"] = round(time.monotonic() - start_time, 2)
                logger.info(
                    f"[Metrics] in={self.last_metrics['input_tokens']} "
                    f"out={self.last_metrics['output_tokens']} "
                    f"total={self.last_metrics['total_tokens']} "
                    f"tools={self.last_metrics['tool_calls']} "
                    f"reflect_in={self.last_metrics['reflection_input_tokens']} "
                    f"reflect_out={self.last_metrics['reflection_output_tokens']} "
                    f"reflect_skipped={self.last_metrics['reflection_skipped']} "
                    f"cached={self.last_metrics['response_cached']} "
                    f"latency={self.last_metrics['latency_sec']}s "
                    f"[Phase 2: Parallel Tool Execution Enabled] "
                    f"[Phase 3: Response Caching Enabled]"
                )

            return final_answer


        except BaseException as e:
            # Catch anyio TaskGroup / BaseExceptionGroup errors and return a clean message
            if hasattr(e, "exceptions"):
                errs = "; ".join(str(sub) for sub in e.exceptions)
            else:
                errs = str(e)
            logger.error(f"Agent loop error: {errs}", exc_info=True)
            error_response = f"I encountered an error while processing your request: {errs}. Please try again."
            self.messages.append({"role": "assistant", "content": error_response})
            return error_response
