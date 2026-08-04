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

# Project root is 3 levels up from this file: src/planpilot/utils/config.py
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


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

    # --- Groq ---
    llm_provider: str = Field(
        default="ollama",
        description="LLM Provider to use ('ollama' or 'groq').",
    )
    groq_api_key: str | None = Field(
        default=None,
        description="API key for Groq Cloud.",
    )
    groq_model: str = Field(
        default="llama-3.3-70b-versatile",
        description="Groq model to use.",
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
