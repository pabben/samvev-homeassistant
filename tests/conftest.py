"""Shared fixtures for Samvev tests."""

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations) -> None:
    """Enable loading custom integrations in Home Assistant tests."""
