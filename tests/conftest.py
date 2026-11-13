"""Synthetic protocol fixtures shared by the Home Assistant tests."""

from copy import deepcopy

import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
)

pytest_plugins = "pytest_homeassistant_custom_component"

BASE_URL = "https://samvev.example"
TOKEN = "synthetic-test-connection-token"  # noqa: S105
CONNECTION = {
    "schemaVersion": 1,
    "installationId": "installation-1",
    "connectionId": "connection-1",
    "householdId": "household-1",
    "name": "Synthetic Samvev",
    "timezone": "Europe/Oslo",
    "capabilities": [
        "ha.groceries.read",
        "ha.groceries.write",
        "ha.messages.read",
        "ha.messages.write",
        "ha.calendar.read",
        "ha.calendar.write",
    ],
    "grants": {
        "revision": 1,
        "listIds": ["groceries"],
        "household": True,
        "personIds": [],
        "calendarSourceIds": [],
    },
}
SNAPSHOT = {
    **CONNECTION,
    "serverNow": "2026-11-12T10:00:00Z",
    "lists": [
        {
            "id": "groceries",
            "name": "Shopping list",
            "writable": True,
            "items": [
                {
                    "id": "item-1",
                    "label": "Synthetic apples",
                    "checked": False,
                    "revision": 1,
                }
            ],
        }
    ],
    "messages": [
        {
            "id": "message-1",
            "body": "Synthetic message",
            "authorName": "Synthetic author",
            "authorType": "member",
            "audience": {"household": True, "personIds": []},
            "publishAt": "2020-01-01T00:00:00Z",
            "expiresAt": "2099-01-01T00:00:00Z",
            "importance": "normal",
            "state": "published",
            "revision": 1,
        }
    ],
    "calendars": [{"id": "samvev", "name": "Samvev", "writable": True}],
}


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations) -> None:
    """Enable custom components without changing any running HA instance."""


@pytest.fixture
def connection():
    """Return an isolated copy of a synthetic connection response."""
    return deepcopy(CONNECTION)


@pytest.fixture
def snapshot():
    """Return an isolated copy of a synthetic current snapshot."""
    return deepcopy(SNAPSHOT)


@pytest.fixture(autouse=True)
def _bounded_aiohttp_mock_response(monkeypatch):
    """Add the real content-length property missing from HA's HTTP test double."""
    monkeypatch.setattr(
        AiohttpClientMockResponse,
        "content_length",
        property(lambda response: len(response.response)),
        raising=False,
    )
