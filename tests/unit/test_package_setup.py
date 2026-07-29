"""Smoke test — verifies the package is importable and version is set."""

import pytest

from weekend_wizard import __version__


@pytest.mark.unit
class TestPackageSetup:
    """Verify that the project scaffolding is correct."""

    def test_version_is_set(self) -> None:
        assert __version__ == "0.1.0"

    def test_version_is_string(self) -> None:
        assert isinstance(__version__, str)

    def test_subpackages_importable(self) -> None:
        """All subpackages should be importable without errors."""
        import weekend_wizard.agent  # noqa: F401
        import weekend_wizard.mcp_server  # noqa: F401
        import weekend_wizard.models  # noqa: F401
        import weekend_wizard.prompts  # noqa: F401
        import weekend_wizard.tools  # noqa: F401
        import weekend_wizard.utils  # noqa: F401
