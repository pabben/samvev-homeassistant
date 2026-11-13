"""Connection lifecycle, revocation and durable mutation recovery tests."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samvev import async_remove_entry, async_setup_entry
from custom_components.samvev.api import (
    SamvevAuthenticationError,
    SamvevClient,
    SamvevConflictError,
    SamvevConnectionError,
)
from custom_components.samvev.const import CONF_API_TOKEN, CONF_BASE_URL, DOMAIN
from custom_components.samvev.coordinator import SamvevDataUpdateCoordinator

from .conftest import BASE_URL, TOKEN


def make_entry():
    """Build a stable, synthetic connection config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Synthetic",
        unique_id="installation-1:connection-1",
        data={CONF_BASE_URL: BASE_URL, CONF_API_TOKEN: TOKEN},
    )


async def test_setup_reload_unload(hass, aioclient_mock, connection, snapshot, caplog):
    """Load the supported platforms and shut down polling on unload."""
    aioclient_mock.get(f"{BASE_URL}/api/v1/ha/connection", json=connection)
    aioclient_mock.get(f"{BASE_URL}/api/v1/ha/snapshot", json=snapshot)
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.coordinator.data == snapshot
    assert entry.runtime_data.coordinator.update_interval.total_seconds() == 30
    assert await hass.config_entries.async_reload(entry.entry_id)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert TOKEN not in caplog.text


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SamvevAuthenticationError(), ConfigEntryAuthFailed),
        (SamvevConnectionError(), ConfigEntryNotReady),
    ],
)
async def test_setup_handshake_errors(hass, error, expected):
    """Reject unauthenticated setup and retry network failures."""
    with (
        patch(
            "custom_components.samvev.SamvevClient.async_connection", side_effect=error
        ),
        pytest.raises(expected),
    ):
        await async_setup_entry(hass, make_entry())


async def test_setup_identity_mismatch(hass, connection):
    """A changed server connection must reauthorize before exposing content."""
    connection["householdId"] = "other-household"
    connection["connectionId"] = "other-connection"
    with (
        patch(
            "custom_components.samvev.SamvevClient.async_connection",
            return_value=connection,
        ),
        pytest.raises(ConfigEntryAuthFailed),
    ):
        await async_setup_entry(hass, make_entry())


async def test_network_preserves_snapshot_revocation_clears(hass, connection, snapshot):
    """Differentiate stale transport failures from lost disclosure authority."""
    client = AsyncMock(spec=SamvevClient)
    client.async_snapshot.side_effect = [
        snapshot,
        SamvevConnectionError(),
        SamvevAuthenticationError(),
    ]
    entry = make_entry()
    entry.add_to_hass(hass)
    coordinator = SamvevDataUpdateCoordinator(hass, entry, client, connection)
    await coordinator.async_refresh()
    last_success = coordinator.last_success
    await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert coordinator.data == snapshot
    assert coordinator.last_success == last_success
    await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert coordinator.authorization_revoked
    assert coordinator.data == {}
    await hass.async_block_till_done()
    await coordinator.async_shutdown()


async def test_durable_ambiguous_retry_and_double_press(hass, connection, snapshot):
    """Reuse the same key after response loss, restart and a repeated press."""
    entry = make_entry()
    client = AsyncMock(spec=SamvevClient)
    client.async_snapshot.return_value = snapshot
    client.async_mutate.side_effect = [
        SamvevConnectionError(),
        {"item": {"id": "item-1", "revision": 2}},
        {"item": {"id": "item-1", "revision": 2}},
    ]
    coordinator = SamvevDataUpdateCoordinator(hass, entry, client, connection)
    operation = {"checked": True, "expectedRevision": 1}
    with pytest.raises(SamvevConnectionError):
        await coordinator.async_mutate(
            "PATCH", "lists/groceries/items/item-1", operation
        )
    first_key = client.async_mutate.call_args.args[2]["requestKey"]
    await coordinator.async_shutdown()
    restarted = SamvevDataUpdateCoordinator(hass, entry, client, connection)
    await restarted.async_mutate("PATCH", "lists/groceries/items/item-1", operation)
    second_key = client.async_mutate.call_args.args[2]["requestKey"]
    await restarted.async_mutate("PATCH", "lists/groceries/items/item-1", operation)
    assert (
        first_key == second_key == client.async_mutate.call_args.args[2]["requestKey"]
    )
    assert restarted.data == snapshot
    saved = await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.operations").async_load()
    serialized = json.dumps(saved)
    assert "checked" not in serialized
    assert TOKEN not in serialized
    assert "item-1" not in serialized
    await restarted.async_shutdown()
    await async_remove_entry(hass, entry)
    assert (
        await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.operations").async_load()
        is None
    )


async def test_conflict_refreshes_but_never_silently_reapplies(
    hass, connection, snapshot
):
    """A competing writer wins until the user reviews the new server revision."""
    client = AsyncMock(spec=SamvevClient)
    client.async_snapshot.return_value = snapshot
    client.async_mutate.side_effect = SamvevConflictError()
    coordinator = SamvevDataUpdateCoordinator(hass, make_entry(), client, connection)
    with pytest.raises(SamvevConflictError):
        await coordinator.async_mutate(
            "PATCH",
            "lists/groceries/items/item-1",
            {"checked": True, "expectedRevision": 1},
        )
    client.async_mutate.assert_awaited_once()
    assert client.async_mutate.call_args.args[2]["expectedRevision"] == 1
    assert coordinator.data == snapshot
    await coordinator.async_shutdown()
