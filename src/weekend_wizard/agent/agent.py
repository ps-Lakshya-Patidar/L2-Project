"""Weekend Wizard Agent Loop.

Orchestrates the client-side MCP session, connects to the local Ollama instance,
manages tool-calling loops, and performs a single reflection pass before returning the final response.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import ollama
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from tenacity import retry, stop_after_attempt, wait_exponential

from weekend_wizard.utils.config import get_settings


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


class WeekendWizardAgent:
    """Agent orchestrator connecting Ollama to the MCP Tool Server."""

    def __init__(self) -> None:
        self.settings = get_settings()
        # Parameters to start the MCP server as a subprocess
        self.server_params = StdioServerParameters(
            command=sys.executable, args=["-m", "weekend_wizard.mcp_server"], env=None
        )
        self.messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are Weekend Wizard, a local AI assistant. You operate using the Model Context Protocol (MCP) tool server. "
                    "The MCP server provides the following tools: 'get_weather', 'search_books', and 'discover_events'. "
                    "When the user asks about available tools, explain that you have access to these 3 tools via the Model Context Protocol. "
                    "For weather, book recommendations, or event discovery requests, you MUST call the appropriate tool and only answer using the "
                    "information returned by the tool. If the user query is about topics you do not have tools for (such as general news, "
                    "math calculations, or general chit-chat), do NOT invoke any tools. Instead, reply directly to the user in plain text explaining "
                    "that you do not have access to that information. If the tools do not provide the needed information, state it clearly."
                ),
            }
        ]

    def reset(self) -> None:
        """Reset the conversation history."""
        self.messages = [
            {
                "role": "system",
                "content": (
                    "You are Weekend Wizard, a local AI assistant. You operate using the Model Context Protocol (MCP) tool server. "
                    "The MCP server provides the following tools: 'get_weather', 'search_books', and 'discover_events'. "
                    "When the user asks about available tools, explain that you have access to these 3 tools via the Model Context Protocol. "
                    "For weather, book recommendations, or event discovery requests, you MUST call the appropriate tool and only answer using the "
                    "information returned by the tool. If the user query is about topics you do not have tools for (such as general news, "
                    "math calculations, or general chit-chat), do NOT invoke any tools. Instead, reply directly to the user in plain text explaining "
                    "that you do not have access to that information. If the tools do not provide the needed information, state it clearly."
                ),
            }
        ]

    def _prepare_groq_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Preprocess messages into OpenAI/Groq compatible schemas (preserving tool IDs)."""
        groq_msgs = []
        last_tool_ids = {}

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            if role == "assistant" and msg.get("tool_calls"):
                formatted_calls = []
                for idx, tc in enumerate(msg["tool_calls"]):
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
                groq_msgs.append(msg)

        return groq_msgs

    def _prepare_ollama_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Preprocess messages into Ollama-compatible message schemas."""
        ollama_msgs = []
        for msg in messages:
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
            else:
                ollama_msgs.append(msg)
        return ollama_msgs

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True
    )
    def _call_llm_with_retry(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        """Helper to invoke the configured LLM provider with exponential backoff on failure."""
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
            }
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"

            with httpx.Client(timeout=30.0) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            choice = data["choices"][0]["message"]
            content = choice.get("content")

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

            return LLMResponse(message=LLMMessage(content=content, tool_calls=tool_calls))

        else:
            # Default to Ollama
            ollama_messages = self._prepare_ollama_messages(messages)

            kwargs: dict[str, Any] = {
                "model": self.settings.ollama_model,
                "messages": ollama_messages,
            }
            if tools:
                kwargs["tools"] = tools

            resp = ollama.chat(**kwargs)
            content = resp.message.content

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

            return LLMResponse(message=LLMMessage(content=content, tool_calls=tool_calls))

    async def run_query(self, user_query: str, status_callback: Any = None) -> str:
        """Run the main agent loop: request -> tool detection -> tool execution -> reflection -> response."""
        if status_callback:
            await status_callback("Connecting to tool server...")

        # Append new user message to conversation history
        self.messages.append({"role": "user", "content": user_query})

        async with (
            stdio_client(self.server_params) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            if status_callback:
                await status_callback("Initializing protocol handshake...")
            await session.initialize()

            # List tools from the server
            if status_callback:
                await status_callback("Retrieving registered tools...")
            tools_response = await session.list_tools()

            # Format tools for Ollama
            ollama_tools = []
            for tool in tools_response.tools:
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

            while iteration < max_iterations:
                iteration += 1
                if status_callback:
                    await status_callback(f"Reasoning (Step {iteration})...")

                # Invoke local LLM using the full stateful messages history
                response = self._call_llm_with_retry(self.messages, tools=ollama_tools)
                message = response.message

                # Add response to messages history
                self.messages.append(
                    {
                        "role": "assistant",
                        "content": message.content or "",
                        "tool_calls": getattr(message, "tool_calls", None),
                    }
                )

                # If no tool calls, break the tool loop
                tool_calls = getattr(message, "tool_calls", None)
                if not tool_calls:
                    break

                # Execute tool calls
                for tool_call in tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = tool_call.function.arguments

                    if status_callback:
                        await status_callback(
                            f"Calling tool '{tool_name}' with args {tool_args}..."
                        )

                    try:
                        # Call the tool through MCP client session
                        result = await session.call_tool(tool_name, arguments=tool_args)
                        # Convert result content to a string block
                        result_text = "\n".join(
                            [block.text for block in result.content if hasattr(block, "text")]
                        )
                    except Exception as e:
                        result_text = json.dumps({"error": f"Tool execution failed: {str(e)}"})

                    if status_callback:
                        await status_callback(f"Received output from '{tool_name}'")

                    # Append tool response
                    self.messages.append(
                        {"role": "tool", "content": result_text, "name": tool_name}
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
            reflection_prompt = [
                {
                    "role": "system",
                    "content": (
                        "You are a quality assurance reviewer. Review the draft response and output a refined version. "
                        "Ensure the response is accurate, neat, and highly friendly. "
                        "Make sure your output ONLY answers the latest user query. Do NOT merge, summarize, or repeat "
                        "unrelated items from previous turns. "
                        "Do NOT mention reflection or QA in the output. Output only the clean refined response."
                    ),
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

            ref_resp = self._call_llm_with_retry(reflection_prompt)
            final_answer = ref_resp.message.content or last_answer

            # Update the last assistant response with the QA refined answer
            self.messages[-1]["content"] = final_answer

            return final_answer
