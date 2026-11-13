"""Real HA action dispatch against the versioned bridge HTTP contract."""

from copy import deepcopy
from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samvev.const import CONF_API_TOKEN, CONF_BASE_URL, DOMAIN
from custom_components.samvev.services import _runtime_for_call

BASE_URL = "https://samvev.example"
CONNECTION = {
    "schemaVersion": 1,
    "installationId": "test-instance",
    "connectionId": "ha-one",
    "householdId": "synthetic-household",
    "name": "Samvev HA",
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


def snapshot() -> dict:
    """Create a small synthetic server-authoritative projection."""
    now = dt_util.utcnow()
    return {
        **deepcopy(CONNECTION),
        "serverNow": now.isoformat(),
        "lists": [
            {
                "id": "groceries",
                "name": "Groceries",
                "writable": True,
                "items": [
                    {"id": "milk", "label": "Milk", "checked": False, "revision": 4}
                ],
            }
        ],
        "messages": [
            {
                "id": "message-one",
                "body": "Bring a coat",
                "authorName": "Samvev HA",
                "authorType": "integration",
                "audience": {"household": True, "personIds": []},
                "publishAt": (now - timedelta(minutes=1)).isoformat(),
                "expiresAt": (now + timedelta(hours=1)).isoformat(),
                "importance": "normal",
                "state": "published",
                "revision": 2,
            }
        ],
        "calendars": [{"id": "samvev", "name": "Samvev", "writable": True}],
    }


async def setup_entry(hass, aioclient_mock, data=None) -> MockConfigEntry:
    """Load the actual integration and all three platforms in the HA harness."""
    aioclient_mock.get(f"{BASE_URL}/api/v1/ha/connection", json=CONNECTION)
    aioclient_mock.get(f"{BASE_URL}/api/v1/ha/snapshot", json=data or snapshot())
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/ha/calendars/samvev/events",
        json={"events": [], "serverNow": dt_util.utcnow().isoformat()},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Samvev HA",
        unique_id="test-instance:ha-one",
        data={CONF_BASE_URL: BASE_URL, CONF_API_TOKEN: "synthetic-token"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


async def test_create_update_withdraw_message(hass, aioclient_mock) -> None:
    """Dispatch all documented message actions and retain authoritative revisions."""
    await setup_entry(hass, aioclient_mock)
    aioclient_mock.post(
        f"{BASE_URL}/api/v1/ha/messages",
        json={"message": {"id": "created", "revision": 1}},
        status=201,
    )
    result = await hass.services.async_call(
        DOMAIN,
        "create_message",
        {
            "body": "Synthetic message",
            "expires_at": (dt_util.utcnow() + timedelta(hours=1)).isoformat(),
            "audience": {"household": True},
            "request_key": "automation-operation-one",
        },
        blocking=True,
        return_response=True,
    )
    assert result == {"message": {"id": "created", "revision": 1}}
    request = next(
        call for call in aioclient_mock.mock_calls if call[0].upper() == "POST"
    )
    assert request[2]["requestKey"] == "automation-operation-one"
    assert request[2]["audience"] == {"household": True, "personIds": []}
    assert "authorName" not in request[2]
    aioclient_mock.patch(
        f"{BASE_URL}/api/v1/ha/messages/message-one",
        json={"message": {"id": "message-one", "revision": 3}},
    )
    await hass.services.async_call(
        DOMAIN,
        "update_message",
        {"message_id": "message-one", "body": "Updated coat"},
        blocking=True,
    )
    request = next(
        call for call in aioclient_mock.mock_calls if call[0].upper() == "PATCH"
    )
    assert request[2]["expectedRevision"] == 2
    aioclient_mock.post(
        f"{BASE_URL}/api/v1/ha/messages/message-one/withdraw",
        json={"message": {"id": "message-one", "revision": 3}},
    )
    await hass.services.async_call(
        DOMAIN, "withdraw_message", {"message_id": "message-one"}, blocking=True
    )
    assert any("/withdraw" in str(call[1]) for call in aioclient_mock.mock_calls)


async def test_message_conflict_and_missing_item(hass, aioclient_mock) -> None:
    """Reject missing revisions and concurrent edits without overwrite."""
    await setup_entry(hass, aioclient_mock)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "withdraw_message", {"message_id": "not-observed"}, blocking=True
        )
    aioclient_mock.patch(f"{BASE_URL}/api/v1/ha/messages/message-one", status=409)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            "update_message",
            {"message_id": "message-one", "body": "Edited"},
            blocking=True,
        )
    assert (
        len([call for call in aioclient_mock.mock_calls if call[0].upper() == "PATCH"])
        == 1
    )


async def test_message_connection_selection(hass, aioclient_mock) -> None:
    """Never select a connection silently when multiple entries are loaded."""
    entry = await setup_entry(hass, aioclient_mock)

    other = MockConfigEntry(domain=DOMAIN, title="Other", data={})
    other.add_to_hass(hass)
    other._async_set_state(hass, ConfigEntryState.LOADED, None)  # noqa: SLF001
    with pytest.raises(ServiceValidationError):
        _runtime_for_call(hass, ServiceCall(hass, DOMAIN, "withdraw_message", {}))
    assert (
        _runtime_for_call(
            hass,
            ServiceCall(
                hass, DOMAIN, "withdraw_message", {"config_entry_id": entry.entry_id}
            ),
        )
        is entry.runtime_data
    )
