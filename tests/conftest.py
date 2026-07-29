"""Shared pytest fixtures for Weekend Wizard tests."""

import pytest


@pytest.fixture
def sample_city() -> str:
    """Provide a default city name for weather-related tests."""
    return "London"
