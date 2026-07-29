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

            messages: list[dict[str, Any]] = [
                {
                    "role": "system",
                    "content": (
                        "You are Weekend Wizard, a local AI assistant. Use the provided tools to answer "
                        "the user's request. Only answer using the tool output information. If the tools "
                        "do not provide the needed information, state it clearly."
                    ),
                },
                {"role": "user", "content": user_query},
            ]

            # Max iterations to prevent infinite tool calling loops
            max_iterations = 5
            iteration = 0

            while iteration < max_iterations:
                iteration += 1
                if status_callback:
                    await status_callback(f"Reasoning (Step {iteration})...")

                # Invoke local LLM
                response = self._call_ollama_with_retry(messages, tools=ollama_tools)
                message = response.message

                # Add response to messages history
                messages.append(
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
                    messages.append({"role": "tool", "content": result_text, "name": tool_name})

            # --- REFLECTION PASS ---
            if status_callback:
                await status_callback("Performing self-reflection review...")

            last_answer = messages[-1].get("content") or ""
            reflection_prompt = [
                {
                    "role": "system",
                    "content": (
                        "You are a quality assurance reviewer. Review the following draft response "
                        "against the original user query and the tool outputs obtained. Ensure all details are "
                        "accurate, formatting is neat, and tone is highly friendly and helpful. Correct "
                        "any inaccuracies, bad formatting, or errors. Do NOT mention that you are a QA reviewer or "
                        "that you are doing a reflection pass. Output only the final improved version."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Original query: {user_query}\n\nDraft Answer: {last_answer}",
                },
            ]

            ref_resp = self._call_ollama_with_retry(reflection_prompt)
            final_answer = ref_resp.message.content or last_answer

            return final_answer
