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
    build_compact_preference_context,
    auto_update_preferences_from_text,
)
from planpilot.utils.validation import (
    extract_requirements,
    validate_and_enforce_sections,
    UserRequirements,
    MANDATORY_SECTIONS,
)

# ---------------------------------------------------------------------------
# Centralized prompt constants — single source of truth, no runtime duplication
# ---------------------------------------------------------------------------

# Compact 11-section system prompt (~180 tokens vs original ~420 tokens)
_SYSTEM_PROMPT = (
    "You are PlanPilot, an AI Travel Concierge. Use MCP tools to answer travel queries.\n"
    "Tools: travel_route, get_weather, find_budget_hotels, famous_restaurants, discover_events, search_books.\n\n"
    "TRAVEL PLAN STRUCTURE — use these exact # headers in order:\n"
    "# Destination Overview | # Weather | # How to Reach | # Estimated Budget | "
    "# Accommodation Options | # Restaurants | # Upcoming Events | # History of Destination | "
    "# Recommended Books | # Suggested Itinerary | # Travel Tips\n\n"
    "RULES:\n"
    "- Cross-border/>2000km: flights only, no drive/train.\n"
    "- Match cuisine exactly (Indian→Indian only, Vegetarian→veg only).\n"
    "- Hotel Class (3-Star) ≠ Review Rating (4.5⭐). Show both separately.\n"
    "- No travel dates: weather = current/seasonal baseline, never invented forecasts.\n"
    "- Always include units (°C, km/h, km, currency)."
)

# Lightweight verification prompt for the reflection pass (~80 tokens vs ~280 tokens)
_REFLECT_TRAVEL = (
    "You are a travel guide editor. Fix the draft below: ensure all 11 # section headers exist "
    "(Destination Overview, Weather, How to Reach, Estimated Budget, Accommodation Options, "
    "Restaurants, Upcoming Events, History of Destination, Recommended Books, Suggested Itinerary, Travel Tips), "
    "no hallucinated data, flights-only for cross-border routes, correct cuisine match. "
    "Output the corrected guide only, no commentary."
)
_REFLECT_SINGLE = (
    "You are a travel assistant editor. Reformat the draft as clean markdown. "
    "Answer only the topic asked. No empty sections. No QA commentary."
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
            {"role": "system", "content": _SYSTEM_PROMPT}
        ]

    def reset(self) -> None:
        """Reset the conversation history."""
        self.messages = [{"role": "system", "content": _SYSTEM_PROMPT}]

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

    def _prepare_gemini_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Format tools into Gemini function_declarations format with uppercase types."""
        declarations = []
        for t in tools:
            func = t.get("function", {})
            params = func.get("parameters", {})
            properties = {}
            for pname, pdata in params.get("properties", {}).items():
                ptype = pdata.get("type", "STRING")
                if isinstance(ptype, list):
                    ptype = [x for x in ptype if x != "null"][0] if ptype else "STRING"
                properties[pname] = {
                    "type": str(ptype).upper(),
                    "description": pdata.get("description", ""),
                }
            declarations.append({
                "name": func.get("name"),
                "description": func.get("description", ""),
                "parameters": {
                    "type": "OBJECT",
                    "properties": properties,
                    "required": params.get("required", []),
                }
            })
        return [{"function_declarations": declarations}]

    def _prepare_gemini_payload(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Format PlanPilot messages for Google Gemini generateContent API with system_instruction."""
        contents = []
        system_texts = []
        merged = self._merge_system_messages(messages)
        for msg in merged:
            role = msg.get("role")
            content = msg.get("content") or ""
            if role == "system":
                system_texts.append(content)
            elif role == "user":
                contents.append({"role": "user", "parts": [{"text": content}]})
            elif role == "assistant":
                parts = []
                if content:
                    parts.append({"text": content})
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        parts.append({"functionCall": {"name": tc.function.name, "args": tc.function.arguments}})
                if not parts:
                    parts.append({"text": ""})
                contents.append({"role": "model", "parts": parts})
            elif role == "tool":
                tname = msg.get("name", "tool")
                contents.append({"role": "user", "parts": [{"text": f"[Tool Output from '{tname}']:\n{content}"}]})

        if not contents:
            contents.append({"role": "user", "parts": [{"text": "Hello"}]})

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": 0.0},
        }
        if system_texts:
            payload["system_instruction"] = {"parts": [{"text": "\n\n".join(system_texts)}]}
        if tools:
            payload["tools"] = self._prepare_gemini_tools(tools)
        return payload

    def _call_gemini(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        """Call Google Gemini generateContent API."""
        import httpx
        key = self.settings.google_api_key
        model = self.settings.gemini_model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

        payload = self._prepare_gemini_payload(messages, tools)

        with httpx.Client(timeout=45.0) as client:
            resp = client.post(url, json=payload)
            if resp.status_code >= 400:
                print("GEMINI API ERROR RESPONSE BODY:", resp.text, flush=True)
                resp.raise_for_status()
            data = resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            return LLMResponse(message=LLMMessage(content="", tool_calls=[]))

        content_parts = candidates[0].get("content", {}).get("parts", [])
        text_content = ""
        tool_calls: list[ToolCall] = []

        for p in content_parts:
            if "text" in p:
                text_content += p["text"]
            if "functionCall" in p:
                fc = p["functionCall"]
                fname = fc.get("name")
                fargs = fc.get("args", {})
                tool_calls.append(
                    ToolCall(
                        id=fc.get("id", f"call_{len(tool_calls)+1}"),
                        function=ToolFunction(name=fname, arguments=fargs),
                    )
                )

        if text_content:
            text_content = re.sub(r"<think>.*?</think>", "", text_content, flags=re.DOTALL).strip()

        if not tool_calls and text_content:
            tool_calls = self._parse_text_tool_calls(text_content)

        # Track usage metrics
        usage = data.get("usageMetadata", {})
        prompt_tokens = usage.get("promptTokenCount", 0)
        completion_tokens = usage.get("candidatesTokenCount", 0)
        if hasattr(self, "last_metrics") and self.last_metrics is not None:
            self.last_metrics["input_tokens"] += prompt_tokens
            self.last_metrics["output_tokens"] += completion_tokens
            self.last_metrics["total_tokens"] += (prompt_tokens + completion_tokens)
            self.last_metrics["llm_calls"] += 1

        return LLMResponse(message=LLMMessage(content=text_content, tool_calls=tool_calls))

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

    def _call_openrouter(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        """Helper to invoke OpenRouter API with OpenAI-compatible schemas, tool calling, and backoff retry."""
        import time
        import httpx

        # 1. Format messages for OpenRouter (OpenAI-compatible)
        openrouter_messages = self._prepare_groq_messages(messages)

        # 2. Invoke OpenRouter API
        url = f"{self.settings.openrouter_base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
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
            payload["tool_choice"] = "auto"

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
                    # If model doesn't support tools, fallback to no-tools
                    if ("tools" in resp.text.lower() or "not supported" in resp.text.lower()) and "tools" in payload:
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
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        """Helper to invoke the configured LLM provider with exponential backoff on failure."""
        import time
        import httpx

        provider = self.settings.llm_provider.lower().strip()

        if provider == "gemini" and self.settings.google_api_key:
            return self._call_gemini(messages, tools)

        elif provider == "openrouter" and self.settings.openrouter_api_key:
            return self._call_openrouter(messages, tools)

        elif provider == "groq" and self.settings.groq_api_key:
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
                max_retries = 3
                for attempt in range(max_retries):
                    resp = client.post(url, json=payload, headers=headers)
                    if resp.status_code == 429:
                        retry_after = int(resp.headers.get("retry-after", "15"))
                        print(f"Groq Rate Limit (429). Waiting {retry_after + 2}s before retry...", flush=True)
                        time.sleep(retry_after + 2)
                        continue
                    if resp.status_code >= 400:
                        print("GROQ API ERROR RESPONSE BODY:", resp.text, flush=True)
                        if "invalid_api_key" in resp.text or resp.status_code == 401:
                            raise ValueError(
                                "🔑 Invalid or Expired Groq API Key! Please get a free API key at https://console.groq.com/keys and enter it in your .env file or Streamlit sidebar."
                            )
                        if ("not supported with this model" in resp.text or "output_parse_failed" in resp.text or "Parsing failed" in resp.text) and "tools" in payload:
                            print(f"Model '{payload['model']}' tool schema or parsing issue. Falling back to text tool calling...", flush=True)
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
                    if resp.status_code < 400:
                        break

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
            "reflection_input_tokens": 0,
            "reflection_output_tokens": 0,
            "reflection_skipped": False,
            "model": self.settings.groq_model if self.settings.llm_provider.lower().strip() == "groq" else self.settings.ollama_model,
            "provider": self.settings.llm_provider.upper().strip()
        }
        start_time = time.monotonic()
        provider = self.settings.llm_provider.lower().strip()

        # Ensure system prompt is always the centralized constant (no per-turn rewrite)
        if not self.messages or self.messages[0].get("role") != "system":
            self.messages.insert(0, {"role": "system", "content": _SYSTEM_PROMPT})
        else:
            self.messages[0]["content"] = _SYSTEM_PROMPT

        if status_callback:
            await status_callback("Connecting to tool server...")

        # Append new user message to conversation history
        self.messages.append({"role": "user", "content": user_query})

        # --- History sliding window: keep system + last 10 non-system messages ---
        system_msg = self.messages[:1]
        history = [m for m in self.messages[1:] if m.get("role") != "system"]
        if len(history) > 10:
            history = history[-10:]
        self.messages = system_msg + history

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
            has_weather = has_events = has_books = has_hotels = has_route = has_restaurants = has_travel_plan = False

        is_general_query = not (has_weather or has_events or has_books or has_hotels or has_route or has_restaurants or has_travel_plan)

        # Single-domain query flags
        is_weather_only = has_weather and not (has_events or has_books or has_hotels or has_route or has_restaurants or has_travel_plan)
        is_events_only = has_events and not (has_weather or has_books or has_hotels or has_route or has_restaurants or has_travel_plan)
        is_books_only = has_books and not (has_weather or has_events or has_hotels or has_route or has_restaurants or has_travel_plan)
        is_hotels_only = has_hotels and not (has_weather or has_events or has_books or has_route or has_restaurants or has_travel_plan)
        is_route_only = has_route and not (has_weather or has_events or has_books or has_hotels or has_restaurants or has_travel_plan)
        is_restaurants_only = has_restaurants and not (has_weather or has_events or has_books or has_hotels or has_route or has_travel_plan)
        # Flag: single tool query → skip reflection pass
        is_single_tool_query = is_weather_only or is_events_only or is_books_only or is_restaurants_only or is_hotels_only or is_route_only

        # Auto-extract preference declarations (e.g., 'I live in Indore', 'Vegetarian') from query prompt
        auto_update_preferences_from_text(user_query)

        # Structured Requirement Extraction
        prefs = load_preferences()
        reqs = extract_requirements(user_query, user_prefs=prefs)

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

                    # Departure City Fallback for travel_route: if source is omitted or empty, use reqs.origin
                    if tool_name == "travel_route":
                        src_arg = str(tool_args.get("source", "")).strip()
                        if not src_arg or src_arg.lower() in ("none", "null", "unknown", "city", "my city", "home"):
                            if reqs.origin:
                                tool_args["source"] = reqs.origin
                                if status_callback:
                                    await status_callback(f"Using departure location '{reqs.origin}'...")

                    # Cuisine Preference Auto-filling for famous_restaurants
                    if tool_name == "famous_restaurants" and not tool_args.get("query"):
                        if reqs.cuisine:
                            tool_args["query"] = f"{reqs.cuisine} food"

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
                        # Cache parsed output into tool_context for quality gate
                        try:
                            parsed_json = json.loads(result_text)
                            if tool_name == "get_weather" and isinstance(parsed_json, dict):
                                tool_context["weather"] = parsed_json
                            elif tool_name == "travel_route" and isinstance(parsed_json, dict):
                                tool_context["route"] = parsed_json
                            elif tool_name == "find_budget_hotels" and isinstance(parsed_json, list):
                                tool_context["hotels"] = parsed_json
                            elif tool_name == "famous_restaurants" and isinstance(parsed_json, list):
                                tool_context["restaurants"] = parsed_json
                            elif tool_name == "discover_events" and isinstance(parsed_json, list):
                                tool_context["events"] = parsed_json
                            elif tool_name == "search_books" and isinstance(parsed_json, list):
                                tool_context["books"] = parsed_json
                        except Exception:
                            pass
                    except Exception as e:
                        result_text = json.dumps({"error": f"Tool execution failed: {str(e)}"})

                    if status_callback:
                        await status_callback(f"Received output from '{tool_name}'")

                    # Summarize tool output for conversation history (200 chars max).
                    # Full JSON is already cached in tool_context for Quality Gate — no data loss.
                    truncated_result = result_text
                    if len(result_text) > 200:
                        truncated_result = result_text[:200] + "…[see tool_context for full data]"

                    # Append tool response
                    self.messages.append(
                        {"role": "tool", "content": truncated_result, "name": tool_name}
                    )

            # --- REFLECTION PASS ---
            last_answer = self.messages[-1].get("content") or ""

            # Skip reflection for simple single-tool queries (weather, books, restaurants, events)
            # These don't need a quality gate — saves ~1,200-2,000 tokens per simple query
            if is_single_tool_query or is_general_query:
                final_answer = last_answer
                if self.last_metrics is not None:
                    self.last_metrics["reflection_skipped"] = True
                logger.debug("Reflection skipped — single-tool or general query")
            else:
                if status_callback:
                    await status_callback("Verifying response quality...")

                # Lightweight reflection: send query + draft only (no repeated tool outputs)
                # Tool data is already embedded in the draft; repeating it wastes 600-1800 tokens
                ref_sys = _REFLECT_TRAVEL if (has_travel_plan or reqs.destination != "Destination") else _REFLECT_SINGLE
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
                final_answer = ref_resp.message.content or last_answer
                final_answer = re.sub(r"<think>.*?</think>", "", final_answer, flags=re.DOTALL).strip()

                # Record reflection-specific token cost
                if self.last_metrics is not None:
                    self.last_metrics["reflection_input_tokens"] = self.last_metrics["input_tokens"] - pre_ref_in
                    self.last_metrics["reflection_output_tokens"] = self.last_metrics["output_tokens"] - pre_ref_out

            # --- POST-GENERATION QUALITY GATE ---
            if has_travel_plan or reqs.destination != "Destination":
                final_answer = validate_and_enforce_sections(final_answer, reqs, tool_context)

            # Update the last assistant response with the QA refined answer
            self.messages[-1]["content"] = final_answer

            # Remove any temporary system messages we added during this turn
            self.messages = [m for idx, m in enumerate(self.messages) if m.get("role") != "system" or idx == 0]

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
                    f"latency={self.last_metrics['latency_sec']}s"
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
