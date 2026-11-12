"""Diagnostics must not export family contents, addresses or credentials."""

import json
from unittest.mock import AsyncMock

from custom_components.samvev.api import SamvevClient
from custom_components.samvev.coordinator import SamvevDataUpdateCoordinator
from custom_components.samvev.diagnostics import async_get_config_entry_diagnostics
from custom_components.samvev.runtime import SamvevRuntimeData

from .conftest import BASE_URL, TOKEN
from .test_init import make_entry


async def test_diagnostics_content_free(hass, connection, snapshot):
    """Export just operational facts even when sensitive content is loaded."""
    entry = make_entry()
    client = AsyncMock(spec=SamvevClient)
    client.async_snapshot.return_value = snapshot
    coordinator = SamvevDataUpdateCoordinator(hass, entry, client, connection)
    entry.runtime_data = SamvevRuntimeData(client, coordinator)
    await coordinator.async_refresh()
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    serialized = json.dumps(diagnostics)
    for private in (
        TOKEN,
        BASE_URL,
        "Synthetic message",
        "item-1",
        "connection-1",
        "household-1",
    ):
        assert private not in serialized
    assert diagnostics["last_update_success"]
    assert diagnostics["poll_interval_seconds"] == 30
    await coordinator.async_shutdown()
