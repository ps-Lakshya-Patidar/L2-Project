"""Application-wide configuration using pydantic-settings.

Reads from environment variables and .env files, with sensible defaults
for local development. All config is validated at startup.

Usage:
    from planpilot.utils.config import get_settings
    settings = get_settings()
    print(settings.ollama_base_url)
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Dynamically locate the project root by searching for .env in parent directories.
# Falls back to the current working directory if not found.

def _find_project_root() -> Path:
    """Walk up from this file's location looking for a .env file (max 6 levels).

    Falls back to CWD if no .env is found, so pydantic-settings can still
    read from environment variables and its own defaults.
    """
    anchor = Path(__file__).resolve().parent
    for _ in range(6):
        if (anchor / ".env").is_file():
            return anchor
        if anchor.parent == anchor:  # filesystem root reached
            break
        anchor = anchor.parent
    # Fallback: current working directory
    return Path.cwd()


_PROJECT_ROOT = _find_project_root()


class Settings(BaseSettings):
    """PlanPilot application settings.

    Values are loaded in this priority order (highest wins):
    1. Environment variables
    2. .env file
    3. Default values defined here
    """

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Don't fail on unrecognized env vars
    )

    # --- Ollama ---
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Base URL for the Ollama API server.",
    )
    ollama_model: str = Field(
        default="llama3.2:3b",
        description="Ollama model to use for reasoning.",
    )
    ollama_timeout: float = Field(
        default=120.0,
        description="Timeout in seconds for Ollama API calls.",
    )

    # --- LLM Provider Selection ---
    llm_provider: str = Field(
        default="gemini",
        description="LLM Provider to use ('gemini', 'groq', or 'ollama').",
    )

    # --- Google Gemini ---
    google_api_key: str | None = Field(
        default=None,
        description="API key for Google Gemini / Google AI Studio.",
    )
    gemini_model: str = Field(
        default="gemini-3.6-flash",
        description="Google Gemini model to use (e.g. gemini-3.6-flash, gemini-3.7-flash).",
    )

    # --- Groq ---
    groq_api_key: str | None = Field(
        default=None,
        description="API key for Groq Cloud.",
    )
    groq_model: str = Field(
        default="openai/gpt-oss-20b",
        description="Groq model to use.",
    )

    # --- SerpAPI ---
    serpapi_api_key: str | None = Field(
        default=None,
        description="API key for SerpAPI (Google Events search).",
    )

    # --- MCP Server ---
    mcp_server_host: str = Field(
        default="localhost",
        description="Host for the MCP server (used in SSE/HTTP mode).",
    )
    mcp_server_port: int = Field(
        default=8080,
        description="Port for the MCP server (used in SSE/HTTP mode).",
    )

    # --- Logging ---
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).",
    )

    # --- HTTP Client ---
    http_timeout: float = Field(
        default=30.0,
        description="Default timeout in seconds for external API calls.",
    )
    http_max_retries: int = Field(
        default=3,
        description="Maximum retry attempts for failed HTTP requests.",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance.

    The settings are loaded once and reused across the application.
    Use this function instead of creating Settings() directly.
    """
    return Settings()
