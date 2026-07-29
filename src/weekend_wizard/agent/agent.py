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
                    "The MCP server provides the following tools: 'get_weather', 'search_books', 'get_joke', 'get_dog_image', and 'get_trivia'. "
                    "When the user asks about MCP tools, explain that you have access to these 5 tools via the Model Context Protocol. "
                    "Only answer queries using the tool output information. "
                    "When a tool output contains URLs (like image URLs), always include the raw URL as a plain "
                    "text link (e.g. 'Image URL: https://...') so the user can access it. If the tools "
                    "do not provide the needed information, state it clearly."
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
                    "The MCP server provides the following tools: 'get_weather', 'search_books', 'get_joke', 'get_dog_image', and 'get_trivia'. "
                    "When the user asks about MCP tools, explain that you have access to these 5 tools via the Model Context Protocol. "
                    "Only answer queries using the tool output information. "
                    "When a tool output contains URLs (like image URLs), always include the raw URL as a plain "
                    "text link (e.g. 'Image URL: https://...') so the user can access it. If the tools "
                    "do not provide the needed information, state it clearly."
                ),
            }
        ]

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True
    )
    def _call_ollama_with_retry(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> Any:
        """Helper to invoke Ollama with exponential backoff on failure."""
        kwargs: dict[str, Any] = {
            "model": self.settings.ollama_model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        return ollama.chat(**kwargs)

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
                response = self._call_ollama_with_retry(self.messages, tools=ollama_tools)
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

            # Build history string of the conversation prior to the latest user prompt
            history_list = []
            for msg in self.messages[: start_msg_count - 1]:
                role = msg.get("role")
                content = msg.get("content")
                if content and isinstance(role, str) and role != "system":
                    history_list.append(f"{role.upper()}: {content}")
            history_str = "\n".join(history_list)

            last_answer = self.messages[-1].get("content") or ""
            reflection_prompt = [
                {
                    "role": "system",
                    "content": (
                        "You are a quality assurance reviewer. Review the draft response and output a refined version. "
                        "Ensure the response is accurate, neat, and highly friendly. "
                        "CRITICAL: Focus ONLY on answering the latest user query. Do NOT merge or repeat answers "
                        "to previous queries from the conversation history unless specifically asked to do so. "
                        "If the user query is answering a trivia question from history, check if they are correct. "
                        "If the current turn's tool outputs contain a dog image URL, ensure that exact URL is "
                        "preserved in the final response. Do not add or hallucinate placeholder URLs. "
                        "Do NOT mention reflection or QA in the output. Output only the clean refined response."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Conversation History:\n{history_str}\n\n"
                        f"Latest User Query: {user_query}\n\n"
                        f"Tool Outputs in this turn:\n{tool_outputs_str}\n\n"
                        f"Draft Response to refine:\n{last_answer}"
                    ),
                },
            ]

            ref_resp = self._call_ollama_with_retry(reflection_prompt)
            final_answer = ref_resp.message.content or last_answer

            # Update the last assistant response with the QA refined answer
            self.messages[-1]["content"] = final_answer

            return final_answer
