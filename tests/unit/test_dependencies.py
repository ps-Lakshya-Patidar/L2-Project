"""Dependency smoke tests — verify all runtime dependencies are importable."""

import pytest


@pytest.mark.unit
class TestRuntimeDependencies:
    """Verify that all runtime dependencies installed correctly."""

    def test_httpx_importable(self) -> None:
        import httpx  # noqa: F401

    def test_ollama_importable(self) -> None:
        import ollama  # noqa: F401

    def test_mcp_importable(self) -> None:
        import mcp  # noqa: F401

    def test_pydantic_importable(self) -> None:
        import pydantic  # noqa: F401

    def test_pydantic_settings_importable(self) -> None:
        import pydantic_settings  # noqa: F401

    def test_tenacity_importable(self) -> None:
        import tenacity  # noqa: F401

    def test_typer_importable(self) -> None:
        import typer  # noqa: F401

    def test_rich_importable(self) -> None:
        import rich  # noqa: F401


@pytest.mark.unit
class TestDependencyVersions:
    """Verify minimum version constraints are satisfied."""

    def test_pydantic_v2(self) -> None:
        import pydantic

        major = int(pydantic.VERSION.split(".")[0])
        assert major >= 2, f"Pydantic v2+ required, got {pydantic.VERSION}"

    def test_httpx_version(self) -> None:
        import httpx

        parts = httpx.__version__.split(".")
        minor = int(parts[1])
        assert minor >= 27 or int(parts[0]) >= 1, (
            f"httpx 0.27+ required, got {httpx.__version__}"
        )
