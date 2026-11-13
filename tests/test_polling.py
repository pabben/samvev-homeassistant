"""Exercise real HA timer scheduling, transient recovery and unload cleanup."""

from copy import deepcopy
from datetime import timedelta
from itertools import chain, repeat

from aiohttp import ClientConnectionError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.samvev.const import CONF_API_TOKEN, CONF_BASE_URL, DOMAIN

from .conftest import BASE_URL, TOKEN

SNAPSHOT_URL = f"{BASE_URL}/api/v1/ha/snapshot"


def _entry() -> MockConfigEntry:
    """Return a real config entry, avoiding manual coordinator refresh calls."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Synthetic polling",
        unique_id="installation-1:connection-1",
        data={CONF_BASE_URL: BASE_URL, CONF_API_TOKEN: TOKEN},
    )


def _response(data):
    """Make a bounded HTTP response for the existing aiohttp HA test double."""
    return AiohttpClientMockResponse("get", URL(SNAPSHOT_URL), json=data)


def _snapshot_requests(mock) -> int:
    """Count actual HTTP snapshot requests independently of entity reads."""
    return sum(str(call[1]) == SNAPSHOT_URL for call in mock.mock_calls)


async def _advance(hass, freezer, instant) -> None:
    """Let HA run due timers with its documented subsecond coordinator jitter."""
    freezer.move_to(instant)
    async_fire_time_changed(hass, instant)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_scheduled_snapshot_changes_at_thirty_seconds_and_stops_on_unload(
    hass, aioclient_mock, connection, snapshot, freezer
) -> None:
    """Update standard entities by HA's scheduler, with no request_refresh call."""
    freezer.move_to("2026-11-12T10:00:00Z")
    start = dt_util.utcnow()
    snapshot["calendars"] = []
    changed = deepcopy(snapshot)
    changed["serverNow"] = (start + timedelta(seconds=30)).isoformat()
    changed["lists"][0]["items"][0].update(checked=True, revision=2)
    changed["messages"][0].update(body="Synthetic scheduled update", revision=2)
    responses = chain([_response(snapshot)], repeat(_response(changed)))

    async def respond(_method, _url, _data):
        return next(responses)

    aioclient_mock.get(f"{BASE_URL}/api/v1/ha/connection", json=connection)
    aioclient_mock.get(SNAPSHOT_URL, side_effect=respond)
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED
    assert _snapshot_requests(aioclient_mock) == 1
    assert hass.states.get("todo.synthetic_polling_groceries").state == "1"
    assert entry.runtime_data.coordinator.data["messages"][0]["revision"] == 1

    await _advance(hass, freezer, start + timedelta(seconds=29))
    assert _snapshot_requests(aioclient_mock) == 1
    assert hass.states.get("todo.synthetic_polling_groceries").state == "1"

    await _advance(hass, freezer, start + timedelta(seconds=30))
    assert _snapshot_requests(aioclient_mock) == 2
    assert hass.states.get("todo.synthetic_polling_groceries").state == "0"
    message_state = hass.states.get("sensor.synthetic_polling_messages")
    assert message_state.attributes["messages"][0]["body"] == (
        "Synthetic scheduled update"
    )
    assert entry.runtime_data.coordinator.last_success == start + timedelta(seconds=30)
    status = hass.states.get("sensor.synthetic_polling_connection_status")
    assert status.state == "connected"
    assert status.attributes["poll_interval_seconds"] == 30

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    restored = hass.states.get("todo.synthetic_polling_groceries")
    assert restored is None or restored.state == "unavailable"
    await _advance(hass, freezer, start + timedelta(seconds=90))
    assert _snapshot_requests(aioclient_mock) == 2


async def test_scheduled_transport_failure_retains_safe_data_and_polling_recovers(
    hass, aioclient_mock, connection, snapshot, freezer
) -> None:
    """Fail one scheduled read, then recover automatically on the next interval."""
    freezer.move_to("2026-11-12T10:00:00Z")
    start = dt_util.utcnow()
    snapshot["calendars"] = []
    recovered = deepcopy(snapshot)
    recovered["lists"][0]["items"][0].update(
        label="Synthetic recovered apples", revision=2
    )
    responses = chain(
        [
            _response(snapshot),
            AiohttpClientMockResponse(
                "get", URL(SNAPSHOT_URL), exc=ClientConnectionError("Synthetic outage")
            ),
        ],
        repeat(_response(recovered)),
    )

    async def respond(_method, _url, _data):
        return next(responses)

    aioclient_mock.get(f"{BASE_URL}/api/v1/ha/connection", json=connection)
    aioclient_mock.get(SNAPSHOT_URL, side_effect=respond)
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = entry.runtime_data.coordinator
    last_success = coordinator.last_success
    assert _snapshot_requests(aioclient_mock) == 1

    await _advance(hass, freezer, start + timedelta(seconds=30))
    assert _snapshot_requests(aioclient_mock) == 2
    assert not coordinator.last_update_success
    assert coordinator.last_success == last_success
    assert coordinator.data["lists"][0]["items"][0]["label"] == "Synthetic apples"
    assert hass.states.get("todo.synthetic_polling_groceries").state == "unavailable"
    assert hass.states.get("sensor.synthetic_polling_connection_status").state == (
        "disconnected"
    )
    stale_messages = hass.states.get("sensor.synthetic_polling_messages")
    assert stale_messages.state == "unavailable"
    # HA deliberately suppresses value attributes on unavailable entities; the
    # coordinator keeps the last safe snapshot for automatic recovery.
    assert "messages" not in stale_messages.attributes
    assert coordinator.data["messages"][0]["body"] == "Synthetic message"

    await _advance(hass, freezer, start + timedelta(seconds=60))
    assert _snapshot_requests(aioclient_mock) == 3
    assert coordinator.last_update_success
    assert coordinator.last_success == start + timedelta(seconds=60)
    assert coordinator.data["lists"][0]["items"][0]["label"] == (
        "Synthetic recovered apples"
    )
    assert hass.states.get("todo.synthetic_polling_groceries").state == "1"
    assert hass.states.get("sensor.synthetic_polling_connection_status").state == (
        "connected"
    )
    assert await hass.config_entries.async_unload(entry.entry_id)
    await _advance(hass, freezer, start + timedelta(seconds=120))
    assert _snapshot_requests(aioclient_mock) == 3
