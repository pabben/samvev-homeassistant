"""Operational diagnostics without credentials, addresses or family content."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import SamvevConfigEntry


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant, entry: SamvevConfigEntry
) -> dict[str, Any]:
    """Export only connection health and protocol facts."""
    coordinator = entry.runtime_data.coordinator
    return {
        "schema_version": coordinator.connection.get("schemaVersion"),
        "last_update_success": coordinator.last_update_success,
        "authorization_revoked": coordinator.authorization_revoked,
        "last_success": coordinator.last_success.isoformat()
        if coordinator.last_success
        else None,
        "poll_interval_seconds": coordinator.update_interval.total_seconds()
        if coordinator.update_interval
        else None,
    }
