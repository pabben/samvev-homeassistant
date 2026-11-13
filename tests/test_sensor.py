"""Multiple message rows, expiry, stale status and revoked-content privacy."""

from datetime import timedelta

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.samvev.sensor import SamvevSensor

from .test_services import setup_entry, snapshot


async def test_multiple_messages_are_attributes_and_expire_locally(
    hass, aioclient_mock, freezer
) -> None:
    """Keep full bodies outside state and expire without a network refresh."""
    data = snapshot()
    now = dt_util.utcnow()
    data["messages"][0]["expiresAt"] = (now + timedelta(seconds=5)).isoformat()
    data["messages"].append(
        {
            **data["messages"][0],
            "id": "message-two",
            "body": "x" * 1000,
            "expiresAt": (now + timedelta(minutes=10)).isoformat(),
        }
    )
    await setup_entry(hass, aioclient_mock, data)
    state = hass.states.get("sensor.samvev_ha_messages")
    assert state.state == "2"
    assert len(state.attributes["messages"]) == 2
    assert len(state.attributes["messages"][1]["body"]) == 1000
    freezer.move_to(now + timedelta(seconds=6))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get("sensor.samvev_ha_messages").state == "1"


async def test_revoked_data_disappears_but_connection_status_remains(
    hass, aioclient_mock
) -> None:
    """Clearing authorization removes private attributes and leaves useful status."""
    entry = await setup_entry(hass, aioclient_mock)
    coordinator = entry.runtime_data.coordinator
    messages = SamvevSensor(entry, coordinator, "messages")
    connection = SamvevSensor(entry, coordinator, "connection_status")
    assert messages.native_value == 1
    coordinator.data = {}
    coordinator.last_update_success = False
    assert messages.extra_state_attributes == {"messages": [], "stale": True}
    assert not messages.available
    assert connection.available
    assert connection.native_value == "disconnected"
    last = SamvevSensor(entry, coordinator, "last_success")
    assert last.native_value == coordinator.last_success


async def test_transient_failure_marks_last_safe_messages_stale(
    hass, aioclient_mock
) -> None:
    """Transport errors retain the last safe content while flagging unavailability."""
    entry = await setup_entry(hass, aioclient_mock)
    coordinator = entry.runtime_data.coordinator
    coordinator.last_update_success = False
    sensor = SamvevSensor(entry, coordinator, "messages")
    assert not sensor.available
    assert sensor.extra_state_attributes["stale"]
    assert len(sensor.extra_state_attributes["messages"]) == 1
