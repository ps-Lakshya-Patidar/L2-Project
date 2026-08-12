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
        if msg.startswith("Calling tool '"):
            clean_msg = msg.replace("Calling tool '", "").replace("' with args", " with args")
            console.print(f"[bold blue]✦ Calling MCP Tool:[/] {clean_msg}")
        elif msg.startswith("Received output from '"):
            clean_msg = msg.replace("Received output from '", "").replace("'", "")
            console.print(f"[bold green]✔ MCP Tool Output:[/] {clean_msg}")

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
