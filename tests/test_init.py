"""Tests for Samvev config entry setup and lifecycle."""

from http import HTTPStatus

import pytest
from aiohttp import ClientConnectionError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samvev import async_setup_entry
from custom_components.samvev.const import CONF_API_TOKEN, CONF_BASE_URL, DOMAIN

BASE_URL = "https://samvev.example"
TOKEN = "secret-token"  # noqa: S105


def make_entry() -> MockConfigEntry:
    """Create a representative Samvev config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Samvev test",
        unique_id="instance-1",
        data={CONF_BASE_URL: BASE_URL, CONF_API_TOKEN: TOKEN},
    )


async def test_setup_sensors_and_unload(hass, aioclient_mock, caplog) -> None:
    """Set up all sensors and unload without restarting Home Assistant."""
    aioclient_mock.get(f"{BASE_URL}/api/v1/health", json={"status": "ok"})
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/context",
        json={
            "status": "connected",
            "attention_count": 1,
            "next_attention": {"id": "a1", "summary": "Pack equipment"},
        },
    )
    entry = make_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    registry = er.async_get(hass)
    status_id = registry.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{entry.entry_id}_status"
    )
    attention_id = registry.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{entry.entry_id}_next_attention"
    )
    count_id = registry.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{entry.entry_id}_attention_count"
    )
    assert hass.states.get(status_id).state == "connected"
    assert hass.states.get(attention_id).state == "Pack equipment"
    assert hass.states.get(count_id).state == "1"
    assert TOKEN not in caplog.text

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(status_id).state == "connected"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get(status_id).state == "unavailable"


async def test_setup_supports_server_without_context_endpoint(
    hass, aioclient_mock
) -> None:
    """Load against a minimal server that implements health but not projection."""
    aioclient_mock.get(f"{BASE_URL}/api/v1/health", json={"status": "ok"})
    aioclient_mock.get(f"{BASE_URL}/api/v1/context", status=HTTPStatus.NOT_FOUND)
    entry = make_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.coordinator.data.attention_count is None


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (HTTPStatus.UNAUTHORIZED, None, ConfigEntryAuthFailed),
        (HTTPStatus.OK, {}, ConfigEntryNotReady),
    ],
)
async def test_setup_maps_health_failures(
    hass, aioclient_mock, status, body, expected
) -> None:
    """Map auth and invalid/missing responses to HA lifecycle exceptions."""
    aioclient_mock.get(f"{BASE_URL}/api/v1/health", status=status, json=body)
    entry = make_entry()

    with pytest.raises(expected):
        await async_setup_entry(hass, entry)


async def test_setup_connection_failure_does_not_log_token(
    hass, aioclient_mock, caplog
) -> None:
    """Keep credentials out of HA logs when setup enters retry state."""
    aioclient_mock.get(f"{BASE_URL}/api/v1/health", exc=ClientConnectionError(TOKEN))
    entry = make_entry()
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert TOKEN not in caplog.text
