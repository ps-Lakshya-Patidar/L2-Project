"""Command Line Interface for PlanPilot.

Provides a CLI command for single-query runs and an interactive REPL mode.
Uses typer for command definition and rich for beautiful terminal outputs.
"""

from __future__ import annotations

import asyncio
import sys

# Force UTF-8 output on Windows for emojis and special characters
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import typer
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from planpilot.agent.agent import PlanPilotAgent
from planpilot.utils.config import get_settings

app = typer.Typer(
    name="planpilot",
    help="🧭 PlanPilot: An interactive local AI agent helper for planning and event discovery.",
    add_completion=False,
)
console = Console()


class StatusIndicator:
    """Helper to display updating progress messages with a spinner."""

    def __init__(self, console: Console) -> None:
        self.console = console
        self.current_status = "Thinking..."
        self._live: Live | None = None

    def update(self, status: str) -> None:
        self.current_status = status
        if self._live:
            self._live.update(self._render())

    def _render(self) -> Panel:
        return Panel(
            Spinner("dots", text=Text(self.current_status, style="cyan")),
            border_style="bold blue",
            title="Wizard Action",
            title_align="left",
        )

    def start(self) -> None:
        self._live = Live(self._render(), console=self.console, refresh_per_second=10)
        self._live.start()

    def stop(self) -> None:
        if self._live:
            self._live.stop()
            self._live = None


async def run_agent_interactive(agent: PlanPilotAgent, query: str) -> None:
    """Run a single query and display step-by-step progress using Rich."""
    indicator = StatusIndicator(console)
    indicator.start()

    async def callback(msg: str) -> None:
        indicator.update(msg)
        if msg.startswith("TOOL_TRACE:start:"):
            parts = msg.split(":", 3)
            tool_name = parts[2] if len(parts) > 2 else "tool"
            args_part = parts[3] if len(parts) > 3 else "{}"
            console.print(f"[bold blue]✦ Calling MCP Tool:[/] {tool_name} {args_part}")
        elif msg.startswith("TOOL_TRACE:end:"):
            parts = msg.split(":", 3)
            tool_name = parts[2] if len(parts) > 2 else "tool"
            source = parts[3] if len(parts) > 3 else "live"
            icon = "⚡" if source == "cache" else "✔"
            console.print(f"[bold green]{icon} MCP Tool Output:[/] {tool_name} ({source})")

    try:
        response = await agent.run_query(query, status_callback=callback)
        indicator.stop()

        # Display the result in a beautiful Markdown panel
        console.print("\n")
        console.print(
            Panel(
                Markdown(response),
                title="🧭 PlanPilot Response",
                border_style="green",
                padding=(1, 2),
            )
        )

        m = getattr(agent, "last_metrics", None)
        if m:
            in_tok = m.get("input_tokens", 0)
            out_tok = m.get("output_tokens", 0)
            mod = m.get("model", "").lower()
            prov = m.get("provider", "").lower()

            # Cost calculations
            if prov == "ollama":
                actual_str = "$0.00 (Local)"
            elif ":free" in mod or mod == "openrouter/free":
                actual_str = "$0.00 (Free Tier)"
            else:
                act_cost = (in_tok * 0.15 / 1e6) + (out_tok * 0.60 / 1e6)
                actual_str = f"${act_cost:.6f}"

            prod_in = 0.50 if any(k in mod for k in ["70b", "large", "sonnet", "gpt-4o"]) else 0.15
            prod_out = 1.50 if any(k in mod for k in ["70b", "large", "sonnet", "gpt-4o"]) else 0.60
            prod_cost = (in_tok * prod_in / 1e6) + (out_tok * prod_out / 1e6)
            cost_per_1k = prod_cost * 1000

            metrics_text = (
                f"[bold cyan]📊 Evaluation Metrics[/]\n"
                f"[dim]LLM:[/] {m.get('provider')}/{m.get('model')}  |  "
                f"[dim]Latency:[/] {m.get('latency_sec')}s  |  "
                f"[dim]Actual Cost:[/] {actual_str}  |  "
                f"[bold green]Est. Production Cost:[/] ~${prod_cost:.5f} (${cost_per_1k:.2f}/1k)\n"
                f"[dim]LLM Steps:[/] {m.get('llm_calls')}  |  "
                f"[dim]Tool Calls:[/] {m.get('tool_calls')}  |  "
                f"[dim]Input Tokens:[/] {in_tok}  |  "
                f"[dim]Output Tokens:[/] {out_tok}  |  "
                f"[dim]Total Tokens:[/] {m.get('total_tokens')}"
            )
            console.print(
                Panel(
                    metrics_text,
                    border_style="cyan",
                    padding=(0, 2),
                )
            )
        console.print("\n")
    except Exception as e:
        indicator.stop()
        console.print(
            Panel(f"[bold red]Error:[/] {str(e)}", title="Execution Failed", border_style="red")
        )


@app.command()
def query(
    user_query: str | None = typer.Argument(
        None, help="Natural language prompt for the agent. If omitted, starts interactive mode."
    ),
    model: str | None = typer.Option(
        None, "--model", "-m", help="Override the Ollama model (default is llama3.2:3b)."
    ),
) -> None:
    """Run PlanPilot to answer your questions."""
    settings = get_settings()
    if model:
        settings.ollama_model = model

    console.print(
        Panel(
            f"[bold gold1]🧭 PlanPilot[/]\n"
            f"[dim]Model: {settings.ollama_model} | URL: {settings.ollama_base_url}[/]\n\n"
            f"Ask me about weather, book recommendations, or local event discovery!",
            border_style="bold gold1",
            padding=(1, 2),
        )
    )

    agent = PlanPilotAgent()

    if user_query:
        # Single query mode
        asyncio.run(run_agent_interactive(agent, user_query))
    else:
        # Interactive REPL mode
        console.print(
            "[bold yellow]Entering Interactive Mode. Type 'exit' or 'quit' to end session.[/]\n"
        )
        while True:
            try:
                prompt = console.input("[bold purple]You ──► [/]")
                if prompt.strip().lower() in ("exit", "quit"):
                    console.print("[bold green]Goodbye! Have a great day! 🧭[/]")
                    break
                if not prompt.strip():
                    continue
                asyncio.run(run_agent_interactive(agent, prompt))
            except (KeyboardInterrupt, EOFError):
                console.print("\n[bold green]Goodbye! Have a great day! 🧭[/]")
                break


@app.command()
def ui() -> None:
    """Start the PlanPilot Streamlit Web UI portal."""
    import subprocess
    from pathlib import Path

    script_path = Path(__file__).resolve().parent / "ui" / "streamlit_app.py"

    # Run streamlit as a subprocess
    console.print("[bold purple]🧭 Igniting the engine... Launching PlanPilot Web UI...[/]")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(script_path)])


def main() -> None:
    """App entrypoint."""
    app()


if __name__ == "__main__":
    main()
