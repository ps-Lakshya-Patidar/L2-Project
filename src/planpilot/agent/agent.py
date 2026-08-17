"""PlanPilot Agent Loop.

Orchestrates the client-side MCP session, connects to the local Ollama instance,
manages tool-calling loops, and performs a single reflection pass before returning the final response.
"""

from __future__ import annotations

import asyncio
import functools
import json
import re
import sys
from typing import Any

import ollama
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from tenacity import retry, stop_after_attempt, wait_exponential

from planpilot.utils.config import get_settings
from planpilot.utils.logger import logger
from planpilot.utils.preferences import (
    load_preferences,
    build_preference_context,
    auto_update_preferences_from_text,
)


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
    """Agent orchestrator connecting Ollama to the MCP Tool Server."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.server_params = StdioServerParameters(
            command=sys.executable, args=["-m", "planpilot.mcp_server"], env=None
        )
        self.last_metrics: dict[str, Any] | None = None
        self.messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are PlanPilot, a Personal AI Weekend Concierge powered by the Model Context Protocol (MCP) tool server. "
                    "The MCP server gives you access to three tools: 'get_weather', 'search_books', and 'discover_events'. "
                    "To call a tool, you MUST write the function call directly in your response in one of these formats:\n"
                    "- get_weather(city=\"Indore\")\n"
                    "- discover_events(city=\"Mumbai\", query=\"music concerts\")\n"
                    "- search_books(query=\"science fiction\")\n\n"
                    "Do not write introductory text, greetings, or placeholders when calling the tool. Write ONLY the tool call in your first turn and wait for the results. "
                    "Once the tool results are returned, summarize them and present your recommendations in your next turn. "
                    "Call ONLY the tools explicitly requested by or relevant to the user query. "
                    "WEATHER RULE: Report ONLY the weather for the specific day requested by the user (or current weather if no specific day is mentioned). Do NOT list a 3-day forecast unless explicitly requested. "
                    "Always include units: temperature in °C, windspeed in km/h, rainfall in mm. "
                    "BOOK FORMATTING RULE: When presenting book recommendations, render each title as a clickable Markdown link using the info_url from the tool output. Example: [The Great Gatsby](https://openlibrary.org/works/OL468431W). "
                    "WEEKEND PLAN RULE: Include Cozy, Adventure, and Budget-friendly plan options ONLY if the user explicitly requested a weekend plan (e.g. 'plan my weekend'). For standard weather, event, or book queries, DO NOT generate Cozy/Adventure/Budget headers—answer the user's specific request directly. "
                    "When user preferences are provided, use them to personalise recommendations for the requested topic only. "
                    "If the tools do not provide information, state it clearly. Do NOT invent data."
                ),
            }
        ]

    def reset(self) -> None:
        """Reset the conversation history."""
        self.messages = [
            {
                "role": "system",
                "content": (
                    "You are PlanPilot, a Personal AI Weekend Concierge powered by the Model Context Protocol (MCP) tool server. "
                    "The MCP server gives you access to three tools: 'get_weather', 'search_books', and 'discover_events'. "
                    "To call a tool, you MUST write the function call directly in your response in one of these formats:\n"
                    "- get_weather(city=\"Indore\")\n"
                    "- discover_events(city=\"Mumbai\", query=\"music concerts\")\n"
                    "- search_books(query=\"science fiction\")\n\n"
                    "Do not write introductory text, greetings, or placeholders when calling the tool. Write ONLY the tool call in your first turn and wait for the results. "
                    "Once the tool results are returned, summarize them and present your recommendations in your next turn. "
                    "Call ONLY the tools explicitly requested by or relevant to the user query. "
                    "WEATHER RULE: Report ONLY the weather for the specific day requested by the user (or current weather if no specific day is mentioned). Do NOT list a 3-day forecast unless explicitly requested. "
                    "Always include units: temperature in °C, windspeed in km/h, rainfall in mm. "
                    "BOOK FORMATTING RULE: When presenting book recommendations, render each title as a clickable Markdown link using the info_url from the tool output. Example: [The Great Gatsby](https://openlibrary.org/works/OL468431W). "
                    "WEEKEND PLAN RULE: Include Cozy, Adventure, and Budget-friendly plan options ONLY if the user explicitly requested a weekend plan (e.g. 'plan my weekend'). For standard weather, event, or book queries, DO NOT generate Cozy/Adventure/Budget headers—answer the user's specific request directly. "
                    "When user preferences are provided, use them to personalise recommendations for the requested topic only. "
                    "If the tools do not provide information, state it clearly. Do NOT invent data."
                ),
            }
        ]

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

    def _parse_text_tool_calls(self, content: str) -> list[ToolCall]:
        """Parse text-based tool calls (like get_weather({...}) or tool(key=val)) as a fallback for weak LLMs."""
        if not content:
            return []

        tool_calls = []

        # 1. Try to find JSON arrays/objects in the text (e.g. [{"name":"get_weather", "arguments":{...}}])
        json_pattern = r"(\[.*?\]|\{.*?\})"
        for block_match in re.finditer(json_pattern, content, re.DOTALL):
            block_str = block_match.group(1).strip()
            try:
                data = json.loads(block_str)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "name" in item:
                            t_name = item["name"]
                            t_args = item.get("arguments", {})
                            if t_name in ("get_weather", "search_books", "discover_events"):
                                tool_calls.append(ToolCall(function=ToolFunction(name=t_name, arguments=t_args)))
                elif isinstance(data, dict) and "name" in data:
                    t_name = data["name"]
                    t_args = data.get("arguments", {})
                    if t_name in ("get_weather", "search_books", "discover_events"):
                        tool_calls.append(ToolCall(function=ToolFunction(name=t_name, arguments=t_args)))
            except Exception:
                try:
                    fixed = block_str.replace("'", '"')
                    data = json.loads(fixed)
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and "name" in item:
                                t_name = item["name"]
                                t_args = item.get("arguments", {})
                                if t_name in ("get_weather", "search_books", "discover_events"):
                                    tool_calls.append(ToolCall(function=ToolFunction(name=t_name, arguments=t_args)))
                    elif isinstance(data, dict) and "name" in data:
                        t_name = data["name"]
                        t_args = data.get("arguments", {})
                        if t_name in ("get_weather", "search_books", "discover_events"):
                            tool_calls.append(ToolCall(function=ToolFunction(name=t_name, arguments=t_args)))
                except Exception:
                    pass

        # 2. If no JSON matched, fallback to parenthesized syntax get_weather(city="Ahmedabad")
        if not tool_calls:
            pattern = r"\b(get_weather|search_books|discover_events)\s*\((.*?)\)"
            matches = list(re.finditer(pattern, content))

            for match in matches:
                name = match.group(1)
                args_str = match.group(2).strip()

                args = {}
                if args_str.startswith("{") and args_str.endswith("}"):
                    try:
                        args = json.loads(args_str)
                    except Exception:
                        try:
                            fixed = args_str.replace("'", '"')
                            args = json.loads(fixed)
                        except Exception:
                            pass

                if not args and args_str:
                    kv_pattern = r"(\w+)\s*=\s*(?:['\"](.*?)['\"]|(\w+))"
                    kv_matches = re.findall(kv_pattern, args_str)
                    for kv in kv_matches:
                        k = kv[0]
                        v = kv[1] if kv[1] else kv[2]
                        if v.isdigit():
                            args[k] = int(v)
                        elif v.lower() == "true":
                            args[k] = True
                        elif v.lower() == "false":
                            args[k] = False
                        elif v.lower() == "none" or v.lower() == "null":
                            args[k] = None
                        else:
                            args[k] = v

                tool_calls.append(
                    ToolCall(function=ToolFunction(name=name, arguments=args))
                )

        return tool_calls

    def _prepare_groq_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Preprocess messages into OpenAI/Groq compatible schemas (preserving tool IDs)."""
        groq_msgs = []
        last_tool_ids = {}

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
                call_id = last_tool_ids.get(name, "call_gen_0")
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

    def _sanitize_tool_schema_for_groq(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sanitize JSON schemas to comply with Groq/OpenAI tool-calling specifications."""
        import copy
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

    @retry(
        stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=5, max=60), reraise=True
    )
    def _call_llm_with_retry(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        """Helper to invoke the configured LLM provider with exponential backoff on failure."""
        import time
        import httpx

        provider = self.settings.llm_provider.lower().strip()

        if provider == "groq" and self.settings.groq_api_key:
            # 1. Format messages for Groq
            groq_messages = self._prepare_groq_messages(messages)

            # 2. Invoke Groq API
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.settings.groq_api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.settings.groq_model,
                "messages": groq_messages,
                "temperature": 0.0,
            }
            is_compound_model = "compound" in self.settings.groq_model.lower() or "prompt-guard" in self.settings.groq_model.lower()
            if tools and not is_compound_model:
                payload["tools"] = self._sanitize_tool_schema_for_groq(tools)
                payload["tool_choice"] = "auto"

            with httpx.Client(timeout=60.0) as client:
                resp = client.post(url, json=payload, headers=headers)
                # Handle 429 rate limit: honour Retry-After header before raising
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("retry-after", "20"))
                    time.sleep(retry_after)
                if resp.status_code >= 400:
                    print("GROQ API ERROR RESPONSE BODY:", resp.text, flush=True)
                    if "invalid_api_key" in resp.text or resp.status_code == 401:
                        raise ValueError(
                            "🔑 Invalid or Expired Groq API Key! Please get a free API key at https://console.groq.com/keys and enter it in your .env file or Streamlit sidebar."
                        )
                    if "not supported with this model" in resp.text and "tools" in payload:
                        print(f"Model '{payload['model']}' does not support native JSON tools API. Falling back to text tool calling...", flush=True)
                        payload.pop("tools", None)
                        payload.pop("tool_choice", None)
                        resp = client.post(url, json=payload, headers=headers)
                    elif "model_not_found" in resp.text:
                        if payload["model"] != "openai/gpt-oss-20b":
                            print(f"Model '{payload['model']}' not supported on Groq API. Auto-falling back to 'openai/gpt-oss-20b'...", flush=True)
                            self.settings.groq_model = "openai/gpt-oss-20b"
                            payload["model"] = "openai/gpt-oss-20b"
                            resp = client.post(url, json=payload, headers=headers)
                        else:
                            raise ValueError(
                                f"🔑 Model '{payload['model']}' is unavailable. Please verify your Groq API key at https://console.groq.com/keys."
                            )
                resp.raise_for_status()
                data = resp.json()

            choice = data["choices"][0]["message"]
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
                    args = json.loads(args_str)
                except Exception:
                    args = {}
                tool_calls.append(
                    ToolCall(
                        id=tc.get("id", "call_gen"),
                        function=ToolFunction(name=name, arguments=args),
                    )
                )

            if not tool_calls and content:
                tool_calls = self._parse_text_tool_calls(content)

            # Track metrics if enabled
            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            if hasattr(self, "last_metrics") and self.last_metrics is not None:
                self.last_metrics["input_tokens"] += prompt_tokens
                self.last_metrics["output_tokens"] += completion_tokens
                self.last_metrics["total_tokens"] += (prompt_tokens + completion_tokens)
                self.last_metrics["llm_calls"] += 1

            return LLMResponse(message=LLMMessage(content=content, tool_calls=tool_calls))

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
        """Extract tool calls written as text (e.g. get_weather(city="Jaipur")) from LLM text responses."""
        valid_tools = ["get_weather", "search_books", "discover_events", "find_budget_hotels", "travel_route", "famous_restaurants"]
        tool_calls: list[ToolCall] = []
        for line in content.split("\n"):
            line = line.strip()
            for tname in valid_tools:
                if f"{tname}(" in line:
                    try:
                        arg_part = line.split(f"{tname}(", 1)[1].rsplit(")", 1)[0]
                        args: dict[str, Any] = {}
                        matches = re.findall(r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\w+))', arg_part)
                        for m in matches:
                            k = m[0]
                            val = m[1] or m[2] or m[3]
                            args[k] = val
                        tool_calls.append(ToolCall(function=ToolFunction(name=tname, arguments=args)))
                    except Exception:
                        pass
        return tool_calls

    async def _run_sync(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Run a blocking function in a thread executor, cleanly re-raising any exception.

        This prevents exceptions from the thread pool from being wrapped in
        anyio's BaseExceptionGroup (which happens when a coroutine raises
        while inside a stdio_client TaskGroup context).
        """
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(
                None, functools.partial(fn, *args, **kwargs)
            )
        except BaseException as e:
            # Unwrap ExceptionGroup if the executor wrapped our exception
            if hasattr(e, "exceptions") and len(e.exceptions) == 1:  # type: ignore[attr-defined]
                raise e.exceptions[0] from None  # type: ignore[attr-defined]
            raise

    async def run_query(self, user_query: str, status_callback: Any = None, goal: str | None = None) -> str:
        """Run the main agent loop: request -> tool detection -> tool execution -> reflection -> response."""
        import time
        self.last_metrics = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "latency_sec": 0.0,
            "llm_calls": 0,
            "tool_calls": 0,
            "model": self.settings.groq_model if self.settings.llm_provider.lower().strip() == "groq" else self.settings.ollama_model,
            "provider": self.settings.llm_provider.upper().strip()
        }
        start_time = time.monotonic()
          # 1. Dynamically set base system prompt based on provider to prevent syntax clashes (Groq vs Ollama)
        provider = self.settings.llm_provider.lower().strip()
        system_content = (
            "You are PlanPilot, a Personal AI Travel Planner powered by the Model Context Protocol (MCP) tool server. "
            "The MCP server gives you access to six tools: 'get_weather', 'search_books', 'discover_events', 'find_budget_hotels', 'travel_route', and 'famous_restaurants'. "
        )
        if provider == "groq":
            system_content += (
                "For requests about weather, travel routes, budget hotels, events, or famous restaurants, you MUST call the appropriate tool first. "
                "For comprehensive travel plan requests (e.g. 'Plan a trip to New York'), you MUST execute ALL 5 travel tools: "
                "1. travel_route, 2. get_weather, 3. find_budget_hotels, 4. famous_restaurants, 5. discover_events. "
                "Do NOT generate a final response until ALL 5 tools have been called. "
                "If the user specifies a cuisine or food preference (e.g. 'Indian food'), pass query='Indian food' to famous_restaurants(city=city, query='Indian food'). "
            )
        else:
            # Local model (Ollama)
            system_content += (
                "To call a tool, write the function call directly in your response in one of these formats:\n"
                "- travel_route(source=\"Ahmedabad\", destination=\"New York\")\n"
                "- get_weather(city=\"New York\")\n"
                "- find_budget_hotels(city=\"New York\", budget=\"low\")\n"
                "- discover_events(city=\"New York\")\n"
                "- famous_restaurants(city=\"New York\", query=\"Indian food\")\n"
                "- search_books(query=\"travel guide\")\n\n"
                "Do not write introductory text or greetings when calling tools. Write ONLY tool calls until all 5 travel tools are executed. "
                "If the user asks for specific food (e.g. 'Indian food'), pass query='Indian food' to famous_restaurants. "
            )
            
        system_content += (
            "\n\nCRITICAL OUTPUT FORMATTING & HALLUCINATION RULES:\n"
            "1. MANDATORY TOOL EXECUTION RULE: For any travel plan request, call ALL 5 tools (Route, Weather, Hotels, Restaurants, Events). Do NOT invent or output fake hotel names or fake events if the tool was not called.\n"
            "2. TRAVEL PLAN FORMAT RULE: When a travel plan is requested, your final output MUST be structured using these exact headers:\n"
            "   Destination:\n   <city>\n\n"
            "   Weather:\n   <summary with °C, km/h>\n\n"
            "   Travel Route:\n   <summary with distance, time, transport options>\n\n"
            "   Budget Hotels:\n   <recommended stays with price range and rating from find_budget_hotels output>\n\n"
            "   Events:\n   <local activities and events from discover_events output>\n\n"
            "   Restaurants:\n   <famous spots and specialities from famous_restaurants output>\n\n"
            "   Suggested Itinerary:\n   Day 1: <morning, afternoon, evening activities>\n   Day 2: <activities>\n   Day 3: <activities>\n\n"
            "   Reasoning:\n   <explain why these choices fit budget and food preferences>\n\n"
            "   Tools Used:\n   ✓ Weather\n   ✓ Route\n   ✓ Hotels\n   ✓ Events\n   ✓ Restaurants\n\n"
            "3. SINGLE QUERY RULE: For single-topic queries (e.g. only weather or only restaurants), answer directly using that specific tool.\n"
            "4. EARTH-ONLY RULE: Tools ONLY work for real locations on Earth.\n"
        )

        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0]["content"] = system_content
        else:
            self.messages.insert(0, {"role": "system", "content": system_content})

        if status_callback:
            await status_callback("Connecting to tool server...")

        # Append new user message to conversation history
        self.messages.append({"role": "user", "content": user_query})

        # Detect domain keywords in user query
        q_lower = user_query.lower()
        has_weather = any(kw in q_lower for kw in ["weather", "temperature", "forecast", "rain", "sunny", "climate"])
        has_events = any(kw in q_lower for kw in ["event", "concert", "exhibition", "festival", "show", "activities"])
        has_books = any(kw in q_lower for kw in ["book", "novel", "author", "reading", "read"])
        has_hotels = any(kw in q_lower for kw in ["hotel", "stay", "resort", "hostel", "accommodation", "lodging"])
        has_route = any(kw in q_lower for kw in ["route", "travel from", "how to reach", "transport", "distance", "how to travel"])
        has_restaurants = any(kw in q_lower for kw in ["restaurant", "eat", "food", "dining", "dish", "delicacy", "cafe", "place to eat"])
        has_travel_plan = any(kw in q_lower for kw in ["trip", "travel", "tour", "itinerary", "vacation", "holiday", "plan a trip", "plan my trip", "budget ₹", "budget rs", "day trip"]) or (sum([has_weather, has_events, has_hotels, has_route, has_restaurants]) >= 2)

        # Detect non-Earth locations — these should be answered from general knowledge, not via tools
        _non_earth = ["mars", "jupiter", "saturn", "venus", "mercury", "neptune", "uranus", "pluto",
                      "moon", "sun", "outer space", "space station", "iss", "europa", "titan",
                      "narnia", "hogwarts", "mordor", "wakanda", "gotham", "atlantis", "asgard"]
        mentions_non_earth = any(loc in q_lower for loc in _non_earth)
        if mentions_non_earth:
            has_weather = False
            has_events = False
            has_books = False
            has_hotels = False
            has_route = False
            has_restaurants = False
            has_travel_plan = False

        is_general_query = not (has_weather or has_events or has_books or has_hotels or has_route or has_restaurants or has_travel_plan)

        # Single-domain query flags
        is_weather_only = has_weather and not (has_events or has_books or has_hotels or has_route or has_restaurants or has_travel_plan)
        is_events_only = has_events and not (has_weather or has_books or has_hotels or has_route or has_restaurants or has_travel_plan)
        is_books_only = has_books and not (has_weather or has_events or has_hotels or has_route or has_restaurants or has_travel_plan)
        is_hotels_only = has_hotels and not (has_weather or has_events or has_books or has_route or has_restaurants or has_travel_plan)
        is_route_only = has_route and not (has_weather or has_events or has_books or has_hotels or has_restaurants or has_travel_plan)
        is_restaurants_only = has_restaurants and not (has_weather or has_events or has_books or has_hotels or has_route or has_travel_plan)

        # Auto-extract preference declarations (e.g., 'I live in Indore', 'Vegetarian') from query prompt
        auto_update_preferences_from_text(user_query)

        # Inject user preferences as contextual system message for this turn
        prefs = load_preferences()
        pref_context = build_preference_context(prefs)
        if goal:
            pref_context = f"Active Session Goal: {goal}. " + pref_context
        if pref_context:
            self.messages.append({
                "role": "system",
                "content": (
                    f"{pref_context}\n\n"
                    "INSTRUCTION: Fulfill the user's request using their stored JSON profile entities. "
                    "DEPARTURE CITY RULE: If the user did NOT specify a starting/departure city in their prompt, use 'home_city' from their profile as the source for travel_route and travel planning. "
                    "Only call tools directly relevant to the query."
                )
            })

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
                    if is_weather_only and tool.name != "get_weather":
                        continue
                    if is_events_only and tool.name != "discover_events":
                        continue
                    if is_books_only and tool.name != "search_books":
                        continue
                    if is_hotels_only and tool.name != "find_budget_hotels":
                        continue
                    if is_route_only and tool.name != "travel_route":
                        continue
                    if is_restaurants_only and tool.name != "famous_restaurants":
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

            # Max iterations to prevent infinite tool calling loops
            max_iterations = 5
            iteration = 0

            # Tracks how many messages were added in this specific turn
            start_msg_count = len(self.messages)

            # Tracks (tool_name, args_key) pairs already called this turn to prevent duplicates
            seen_tool_calls: set[tuple[str, str]] = set()

            while iteration < max_iterations:
                iteration += 1
                if status_callback:
                    await status_callback(f"Reasoning (Step {iteration})...")

                # If general query or tool already executed for single-intent query, pass tools=None
                # so the LLM outputs its natural language answer directly without unrequested tool calls.
                tools_for_step = ollama_tools
                if is_general_query or (seen_tool_calls and (is_weather_only or is_events_only or is_books_only)):
                    tools_for_step = None

                # Invoke local LLM in a thread so the blocking network call
                # does not stall the anyio TaskGroup managing the MCP subprocess.
                response = await self._run_sync(
                    self._call_llm_with_retry, self.messages, tools=tools_for_step
                )
                message = response.message
                tool_calls = getattr(message, "tool_calls", None)

                # Force-discard any tool calls for general knowledge queries
                if is_general_query:
                    tool_calls = None

                # Filter out irrelevant tool calls for single-intent queries
                elif tool_calls and (is_weather_only or is_events_only or is_books_only):
                    filtered_calls = []
                    for tc in tool_calls:
                        t_name = tc.function.name
                        if is_weather_only and t_name == "get_weather":
                            filtered_calls.append(tc)
                        elif is_events_only and t_name == "discover_events":
                            filtered_calls.append(tc)
                        elif is_books_only and t_name == "search_books":
                            filtered_calls.append(tc)
                    tool_calls = filtered_calls if filtered_calls else None

                # If tool calls were made, strip pre-tool draft content from this assistant message
                # to prevent draft placeholders (e.g. "[insert details]") from polluting chat history.
                content_to_save = "" if tool_calls else (message.content or "")

                # Add response to messages history (omit tool_calls key when None to avoid Groq API errors)
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": content_to_save,
                }
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                self.messages.append(assistant_msg)

                # If no tool calls, break the tool loop
                if not tool_calls:
                    break

                # Execute tool calls (skip duplicates within the same turn)
                for tool_call in tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = tool_call.function.arguments

                    # Departure City Fallback for travel_route: if source is omitted or empty, use home_city from user_preferences.json
                    if tool_name == "travel_route":
                        src_arg = str(tool_args.get("source", "")).strip()
                        if not src_arg or src_arg.lower() in ("none", "null", "unknown", "city", "my city", "home"):
                            home_city = prefs.get("home_city")
                            if home_city:
                                tool_args["source"] = home_city
                                if status_callback:
                                    await status_callback(f"Using stored home city '{home_city}' as departure location...")

                    # Cuisine Preference Auto-filling for famous_restaurants
                    if tool_name == "famous_restaurants" and not tool_args.get("query"):
                        for cuisine in ["indian", "italian", "chinese", "mexican", "thai", "japanese", "vegan", "vegetarian", "seafood", "street food"]:
                            if cuisine in q_lower:
                                tool_args["query"] = f"{cuisine.title()} food"
                                break

                    # Deduplicate: skip if exact same call already made this turn
                    call_key = (tool_name, json.dumps(tool_args, sort_keys=True))
                    if call_key in seen_tool_calls:
                        if status_callback:
                            await status_callback(
                                f"Skipping duplicate call to '{tool_name}'..."
                            )
                        continue
                    seen_tool_calls.add(call_key)

                    if status_callback:
                        await status_callback(
                            f"Calling tool '{tool_name}' with args {tool_args}..."
                        )

                    try:
                        # Call the tool through MCP client session
                        result = await session.call_tool(tool_name, arguments=tool_args)
                        if hasattr(self, "last_metrics") and self.last_metrics is not None:
                            self.last_metrics["tool_calls"] += 1
                        # Convert result content to a string block
                        result_text = "\n".join(
                            [block.text for block in result.content if hasattr(block, "text")]
                        )
                    except Exception as e:
                        result_text = json.dumps({"error": f"Tool execution failed: {str(e)}"})

                    if status_callback:
                        await status_callback(f"Received output from '{tool_name}'")

                    # Truncate overly long tool outputs (e.g. 5+ JSON objects) to keep context under Groq 6000 TPM limit
                    truncated_result = result_text
                    if len(result_text) > 1500:
                        truncated_result = result_text[:1500] + "\n...[truncated for token efficiency]"

                    # Append tool response
                    self.messages.append(
                        {"role": "tool", "content": truncated_result, "name": tool_name}
                    )

            # --- REFLECTION PASS ---
            if status_callback:
                await status_callback("Performing self-reflection review...")

            # Extract tool outputs *only* from the current turn
            current_turn_tool_outputs = []
            for msg in self.messages[start_msg_count:]:
                if msg.get("role") == "tool":
                    current_turn_tool_outputs.append(
                        f"[{msg.get('name')} output]: {msg.get('content')}"
                    )
            tool_outputs_str = "\n".join(current_turn_tool_outputs)

            last_answer = self.messages[-1].get("content") or ""
            if has_travel_plan:
                ref_sys_prompt = (
                    "You are a quality assurance reviewer and personalisation engine for PlanPilot AI Travel Planner. Review the draft response and output a refined version. "
                    "Ensure the response is accurate, beautifully formatted in clean markdown, and highly helpful. "
                    "TRAVEL PLAN MANDATORY STRUCTURE: Because the user requested a full trip plan or itinerary, you MUST output using these exact headers:\n\n"
                    "Destination:\n<city>\n\n"
                    "Weather:\n<summary with °C, km/h>\n\n"
                    "Travel Route:\n<summary with distance, time, transport options>\n\n"
                    "Hotels / Accommodations:\n<recommended Stays with price range and rating>\n\n"
                    "Events:\n<local activities and events>\n\n"
                    "Restaurants:\n<famous spots and specialities>\n\n"
                    "Suggested Itinerary:\nDay 1: <morning, afternoon, evening activities>\nDay 2: <activities>\nDay 3: <activities>\n\n"
                    "Trip Score:\n<0-100 score and quality label>\n\n"
                    "Reasoning:\n<explain why recommendations fit user budget and preferences>\n\n"
                    "Tools Used:\n✓ Weather\n✓ Route\n✓ Hotels\n✓ Events\n✓ Restaurants\n\n"
                    "Units: Always include units (temperature in °C, windspeed in km/h, distance in km).\n"
                    "Do NOT mention reflection or QA in the output."
                )
            else:
                ref_sys_prompt = (
                    "You are a quality assurance reviewer and personalisation engine for PlanPilot AI Travel Planner. Review the draft response and output a refined version. "
                    "Ensure the response is accurate, beautifully formatted in clean markdown, and highly helpful. "
                    "SINGLE-TOPIC QUERY RULE: The user asked ONLY for a specific item (e.g. only hotels, or only weather, or only restaurants). "
                    "Answer ONLY that specific topic directly using the provided tool output. "
                    "Do NOT output empty filler sections (e.g., 'Weather: Unfortunately...', 'Events: Unfortunately...', 'Suggested Itinerary: Unfortunately...') for topics the user did NOT request. "
                    "Do NOT mention reflection or QA in the output."
                )

            reflection_prompt = [
                {
                    "role": "system",
                    "content": ref_sys_prompt,
                },
                {
                    "role": "user",
                    "content": (
                        f"Latest User Query: {user_query}\n\n"
                        f"Tool Outputs in this turn:\n{tool_outputs_str}\n\n"
                        f"Draft Response to refine:\n{last_answer}"
                    ),
                },
            ]

            ref_resp = await self._run_sync(
                self._call_llm_with_retry, reflection_prompt
            )
            final_answer = ref_resp.message.content or last_answer
            final_answer = re.sub(r"<think>.*?</think>", "", final_answer, flags=re.DOTALL).strip()

            # Update the last assistant response with the QA refined answer
            self.messages[-1]["content"] = final_answer

            # Remove any temporary system messages we added during this turn
            self.messages = [m for idx, m in enumerate(self.messages) if m.get("role") != "system" or idx == 0]

            if hasattr(self, "last_metrics") and self.last_metrics is not None:
                self.last_metrics["latency_sec"] = round(time.monotonic() - start_time, 2)

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
