"""Tests for generic Samvev actions and the explicit context bridge."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samvev.api import AskResponse, EventResponse, SamvevClient
from custom_components.samvev.const import (
    CONF_API_TOKEN,
    CONF_BASE_URL,
    DOMAIN,
    SERVICE_ASK,
    SERVICE_EVENT,
)

BASE_URL = "https://samvev.example"


async def setup_entry(hass, aioclient_mock) -> MockConfigEntry:
    """Load one Samvev entry for action tests."""
    aioclient_mock.get(f"{BASE_URL}/api/v1/health", json={"status": "ok"})
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/context",
        json={"status": "connected", "attention_count": 0},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Samvev test",
        data={CONF_BASE_URL: BASE_URL, CONF_API_TOKEN: "secret-token"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_ask_action_returns_response(hass, aioclient_mock) -> None:
    """Forward generic prompt/context and return a service response."""
    entry = await setup_entry(hass, aioclient_mock)
    with patch.object(
        SamvevClient,
        "async_ask",
        new=AsyncMock(
            return_value=AskResponse("Structured answer", "request-1", {"items": 1})
        ),
    ) as ask:
        result = await hass.services.async_call(
            DOMAIN,
            SERVICE_ASK,
            {
                "prompt": "What needs attention?",
                "context": {"period": "tomorrow"},
                "config_entry_id": entry.entry_id,
            },
            blocking=True,
            return_response=True,
        )

    assert result == {
        "answer": "Structured answer",
        "request_id": "request-1",
        "data": {"items": 1},
    }
    ask.assert_awaited_once_with("What needs attention?", {"period": "tomorrow"})


async def test_event_action_sends_only_selected_entity_states(
    hass, aioclient_mock
) -> None:
    """Minimize local context and keep entity attributes out of the event."""
    entry = await setup_entry(hass, aioclient_mock)
    hass.states.async_set(
        "weather.home",
        "rainy",
        {"forecast": "sensitive and intentionally omitted"},
    )
    hass.states.async_set("person.someone", "home")
    refresh = AsyncMock()
    entry.runtime_data.coordinator.async_request_refresh = refresh

    with patch.object(
        SamvevClient,
        "async_send_event",
        new=AsyncMock(return_value=EventResponse(accepted=True, event_id="event-1")),
    ) as send_event:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_EVENT,
            {
                "event_type": "household.context_changed",
                "data": {"reason": "automation"},
                "entity_ids": ["weather.home"],
            },
            blocking=True,
        )

    send_event.assert_awaited_once()
    event_type, data, context = send_event.await_args.args
    assert event_type == "household.context_changed"
    assert data == {"reason": "automation"}
    assert context["entities"][0]["entity_id"] == "weather.home"
    assert context["entities"][0]["state"] == "rainy"
    assert "attributes" not in context["entities"][0]
    assert "person.someone" not in str(context)
    refresh.assert_awaited_once()


async def test_event_rejects_missing_selected_entity(hass, aioclient_mock) -> None:
    """Fail visibly instead of silently dropping an explicitly selected entity."""
    await setup_entry(hass, aioclient_mock)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_EVENT,
            {"event_type": "context.changed", "entity_ids": ["sensor.missing"]},
            blocking=True,
        )
