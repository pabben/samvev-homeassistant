"""Sanitized diagnostics for Samvev."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data

from .const import CONF_API_TOKEN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import SamvevConfigEntry

TO_REDACT = {CONF_API_TOKEN}


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant, entry: SamvevConfigEntry
) -> dict[str, Any]:
    """Return diagnostics without credentials or personal attention content."""
    coordinator = entry.runtime_data.coordinator
    context = coordinator.data if coordinator.last_update_success else None
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "last_update_success": coordinator.last_update_success,
        "context_projection": {
            "status": context.status if context else None,
            "attention_present": bool(context and context.next_attention),
            "attention_count": context.attention_count if context else None,
        },
    }
