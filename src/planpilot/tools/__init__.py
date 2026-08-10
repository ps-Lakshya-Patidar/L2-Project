"""Tool implementations — weather, books, and event discovery."""

from .services import (
    get_weather_data,
    search_books_data,
    discover_events_data,
)

__all__ = ['get_weather_data', 'search_books_data', 'discover_events_data']